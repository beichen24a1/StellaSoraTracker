import json
import unittest
from datetime import datetime, timedelta

from stellasora_toolkit.catalog import TRAVELER_NAMES
from stellasora_toolkit.gacha_display import (
    CN_TIMEZONE,
    SparkReward,
    build_spark_rewards,
    insert_spark_rewards,
)
from stellasora_toolkit.gacha_stats import (
    FiveStarPull,
    build_banner_stats_with_shared_pity,
    build_category_stat,
)


def timestamp(day, hour=12):
    return int(datetime.fromisoformat(day).replace(hour=hour, tzinfo=CN_TIMEZONE).timestamp())


def group(gid, count, day="2026-10-08", item_id=211001):
    return {"Gid": gid, "Time": timestamp(day), "Ids": [item_id] * count}


def real_pull(gid, day, item_id=110, position=1):
    return FiveStarPull(item_id, "traveler", TRAVELER_NAMES[item_id], 10, timestamp(day), position, gid)


BANNERS = {
    10110: ("first banner", "2026-10-01", "2026-10-15", TRAVELER_NAMES[110]),
    11110: ("rerun banner", "2026-11-01", "2026-11-15", TRAVELER_NAMES[110]),
    10160: ("other traveler", "2026-10-01", "2026-10-15", TRAVELER_NAMES[160]),
    20110: ("disc banner", "2026-10-01", "2026-10-15", TRAVELER_NAMES[110]),
    1: ("standard traveler", "2026-10-01", "2026-10-15", TRAVELER_NAMES[110]),
    2: ("standard disc", "2026-10-01", "2026-10-15", TRAVELER_NAMES[110]),
}


class SparkDisplayTests(unittest.TestCase):
    def test_threshold_emits_one_reward_even_above_240_pulls(self):
        for count, expected in ((0, 0), (119, 0), (120, 1), (121, 1), (240, 1), (360, 1)):
            with self.subTest(count=count):
                rewards = build_spark_rewards([group(10110, count)], BANNERS)
                self.assertEqual(len(rewards), expected)
                if expected:
                    self.assertEqual(rewards[10110].item_id, 110)
                    self.assertEqual(rewards[10110].kind, "traveler")

    def test_only_limited_traveler_pools_are_eligible(self):
        groups = [group(gid, 120) for gid in (1, 2, 10110, 20110, 21110)]
        self.assertEqual(set(build_spark_rewards(groups, BANNERS)), {10110})

    def test_threshold_counts_all_pulls_not_just_five_stars(self):
        groups = [group(10110, 60), group(10110, 59, item_id=110), group(10110, 1, item_id=135)]
        self.assertEqual(set(build_spark_rewards(groups, BANNERS)), {10110})

    def test_first_run_and_rerun_do_not_share_progress_for_same_up(self):
        groups = [group(10110, 119), group(11110, 119, "2026-11-08")]
        self.assertEqual(build_spark_rewards(groups, BANNERS), {})
        groups.append(group(11110, 1, "2026-11-09"))
        self.assertEqual(set(build_spark_rewards(groups, BANNERS)), {11110})
        groups.append(group(10110, 1, "2026-10-09"))
        self.assertEqual(set(build_spark_rewards(groups, BANNERS)), {10110, 11110})

    def test_same_gid_outside_period_never_contributes(self):
        groups = [
            group(10110, 120, "2026-09-30"),
            group(10110, 119),
            group(10110, 120, "2026-10-16"),
        ]
        self.assertEqual(build_spark_rewards(groups, BANNERS), {})

    def test_period_uses_china_calendar_days_and_inclusive_end_day(self):
        start = timestamp("2026-10-01", 0)
        end = timestamp("2026-10-16", 0)
        groups = [
            {"Gid": 10110, "Time": start - 1, "Ids": [211001] * 120},
            {"Gid": 10110, "Time": start, "Ids": [211001] * 60},
            {"Gid": 10110, "Time": end - 1, "Ids": [211001] * 60},
            {"Gid": 10110, "Time": end, "Ids": [211001] * 120},
        ]
        reward = build_spark_rewards(groups, BANNERS)[10110]
        self.assertEqual(reward.period_start, start)
        self.assertEqual(reward.period_end, end)
        self.assertEqual(reward.last_pull_time, end - 1)
        self.assertEqual(CN_TIMEZONE.utcoffset(None), timedelta(hours=8))

    def test_reward_resolves_official_up_not_actual_off_banner_result(self):
        info = {10160: ("summer", "2026-10-01", "2026-10-15", " \u8587\u6d1b ( \u76db\u590f ) ")}
        reward = build_spark_rewards([group(10160, 120, item_id=110)], info)[10160]
        self.assertEqual(reward.item_id, 160)

    def test_unknown_banner_or_unknown_up_is_not_guessed(self):
        info = {10110: ("unknown up", "2026-10-01", "2026-10-15", "unknown traveler")}
        self.assertEqual(build_spark_rewards([group(10110, 120), group(10111, 120)], info), {})

    def test_malformed_record_is_ignored_and_numeric_gid_strings_work(self):
        groups = [
            {"Gid": None, "Time": timestamp("2026-10-08"), "Ids": [211001] * 120},
            {"Gid": 10110, "Time": "invalid", "Ids": [211001] * 120},
            {"Gid": 10110, "Time": timestamp("2026-10-08"), "Ids": "not an array"},
        ]
        self.assertEqual(build_spark_rewards(groups, BANNERS), {})
        groups.append(group("10110", 120))
        self.assertEqual(set(build_spark_rewards(groups, BANNERS)), {10110})

    def test_inserts_before_period_first_real_hit_without_reordering_actual_pulls(self):
        groups = [group(10110, 120), group(11110, 120, "2026-11-08")]
        rewards = build_spark_rewards(groups, BANNERS)
        pulls = (
            real_pull(11110, "2026-11-07"),
            real_pull(11110, "2026-11-03", position=2),
            real_pull(10110, "2026-10-07", position=3),
            real_pull(10110, "2026-10-03", position=4),
        )
        result = insert_spark_rewards(pulls, rewards)
        self.assertEqual(result, (rewards[11110], pulls[0], pulls[1], rewards[10110], pulls[2], pulls[3]))
        self.assertEqual(tuple(item for item in result if isinstance(item, FiveStarPull)), pulls)
        self.assertEqual(sum(isinstance(item, SparkReward) for item in result), 2)

    def test_reward_only_period_is_shown_in_chronological_position(self):
        rewards = build_spark_rewards([group(10110, 120)], BANNERS)
        pulls = (real_pull(10160, "2026-10-09"), real_pull(10160, "2026-10-07"))
        self.assertEqual(insert_spark_rewards(pulls, rewards), (pulls[0], rewards[10110], pulls[1]))
        self.assertEqual(insert_spark_rewards((), rewards), (rewards[10110],))

    def test_same_gid_older_period_hit_is_not_used_as_insertion_anchor(self):
        rewards = build_spark_rewards([group(10110, 120)], BANNERS)
        pulls = (real_pull(10160, "2026-10-09"), real_pull(10160, "2026-10-07"), real_pull(10110, "2026-09-01"))
        self.assertEqual(insert_spark_rewards(pulls, rewards), (pulls[0], rewards[10110], pulls[1], pulls[2]))

    def test_multiple_reward_only_periods_are_newest_first(self):
        rewards = build_spark_rewards([group(10110, 120), group(11110, 120, "2026-11-08")], BANNERS)
        self.assertEqual(insert_spark_rewards((), rewards), (rewards[11110], rewards[10110]))

    def test_display_leaves_archive_bytes_and_statistics_unchanged(self):
        groups = [group(10110, 99), group(10110, 1, item_id=110), group(10110, 20)]
        before = json.dumps(groups, sort_keys=True, separators=(",", ":")).encode("utf-8")
        category_before = build_category_stat(groups)
        banners_before = build_banner_stats_with_shared_pity(groups)
        rewards = build_spark_rewards(groups, BANNERS)
        entries = insert_spark_rewards(category_before.five_stars, rewards)
        self.assertEqual(len(entries), 2)
        self.assertEqual(json.dumps(groups, sort_keys=True, separators=(",", ":")).encode("utf-8"), before)
        self.assertEqual(build_category_stat(groups), category_before)
        self.assertEqual(build_banner_stats_with_shared_pity(groups), banners_before)
        self.assertEqual(category_before.total_pulls, 120)
        self.assertEqual(category_before.current_pity, 20)
        self.assertEqual(category_before.average_pulls, 120)
        self.assertEqual(len(category_before.five_stars), 1)
        self.assertEqual(category_before.five_stars[0].pity, 100)


if __name__ == "__main__":
    unittest.main()
