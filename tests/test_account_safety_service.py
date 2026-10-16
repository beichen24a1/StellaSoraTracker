import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import service
from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.uid import AmbiguousUidError
from stellasora_toolkit.upload import UploadError, upload_archive


def history(offset=0):
    return {1: [{"Gid": 10, "Time": 100 + offset + i, "Ids": [11, 22]} for i in range(4)]}


class AccountSafetyServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.find = self.mock("find_process_id", return_value=20)
        self.process = self.mock("RemoteProcess").return_value.__enter__.return_value
        self.process.get_creation_time.return_value = 1000
        self.uid = self.mock("read_game_uid_from_process", return_value="100000001")
        self.discovery = self.mock("LuaTableDiscovery").return_value
        self.discovery.read_target_field.return_value = history()
        self.export = self.mock("export_all", return_value=[])

    def mock(self, name, **kwargs):
        patcher = patch.object(service, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def read(self):
        return service.extract_snapshot(self.root, process_id=20)

    def test_normal_read_checks_uid_twice_and_preserves_archive_schema(self):
        snapshot = self.read()
        self.assertEqual(self.uid.call_count, 2)
        self.assertEqual(snapshot.pull_count, 8)
        payload = json.loads((self.root / "100000001.json").read_text())
        self.assertEqual(set(payload), {"version", "uid", "updatedAt", "categories"})
        self.assertEqual(payload["categories"]["1"], history()[1])
        self.read()
        self.assertEqual(json.loads((self.root / "100000001.json").read_text())["categories"], payload["categories"])

    def test_account_switch_blocks_before_discovery_and_retains_original(self):
        self.read()
        before = (self.root / "100000001.json").read_bytes()
        self.export.reset_mock()
        self.discovery.reset_mock()
        self.uid.return_value = "100000002"
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()
        self.discovery.read_target_field.assert_not_called()
        self.assertEqual((self.root / "100000001.json").read_bytes(), before)
        self.assertFalse((self.root / "100000002.json").exists())
        self.uid.return_value = "100000001"
        with self.assertRaises(AccountSafetyError):
            self.read()

    def test_restarted_game_can_read_another_account(self):
        self.read()
        self.process.get_creation_time.return_value = 2000
        self.uid.return_value = "100000002"
        self.discovery.read_target_field.return_value = history(100)
        self.assertEqual(self.read().uid, "100000002")
        self.assertTrue((self.root / "100000001.json").exists())
        self.assertTrue((self.root / "100000002.json").exists())

    def test_uid_change_during_scan_writes_no_records_and_taints_session(self):
        self.uid.side_effect = ["100000001", "100000002"]
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()
        self.assertEqual(list(self.root.glob("*.json")), [])
        self.uid.side_effect = None
        with self.assertRaises(AccountSafetyError):
            self.read()

    def test_ambiguous_first_uid_taints_session_even_when_it_later_disappears(self):
        self.uid.side_effect = AmbiguousUidError("multiple UIDs")
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.uid.side_effect = None
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()

    def test_missing_uid_after_scan_blocks_save_and_future_reads(self):
        self.uid.side_effect = ["100000001", LookupError("missing UID")]
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.uid.side_effect = None
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()

    def test_reused_pid_during_scan_never_saves(self):
        self.process.get_creation_time.side_effect = [1000, 2000]
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()

    def test_failed_discovery_still_remembers_first_account(self):
        self.discovery.read_target_field.side_effect = LookupError("no loaded history")
        with self.assertRaises(LookupError):
            self.read()
        self.discovery.read_target_field.side_effect = None
        self.uid.return_value = "100000002"
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()

    def test_stale_history_matching_another_uid_is_never_exported(self):
        service._write_archive(self.root, "100000002", history())
        before = (self.root / "100000002.json").read_bytes()
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()
        self.assertFalse((self.root / "100000001.json").exists())
        self.assertEqual((self.root / "100000002.json").read_bytes(), before)

    def test_existing_polluted_archive_is_blocked_even_when_new_read_is_clean(self):
        for uid in ("100000001", "100000002"):
            service._write_archive(self.root, uid, history())
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        self.discovery.read_target_field.return_value = history(100)
        with self.assertRaises(AccountSafetyError):
            self.read()
        self.export.assert_not_called()
        self.assertEqual({p.name: p.read_bytes() for p in self.root.glob("*.json")}, before)

    def test_upload_of_existing_mixed_archives_is_blocked_before_network(self):
        for uid in ("100000001", "100000002"):
            service._write_archive(self.root, uid, history())
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        with patch("stellasora_toolkit.upload.urlopen") as network:
            with self.assertRaises(UploadError):
                upload_archive(self.root / "100000001.json", "100000001")
            network.assert_not_called()
        self.assertEqual({p.name: p.read_bytes() for p in self.root.glob("*.json")}, before)
