"""性能规则: 抽卡记录里的序号都已经认识(有名字)时, 不再联网查询资源。

用户要求: "如果当前读取全部角色都有对应当前有的名字等内容可以不做后面的资源查询等"。
锁四件事:
    1. 序号全认识 + 有缓存 → 不联网;
    2. 序号全认识 + 没缓存 → 也不联网(直接用程序内置名称表);
    3. 有认不出的序号 → 必须联网;
    4. 启动同步(没有 ids): 缓存新鲜就用缓存, 过期才联网。
"""
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import catalog_sync  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


class SyncSkipTests(unittest.TestCase):
    def setUp(self):
        self.work = (TEMP_ROOT / "sync_skip").resolve()
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.state = self.work / "state.json"
        # 已知序号: 162 是内置五星旅人, 214066 是内置五星秘纹
        self.known_ids = [162, 214066]

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _sync(self, ids):
        calls = []

        def fake_fetch(progress=None):
            calls.append(True)
            return [{"id": 162, "kind": "traveler", "name": "尘沙（源初）",
                     "icon": "", "rarity": 5, "five_star": True}]

        with mock.patch.object(catalog_sync, "_fetch_five_star_catalog", side_effect=fake_fetch), \
                mock.patch.object(catalog_sync, "missing_icon_targets", return_value=[]), \
                mock.patch.object(catalog_sync, "_augment_with_banner_names",
                                  side_effect=lambda items, _p=None: items):
            report = catalog_sync.sync_with_report(self.state, record_ids=ids)
        return report, calls

    def test_known_ids_skip_network_even_without_cache(self):
        report, calls = self._sync(self.known_ids)
        self.assertEqual(calls, [], "序号全认识时不该联网")
        self.assertTrue(report["skipped_online"])
        self.assertEqual(report["registered"], [])

    def test_known_ids_skip_network_with_cache_present(self):
        cache = catalog_sync._catalog_cache_path(self.state)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"items": [{"id": 999, "kind": "traveler", "name": "旧条目",
                                                "icon": "", "rarity": 5, "five_star": True}]}),
                         encoding="utf-8")
        report, calls = self._sync(self.known_ids)
        self.assertEqual(calls, [])
        self.assertTrue(report["skipped_online"])

    def test_unknown_id_forces_network(self):
        report, calls = self._sync([162, 999999])
        self.assertEqual(len(calls), 1, "有认不出的序号时必须联网")
        self.assertFalse(report["skipped_online"])

    def test_startup_sync_uses_fresh_cache(self):
        cache = catalog_sync._catalog_cache_path(self.state)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"items": [{"id": 162, "kind": "traveler", "name": "尘沙（源初）",
                                                "icon": "", "rarity": 5, "five_star": True}]}),
                         encoding="utf-8")
        report, calls = self._sync([])
        self.assertEqual(calls, [], "启动同步遇到新鲜缓存不该联网")
        self.assertTrue(report["skipped_online"])

    def test_startup_sync_refetches_when_cache_is_old(self):
        cache = catalog_sync._catalog_cache_path(self.state)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"items": []}), encoding="utf-8")
        old = 1000 * 3600
        import os
        stamp = cache.stat().st_mtime - old
        os.utime(cache, (stamp, stamp))
        report, calls = self._sync([])
        self.assertEqual(len(calls), 1, "缓存超过 12 小时应重新拉取")
        self.assertFalse(report["skipped_online"])


if __name__ == "__main__":
    unittest.main()
