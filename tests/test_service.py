import tempfile
import json
import unittest
from pathlib import Path

from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.service import LEGACY_ARCHIVE_FILENAME, _load_archive, _write_archive, archive_path_for_uid, load_latest_snapshot


class ServiceTests(unittest.TestCase):
    def test_anniversary_archive_round_trip_preserves_raw_category_and_gid(self):
        groups = [{"Gid": 1001, "Time": 1792487790, "Ids": [211005, 112], "NextPackage": ""}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_archive(root, "123456789", {6: groups})
            payload = json.loads((root / "123456789.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(set(payload["categories"]), {"1", "2", "3", "4", "6"})
            self.assertEqual(payload["categories"]["6"], groups)
            self.assertEqual(_load_archive(root, "123456789")[6], groups)
            snapshot = load_latest_snapshot(root)
            self.assertEqual(snapshot.gacha_categories[6], groups)
            self.assertEqual(snapshot.pull_count, 2)

    def test_old_archive_does_not_gain_an_anniversary_category(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_archive(root, "123456789", {1: []})
            payload = json.loads((root / "123456789.json").read_text(encoding="utf-8"))
            self.assertEqual(set(payload["categories"]), {"1", "2", "3", "4"})

    def test_explicit_empty_anniversary_category_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_archive(root, "123456789", {6: []})
            self.assertEqual(_load_archive(root, "123456789")[6], [])

    def test_write_rejects_unsupported_categories_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "123456789.json"
            _write_archive(root, "123456789", {1: []})
            before = archive.read_bytes()
            for categories in ({5: []}, {7: []}, {True: []}, {6.0: []}, {"6": []}, {6: {}}, []):
                with self.subTest(categories=categories), self.assertRaises(ValueError):
                    _write_archive(root, "123456789", categories)
                self.assertEqual(archive.read_bytes(), before)
                self.assertFalse((root / ".123456789.json.tmp").exists())

    def test_load_rejects_unknown_category_five_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "123456789.json"
            archive.write_text(json.dumps({"uid": "123456789", "categories": {"5": []}}))
            before = archive.read_bytes()
            with self.assertRaises(ValueError):
                _load_archive(root, "123456789")
            self.assertEqual(archive.read_bytes(), before)

    def test_uid_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_archive(root, "123456789", {1: [{"Gid": 10, "Time": 100, "Ids": [1]}]})
            path = archive_path_for_uid(root, "123456789")
            self.assertTrue(path.is_file())
            snapshot = load_latest_snapshot(root)
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.uid, "123456789")
            self.assertEqual(snapshot.gacha[0]["Gid"], 10)

    def test_second_account_never_inherits_legacy_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / LEGACY_ARCHIVE_FILENAME).write_text(json.dumps({"uid": "123456789", "categories": {"1": [{"Gid": 10, "Time": 1, "Ids": [1]}]}}))
            first = _load_archive(root, "123456789")
            self.assertEqual(len(first[1]), 1)
            _write_archive(root, "123456789", first)
            self.assertEqual(_load_archive(root, "987654321"), {})
            self.assertTrue((root / LEGACY_ARCHIVE_FILENAME).exists())

    def test_unowned_legacy_history_is_not_assigned_to_current_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / LEGACY_ARCHIVE_FILENAME
            legacy.write_text(json.dumps({"categories": {"1": [{"Gid": 10, "Time": 1, "Ids": [1]}]}}))
            original = legacy.read_bytes()
            with self.assertRaises(AccountSafetyError):
                _load_archive(root, "123456789")
            self.assertEqual(legacy.read_bytes(), original)
            self.assertFalse((root / "123456789.json").exists())

    def test_corrupt_archive_is_not_overwritten_or_replaced_with_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "123456789.json"
            archive.write_text("broken")
            with self.assertRaises(ValueError):
                _load_archive(root, "123456789")
            self.assertEqual(archive.read_text(), "broken")

    def test_filename_and_internal_uid_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "123456789.json").write_text(json.dumps({"uid": "987654321", "categories": {"1": []}}))
            with self.assertRaises(ValueError):
                _load_archive(root, "123456789")
            self.assertIsNone(load_latest_snapshot(root))

    def test_legacy_only_archive_is_still_displayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / LEGACY_ARCHIVE_FILENAME).write_text(json.dumps({"categories": {"1": []}}))
            self.assertIsNotNone(load_latest_snapshot(root))
            self.assertIsNone(load_latest_snapshot(root).uid)

    def test_uid_path_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            archive_path_for_uid(Path("exports"), "../other")


if __name__ == "__main__":
    unittest.main()
