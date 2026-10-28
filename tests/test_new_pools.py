"""新卡池自动适配 + 数据格式不变的回归测试。

背景（用户报告）：
    - 新开的活动/自选卡池 Gid 不在老的 10xxx(旅人限时)/20xxx(秘纹限时) 区间里,
      旧逻辑判成 unknown, 记录会被归错类甚至丢分类;
    - 但导出的 <uid>.json 必须保持四类(1..4)格式, 不能冒出 "5"、"unknown" 之类的新键;
    - 卡池接口改成了 {"current": [...], "permanent": [...], ...}, 且新池子的
      bannerType 是「角色自选规则」这类特殊类型, 需要能识别并归到活动池;
    - 角色接口超时时, 要用卡池的 UP 名单兜底补名字。
"""
import contextlib
import json
import shutil
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import catalog_sync, official_banners, service  # noqa: E402
from stellasora_toolkit.catalog import (  # noqa: E402
    FIVE_STAR_DISCS, FIVE_STAR_TRAVELERS, TRAVELER_NAMES, is_five_star_item,
)
from stellasora_toolkit.exporter import normalize_category_keys  # noqa: E402
from stellasora_toolkit.gacha_stats import (  # noqa: E402
    classify_history_category, fallback_category_key, history_category_key,
)

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"

TRAVELER_PULL = {"Gid": 1002, "Time": 1791883135, "Ids": [162, 212009, 107]}
DISC_PULL = {"Gid": 1002, "Time": 1791883200, "Ids": [214066, 214067]}


@contextlib.contextmanager
def temp_workdir(name: str):
    directory = TEMP_ROOT / f"newpools_{name}"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class NewPoolClassificationTests(unittest.TestCase):
    """两条判据必须分开: 写文件用 classify_history_category, 界面用 display_category。"""

    def test_export_classifier_does_not_guess_for_unknown_gid(self):
        """活动池的 Gid 判不出来时必须返回 unknown —— 否则会改掉游戏给的分类。"""
        self.assertEqual(classify_history_category([TRAVELER_PULL]), "unknown")
        self.assertEqual(classify_history_category([DISC_PULL]), "unknown")
        self.assertIsNone(history_category_key([TRAVELER_PULL]))

    def test_display_classifier_groups_activity_pools_by_content(self):
        from stellasora_toolkit.gacha_stats import display_category
        self.assertEqual(display_category([TRAVELER_PULL]), "traveler_limited")
        self.assertEqual(display_category([DISC_PULL]), "disc_limited")
        mixed_disc_heavy = [{"Gid": 2005, "Time": 1, "Ids": [214066, 214067, 162]}]
        self.assertEqual(display_category(mixed_disc_heavy), "disc_limited")
        mixed_traveler_heavy = [{"Gid": 2005, "Time": 1, "Ids": [162, 137, 214066]}]
        self.assertEqual(display_category(mixed_traveler_heavy), "traveler_limited")

    def test_old_ranges_are_unchanged(self):
        self.assertEqual(classify_history_category([{"Gid": 10162, "Ids": [162]}]), "traveler_limited")
        self.assertEqual(classify_history_category([{"Gid": 20162, "Ids": [214066]}]), "disc_limited")
        self.assertEqual(classify_history_category([{"Gid": 1, "Ids": [137]}]), "traveler_standard")
        self.assertEqual(classify_history_category([{"Gid": 2, "Ids": [214001]}]), "disc_standard")

    def test_empty_group_still_unknown(self):
        self.assertEqual(classify_history_category([{"Gid": 9999, "Ids": []}]), "unknown")
        self.assertIsNone(history_category_key([{"Gid": 9999, "Ids": []}]))

    def test_fallback_key_is_always_in_range(self):
        for group in (TRAVELER_PULL, DISC_PULL, {"Gid": 7, "Ids": []}):
            self.assertIn(fallback_category_key([group]), (1, 2, 3, 4))


class ExportFormatTests(unittest.TestCase):
    """核心约束: 归档/分享文件保持游戏给的记录方式, categories 只能是 1..4。"""

    def test_activity_records_keep_their_original_category(self):
        """用户要求: uid.json 里活动池的记录方式不变 —— 原来在 3 就还是 3。"""
        for original in (1, 2, 3, 4):
            with self.subTest(category=original):
                normalized = normalize_category_keys({original: [dict(TRAVELER_PULL)]})
                self.assertEqual(list(normalized), [original])

    def test_only_out_of_range_keys_are_remapped(self):
        with self.assertRaises(ValueError):
            normalize_category_keys({7: [dict(DISC_PULL)]})

    def test_known_pool_records_are_still_repaired(self):
        """已知区间但被拍平到错分类的, 仍然按 Gid 纠正(历史修复逻辑不变)。"""
        normalized = normalize_category_keys({4: [{"Gid": 20162, "Time": 1, "Ids": [214066]}]})
        self.assertEqual(list(normalized), [3])

    def test_share_file_keeps_the_original_shape(self):
        with temp_workdir("format") as directory:
            categories = normalize_category_keys({1: [dict(TRAVELER_PULL)]})
            path = service.write_share_file(directory, categories, "100872990")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(list(payload), ["version", "uid", "updatedAt", "categories"])
        self.assertEqual(payload["version"], 1)
        self.assertEqual(sorted(payload["categories"]), ["1"])
        self.assertEqual(payload["categories"]["1"][0]["Gid"], 1002)


class BannerSchemaTests(unittest.TestCase):
    """卡池接口已经变成 {"current": [...], "permanent": [...], "upcoming", "ended"}。"""

    SAMPLE = {
        "current": [
            {"id": 1002, "name": "异途一世·自选", "bannerType": "角色自选规则",
             "startTime": "2026-10-20T12:00:00+08:00", "endTime": "2026-11-10T10:59:59+08:00",
             "rateUp": {"fiveStar": None, "fourStar": None}},
            {"id": 10162, "name": "星沙源流", "bannerType": "角色限时规则",
             "startTime": "2026-10-20T12:00:00+08:00", "endTime": "2026-11-10T10:59:59+08:00",
             "rateUp": {"fiveStar": {"entries": [{"id": 162, "name": "尘沙（源初）"}]},
                        "fourStar": {"entries": [{"id": 107, "name": "琥珀"}]}}},
        ],
        "permanent": [
            {"id": 1, "name": "常驻旅人", "bannerType": "角色常驻规则",
             "startTime": "2025-01-01T00:00:00+08:00", "endTime": ""},
        ],
        "upcoming": [],
        "ended": [],
    }

    def setUp(self):
        self._saved_urlopen = official_banners.urlopen

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        official_banners.urlopen = lambda *_a, **_k: _Response(self.SAMPLE)
        # 与 refresh_from_network 一致: 拉完就生效(它内部会 set_active_banners)
        official_banners.set_active_banners(official_banners.fetch_banners())

    def tearDown(self):
        official_banners.urlopen = self._saved_urlopen
        official_banners.set_active_banners({}, {})

    def test_permanent_pools_are_parsed_too(self):
        banners = official_banners.fetch_banners()
        self.assertIn(1, banners, "常驻池也要读（名字/时间对界面有用）")
        self.assertEqual(banners[1][3], "", "常驻池不该有 UP 名")
        self.assertIn(10162, banners)
        self.assertEqual(banners[10162][3], "尘沙（源初）")

    def test_activity_pools_are_flagged(self):
        official_banners.fetch_banners()
        self.assertTrue(official_banners.is_activity_pool(1002))     # 自选规则
        self.assertFalse(official_banners.is_activity_pool(10162))   # 普通限时
        self.assertFalse(official_banners.is_activity_pool(1))       # 常驻
        self.assertTrue(official_banners.is_activity_pool(4242))     # 区间外 → 当活动池

    def test_display_name_marks_activity_pools(self):
        official_banners.fetch_banners()
        self.assertIn("活动", official_banners.pool_display_name(1002))
        self.assertEqual(official_banners.pool_display_name(10162), "星沙源流")
        self.assertIn("4242", official_banners.pool_display_name(4242))

    def test_rate_up_entries_feed_the_name_fallback(self):
        official_banners.fetch_banners()
        entries = official_banners.rate_up_entries()
        ids = {entry["id"] for entry in entries}
        self.assertEqual(ids, {162, 107})

        messages = []
        augmented = catalog_sync._augment_with_banner_names(
            [{"id": 214066, "kind": "disc", "name": "指引前路的启明星",
              "icon": "", "rarity": 5, "five_star": True}], messages.append)
        by_id = {item["id"]: item for item in augmented}
        self.assertEqual(by_id[162]["name"], "尘沙（源初）")
        self.assertTrue(by_id[162]["five_star"])
        self.assertFalse(by_id[107]["five_star"])
        self.assertIn(214066, by_id)                       # 原有的秘纹条目不能丢
        self.assertTrue(messages)

    def test_fallback_is_skipped_when_characters_already_ok(self):
        official_banners.fetch_banners()
        fetched = [{"id": 162, "kind": "traveler", "name": "尘沙（源初）",
                    "icon": "", "rarity": 5, "five_star": True}]
        self.assertEqual(catalog_sync._augment_with_banner_names(fetched), fetched)


class RefreshCadenceTests(unittest.TestCase):
    def test_missing_state_means_stale(self):
        with temp_workdir("cadence") as directory:
            self.assertIsNone(catalog_sync.last_success_age_hours(directory / "state.json"))

    def test_age_is_reported_from_state_file(self):
        with temp_workdir("cadence2") as directory:
            state = directory / "state.json"
            state.write_text(json.dumps({
                "seen": [], "last_success": "2026-10-22T00:00:00+00:00"}), encoding="utf-8")
            age = catalog_sync.last_success_age_hours(state)
        self.assertIsNotNone(age)
        self.assertGreater(age, 0)

    def test_success_is_recorded_and_survives_failure(self):
        with temp_workdir("cadence3") as directory:
            state = directory / "state.json"
            catalog_sync._save_seen(state, {1, 2}, success=True)
            first = json.loads(state.read_text(encoding="utf-8"))
            catalog_sync._save_seen(state, {1, 2, 3}, success=False)
            second = json.loads(state.read_text(encoding="utf-8"))
        self.assertIn("last_success", first)
        self.assertEqual(second["last_success"], first["last_success"], "失败的那次不能清掉成功时间")
        self.assertEqual(second["seen"], [1, 2, 3])


class IconBackfillTests(unittest.TestCase):
    """接口超时拿不到 icon 字段时, 按资源命名规律补图。"""

    def test_fallback_paths_match_the_observed_layout(self):
        # 实测: 103 → head_10301_XL.png; 214066 → outfit_4066_b.png
        self.assertEqual(catalog_sync._icon_fallback_path("traveler", 103),
                         "/stella/assets/head_10301_XL.png")
        self.assertEqual(catalog_sync._icon_fallback_path("disc", 214066),
                         "/stella/assets/outfit_4066_b.png")
        self.assertEqual(catalog_sync._icon_fallback_path("disc", 214001),
                         "/stella/assets/outfit_4001_b.png")
        self.assertEqual(catalog_sync._icon_fallback_path("other", 1), "")

    def test_missing_targets_only_lists_absent_files(self):
        with temp_workdir("icons") as directory:
            assets = directory / "assets"
            (assets / "travelers").mkdir(parents=True)
            (assets / "travelers" / "162.png").write_bytes(b"x")
            with mock.patch.object(catalog_sync, "asset_root", return_value=assets):
                targets = catalog_sync.missing_icon_targets()
        ids = {target["id"] for target in targets}
        self.assertNotIn(162, ids, "已经存在的头像不该再补")
        self.assertIn(214066, ids)

    def test_second_pass_downloads_backfilled_icons(self):
        with temp_workdir("icons2") as directory:
            assets = directory / "assets"
            state = directory / "state.json"
            targets = [{"id": 214066, "kind": "disc",
                        "icon": "/stella/assets/outfit_4066_b.png"}]
            with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", return_value=[]), \
                    mock.patch.object(catalog_sync, "_augment_with_banner_names",
                                      side_effect=lambda items, _progress=None: items), \
                    mock.patch.object(catalog_sync, "missing_icon_targets", return_value=targets), \
                    mock.patch.object(catalog_sync, "asset_root", return_value=assets), \
                    mock.patch.object(catalog_sync, "_download_icon", return_value=True):
                report = catalog_sync.sync_with_report(state)
        self.assertEqual({item["id"] for item in report["downloaded"]}, {214066})


class ActivityPoolViewTests(unittest.TestCase):
    """界面要能把活动池单独筛出来(数据仍归 1..4)。"""

    RECORDS = [
        {"Gid": 1002, "Time": 1791883135, "Ids": [162, 214066]},
        {"Gid": 1002, "Time": 1791883200, "Ids": [107]},
        {"Gid": 10162, "Time": 1791883300, "Ids": [162, 137]},
        {"Gid": 1, "Time": 1791883400, "Ids": [137]},
    ]

    def setUp(self):
        official_banners.set_active_banners(
            {1002: ("异途一世·自选", "2026-10-20", "2026-11-10", ""),
             10162: ("星沙源流", "2026-10-20", "2026-11-10", "尘沙（源初）")},
            {1002: "角色自选规则", 10162: "角色限时规则"})

    def tearDown(self):
        official_banners.set_active_banners({}, {})

    def test_activity_pools_groups_by_gid_with_counts(self):
        from stellasora_toolkit.presentation import activity_pools
        rows = activity_pools(self.RECORDS)
        self.assertEqual(len(rows), 1, "只有 1002 是活动池")
        row = rows[0]
        self.assertEqual(row["gid"], 1002)
        self.assertEqual(row["pulls"], 3)
        self.assertEqual(row["five_stars"], 2)          # 162 + 214066
        self.assertEqual(row["name"], "异途一世·自选（活动）")

    def test_ordinary_pools_are_not_listed(self):
        from stellasora_toolkit.presentation import activity_pools
        rows = activity_pools([{"Gid": 10162, "Time": 1, "Ids": [162]}])
        self.assertEqual(rows, [])

    def test_records_keep_the_category_the_game_gave_them(self):
        """界面单独筛活动池, 但归档里的分类原样不动(同一类里可以混活动池)。"""
        normalized = normalize_category_keys({1: [dict(TRAVELER_PULL), dict(DISC_PULL)]})
        self.assertEqual(list(normalized), [1])
        self.assertEqual(len(normalized[1]), 2)

    def test_display_grouping_shows_activity_pools_under_limited(self):
        from stellasora_toolkit.gacha_stats import display_category
        from stellasora_toolkit.presentation import categories
        grouped = categories([dict(TRAVELER_PULL), dict(DISC_PULL)])
        shown = sorted(key for key, value in grouped.items() if value)
        self.assertTrue(shown, "活动池不能从界面消失")
        self.assertEqual(display_category([DISC_PULL]), "disc_limited")


class StaticPoolNameTests(unittest.TestCase):
    """卡池名不能依赖网络: 内置静态表要覆盖到最新卡池。"""

    def test_recent_pools_have_bundled_names(self):
        from stellasora_toolkit.official_banners import official_pool_info
        for gid in (10137, 10139, 10162, 11110):
            info = official_pool_info(gid)
            self.assertIsNotNone(info, f"{gid} 缺少内置名称")
            self.assertTrue(info[0], f"{gid} 名称为空")
            self.assertNotIn("卡池", info[0])

    def test_pool_table_is_large_enough(self):
        from stellasora_toolkit.constants import OFFICIAL_LIMITED_POOL_INFO
        self.assertGreaterEqual(len(OFFICIAL_LIMITED_POOL_INFO), 70, "内置卡池表应覆盖全部历史卡池")

    def test_small_gid_pools_are_not_activity(self):
        from stellasora_toolkit.official_banners import is_activity_pool
        self.assertFalse(is_activity_pool(1))
        self.assertFalse(is_activity_pool(2))
        self.assertFalse(is_activity_pool(5), "小序号池(初心旅人)不该被当成活动池")
        self.assertTrue(is_activity_pool(1002))

    def test_anniversary_pool_is_an_activity_pool(self):
        """周年特选算活动卡池: 界面不再单独占一类。"""
        from stellasora_toolkit.official_banners import is_activity_pool
        from stellasora_toolkit.gacha_stats import display_category
        from stellasora_toolkit.presentation import activity_pools
        self.assertTrue(is_activity_pool(1001))
        rows = activity_pools([{"Gid": 1001, "Time": 1, "Ids": [162]}])
        self.assertEqual([row["gid"] for row in rows], [1001])
        # #21: 周年特选保持自己的分类, 不再按掉落内容并进「秘纹限时」。
        self.assertEqual(display_category([{"Gid": 1001, "Ids": [162]}]), "anniversary_selected")

    def test_anniversary_pool_does_not_dilute_limited_statistics(self):
        """#21: 秘纹限时的抽数/五星只算分类 3, 活动池单列。"""
        from stellasora_toolkit.presentation import activity_pools, categories, overview
        disc_pulls = [{"Gid": 21115, "Time": 1793082943 + index, "Ids": [212001] * 10} for index in range(3)]
        activity_pulls = [{"Gid": 1001, "Time": 1792491368 + index, "Ids": [211004, 212005, 103] * 3 + [162]}
                          for index in range(9)]

        grouped = categories(activity_pulls + disc_pulls)
        self.assertEqual(len(grouped['disc_limited']), 3)
        self.assertEqual(len(grouped['anniversary_selected']), 9)
        self.assertEqual(grouped['traveler_limited'], [])

        stats = overview(activity_pulls + disc_pulls)
        self.assertEqual(len(stats.category_stats), 4, '周年特选不能变成第五张卡')
        self.assertNotIn('anniversary_selected', stats.category_stats)
        self.assertEqual(stats.category_stats['disc_limited'].total_pulls, 30)
        self.assertEqual(sum(card.total_pulls for card in stats.category_stats.values() if card), 30,
                         '活动池的抽数不能再算进四张常规卡')
        rows = activity_pools(activity_pulls + disc_pulls)
        self.assertEqual([row['gid'] for row in rows], [1001])
        self.assertEqual(rows[0]['pulls'], 90)
        self.assertEqual(stats.total_pulls, 120, '累计招募仍然含活动池')


class BundledCatalogTests(unittest.TestCase):
    def test_new_traveler_and_discs_are_bundled(self):
        self.assertIn(162, TRAVELER_NAMES)
        self.assertIn(162, FIVE_STAR_TRAVELERS)
        self.assertTrue(is_five_star_item(162))
        self.assertIn(214066, FIVE_STAR_DISCS)
        self.assertIn(214067, FIVE_STAR_DISCS)
        self.assertGreaterEqual(len(FIVE_STAR_DISCS), 61, "内置五星秘纹不应少于 61 条")


if __name__ == "__main__":
    unittest.main()
