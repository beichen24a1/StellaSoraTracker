import copy
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from stellasora_toolkit.gacha_display import CN_TIMEZONE, build_spark_rewards
from stellasora_toolkit.gacha_stats import (
    CATEGORY_ANNIVERSARY, CATEGORY_DISC_LIMITED, CATEGORY_TRAVELER_LIMITED,
    CATEGORY_TRAVELER_STANDARD, build_category_stat, build_banner_stats_with_shared_pity,
    classify_history_category,
)
from stellasora_toolkit.gui import (
    GACHA_CATEGORY_ORDER, GACHA_CATEGORY_PITY_LIMITS, OFFICIAL_LIMITED_POOL_INFO,
    SPECIAL_POOL_INFO, StellaSoraApp,
)
from stellasora_toolkit.service import Snapshot


NEW_BANNERS = (
    (10162, 162, "尘沙（源初）", "邂逅源初之剑", "2026-10-20", "2026-11-10"),
    (20162, 214066, "指引前路的启明星", "心意凝于剑尖", "2026-10-20", "2026-11-10"),
    (11115, 115, "火垂", "乘光而起的星之砂", "2026-10-27", "2026-11-17"),
    (21115, 214051, "星之所向", "若能触及那片繁星", "2026-10-27", "2026-11-17"),
)


def group(gid, ids, timestamp=1792490400):
    return {"Gid": gid, "Time": timestamp, "Ids": ids}


class AnniversaryBannerTests(unittest.TestCase):
    def test_new_limited_and_announced_rerun_metadata(self):
        for gid, item_id, name, title, start, end in NEW_BANNERS:
            with self.subTest(gid=gid):
                self.assertEqual(OFFICIAL_LIMITED_POOL_INFO[gid], (title, start, end, name))
                self.assertTrue(StellaSoraApp._is_up_item(gid, item_id))
                self.assertFalse(StellaSoraApp._is_up_item(gid, 144))
                expected = CATEGORY_TRAVELER_LIMITED if gid < 20000 else CATEGORY_DISC_LIMITED
                self.assertEqual(classify_history_category([group(gid, [])]), expected)

    def test_anniversary_is_not_a_limited_up_banner(self):
        self.assertEqual(classify_history_category([group(1001, [])]), CATEGORY_ANNIVERSARY)
        self.assertEqual(GACHA_CATEGORY_PITY_LIMITS[CATEGORY_ANNIVERSARY], 160)
        self.assertEqual(SPECIAL_POOL_INFO[1001], ("星途一载·予缘重聚", "2026-10-20", "2026-11-10"))
        self.assertNotIn(1001, OFFICIAL_LIMITED_POOL_INFO)
        self.assertEqual(GACHA_CATEGORY_ORDER[-1], CATEGORY_ANNIVERSARY)

    def test_raw_category_six_and_mixed_raw_groups_are_bucketed_without_mutation(self):
        categories = {
            1: [group(10162, [162]), group(1001, [144])],
            2: [group(1, [155])],
            6: [group(1001, [133])],
        }
        original = copy.deepcopy(categories)
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.snapshot = Snapshot([], gacha_categories=categories)
        semantic = app._semantic_gacha_categories()
        self.assertEqual(len(semantic[CATEGORY_TRAVELER_LIMITED]), 1)
        self.assertEqual(len(semantic[CATEGORY_ANNIVERSARY]), 2)
        self.assertEqual(len(semantic[CATEGORY_TRAVELER_STANDARD]), 1)
        self.assertEqual(categories, original)

    def test_anniversary_five_stars_reset_pity_independent_of_limited(self):
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.snapshot = Snapshot([], gacha_categories={
            1: [group(10162, [162, 211001, 144, 211001, 155, 211001])],
            6: [group(1001, [211001, 133, 211001, 144, 211001])],
        })
        semantic = app._semantic_gacha_categories()
        anniversary = build_category_stat(semantic[CATEGORY_ANNIVERSARY], is_up=app._is_up_item)
        limited = build_category_stat(semantic[CATEGORY_TRAVELER_LIMITED], is_up=app._is_up_item)
        self.assertEqual(anniversary.current_pity, 1)
        self.assertEqual([hit.pity for hit in anniversary.five_stars], [2, 2])
        self.assertEqual(anniversary.average_pulls, 2)
        self.assertEqual(limited.current_pity, 5)
        self.assertEqual(build_banner_stats_with_shared_pity(semantic[CATEGORY_TRAVELER_LIMITED])[0].five_stars[0].pity, 2)

    def test_chitose_shia_standard_and_historical_up_are_preserved(self):
        for item_id in (144, 155):
            with self.subTest(item_id=item_id):
                self.assertTrue(StellaSoraApp._is_up_item(1, item_id))
                self.assertTrue(StellaSoraApp._is_up_item(10000 + item_id, item_id))
                self.assertTrue(StellaSoraApp._is_up_item(11000 + item_id, item_id))
                self.assertFalse(StellaSoraApp._is_up_item(10162, item_id))
                standard = build_category_stat([group(1, [211001, item_id, 211001])], is_up=StellaSoraApp._is_up_item)
                self.assertEqual(standard.current_pity, 1)
                self.assertEqual(standard.five_stars[0].item_id, item_id)

    def test_off_banner_before_first_known_up_does_not_reset_home_pity(self):
        for item_id in (144, 155):
            with self.subTest(item_id=item_id):
                groups = [group(10162, [211001] * 20 + [item_id] + [211001] * 11)]
                home = build_category_stat(groups, is_up=StellaSoraApp._is_up_item)
                history = build_category_stat(groups)
                self.assertEqual(home.current_pity, 32)
                self.assertEqual(history.current_pity, 11)
                groups.append(group(10162, [162], timestamp=1792490460))
                self.assertEqual(build_category_stat(groups, is_up=StellaSoraApp._is_up_item).current_pity, 0)
                self.assertEqual(build_banner_stats_with_shared_pity(groups)[0].five_stars[0].pity, 12)

    def test_only_new_limited_traveler_grants_spark_not_anniversary(self):
        timestamp = int(datetime(2026, 10, 21, 12, tzinfo=CN_TIMEZONE).timestamp())
        groups = [group(gid, [211001] * 160, timestamp) for gid in (10162, 20162, 1001)]
        rewards = build_spark_rewards(groups, OFFICIAL_LIMITED_POOL_INFO)
        self.assertEqual(set(rewards), {10162})
        self.assertEqual(rewards[10162].item_id, 162)

    def test_anniversary_history_card_has_name_and_no_up_or_spark_badge(self):
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.gacha_rows_content = Mock()
        app.gacha_avatar_images = []
        app._square_avatar_photo = Mock()
        pool = build_banner_stats_with_shared_pity([group(1001, [144, 211001, 133])])[0]
        with patch("stellasora_toolkit.gui.tk.Frame"), patch("stellasora_toolkit.gui.tk.Label") as label, patch("stellasora_toolkit.gui.tk.Canvas") as canvas:
            app._add_five_star_banner_card(0, CATEGORY_ANNIVERSARY, pool)
        labels = [call.kwargs.get("text") for call in label.call_args_list]
        self.assertIn("星途一载·予缘重聚", labels)
        self.assertFalse({"UP", "歪", "井"}.intersection(labels))
        callback = canvas.return_value.bind.call_args.args[1]
        self.assertEqual(callback.__kwdefaults__["pity_limit"], 160)

    def test_anniversary_home_uses_average_and_plain_five_star_tiles(self):
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.root = Mock()
        app.avatar_images = []
        app._square_avatar_photo = Mock()
        app._pool_metric = Mock()
        pool = build_category_stat([group(1001, [144, 211001, 133])])
        with patch("stellasora_toolkit.gui.ttk.Frame"), patch("stellasora_toolkit.gui.tk.Frame") as frame, patch("stellasora_toolkit.gui.tk.Label") as label:
            frame.return_value.winfo_width.return_value = 500
            frame.return_value.winfo_children.return_value = []
            app._build_pool_section(pool, "#a0804e", "周年特选招募", Mock(), category=CATEGORY_ANNIVERSARY)
            app.root.after_idle.call_args.args[0]()
        self.assertIn("平均抽数", [call.args[2] for call in app._pool_metric.call_args_list])
        labels = [call.kwargs.get("text") for call in label.call_args_list]
        self.assertFalse({"UP", "歪", "井"}.intersection(labels))
