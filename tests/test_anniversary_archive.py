import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import service
from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.exporter import sanitize_gacha_categories


def batch(timestamp, ids, gid=1001):
    return {"Gid": gid, "Time": timestamp, "Ids": ids}


class AnniversaryArchiveTests(unittest.TestCase):
    def test_sanitizer_keeps_raw_anniversary_category_and_pool_id(self):
        raw = {6: {1: batch(1792487790, [211005, 112])}}
        before = copy.deepcopy(raw)
        self.assertEqual(sanitize_gacha_categories(raw), {6: [batch(1792487790, [211005, 112])]})
        self.assertEqual(raw, before)

    def test_merge_keeps_anniversary_separate_and_deduplicates_without_mutation(self):
        old = {1: [batch(100, [162], 10162)], 6: [batch(110, [114])]}
        current = {6: [batch(110, [114]), batch(120, [155])]}
        original = copy.deepcopy((old, current))
        merged = service.merge_gacha_categories(old, current)
        self.assertEqual(merged, {1: old[1], 6: [batch(110, [114]), batch(120, [155])]})
        self.assertEqual((old, current), original)

    def mocked_read(self, root, raw):
        with ExitStack() as stack:
            stack.enter_context(patch.object(service, "find_process_id", return_value=20))
            process = stack.enter_context(patch.object(service, "RemoteProcess")).return_value.__enter__.return_value
            process.get_creation_time.return_value = 1000
            uid = stack.enter_context(patch.object(service, "read_game_uid_from_process", return_value="100000001"))
            discovery = stack.enter_context(patch.object(service, "LuaTableDiscovery")).return_value
            discovery.read_target_field.return_value = raw
            return service.extract_snapshot(root, process_id=20), uid

    def test_extract_saves_new_raw_category_without_changing_existing_records(self):
        old = {1: [batch(100, [162], 10162)]}
        new = {6: [batch(1792487790, [211005, 112])]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service._write_archive(root, "100000001", old)
            with patch.object(service, "export_all", return_value=[]) as export:
                snapshot, uid = self.mocked_read(root, new)
            self.assertEqual(uid.call_count, 2)
            self.assertEqual(snapshot.pull_count, 3)
            payload = json.loads((root / "100000001.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["categories"]["1"], old[1])
            self.assertEqual(payload["categories"]["6"], new[6])
            self.assertEqual(export.call_args.args[3][6], new[6])

    def test_unknown_raw_category_stops_extraction_before_export_or_archive_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "100000001.json"
            service._write_archive(root, "100000001", {1: [batch(100, [162], 10162)]})
            original = archive.read_bytes()
            with patch.object(service, "export_all") as export:
                with self.assertRaises(AccountSafetyError):
                    self.mocked_read(root, {5: [batch(1792487790, [114])]})
                export.assert_not_called()
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(list(root.glob("stellasora_gacha_*.json")), [])


if __name__ == "__main__":
    unittest.main()
