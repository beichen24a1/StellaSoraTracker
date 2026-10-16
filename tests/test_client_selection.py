import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stellasora_toolkit import gui, service
from stellasora_toolkit.cli import build_parser
from stellasora_toolkit.process import GameProcess


class ClientSelectionTests(unittest.TestCase):
    def setUp(self):
        self.app = gui.StellaSoraApp.__new__(gui.StellaSoraApp)
        for name in ("root", "status_var", "refresh_button", "upload_button", "update_button", "progress"):
            setattr(self.app, name, Mock())
        self.app.busy = self.app.uploading = self.app.update_checking = False
        self.app.output_dir = Path("exports")
        self.app.events = queue.Queue()
        self.clients = [GameProcess("StellaSora.exe", 20), GameProcess("xtlr.exe", 30)]

    def test_single_client_reads_exact_selected_pid(self):
        with patch.object(gui, "find_game_processes", return_value=self.clients[:1]), patch.object(gui, "GameProcessDialog") as dialog, patch.object(gui.threading, "Thread") as thread, patch.object(gui, "extract_snapshot") as extract:
            self.app.refresh()
            thread.call_args.kwargs["target"]()
        dialog.assert_not_called()
        self.assertTrue(self.app.busy)
        self.assertEqual(extract.call_args.kwargs["process_id"], 20)
        self.assertEqual(extract.call_args.kwargs["process_name"], "StellaSora.exe")
        self.assertEqual(self.app.events.get_nowait()[0], "complete")

    def test_multiple_clients_use_dialog_selection(self):
        with patch.object(gui, "find_game_processes", return_value=self.clients), patch.object(gui, "GameProcessDialog") as dialog, patch.object(gui.threading, "Thread") as thread, patch.object(gui, "extract_snapshot") as extract:
            dialog.return_value.result = self.clients[1]
            self.app.refresh()
            thread.call_args.kwargs["target"]()
        dialog.assert_called_once_with(self.app.root, self.clients)
        self.assertEqual(extract.call_args.kwargs["process_id"], 30)

    def test_cancel_leaves_buttons_and_archive_untouched(self):
        with patch.object(gui, "find_game_processes", return_value=self.clients), patch.object(gui, "GameProcessDialog") as dialog, patch.object(gui.threading, "Thread") as thread:
            dialog.return_value.result = None
            self.app.refresh()
        self.assertFalse(self.app.busy)
        thread.assert_not_called()
        self.app.refresh_button.state.assert_not_called()
        self.app.progress.start.assert_not_called()

    def test_no_client_reports_error_without_starting_reader(self):
        with patch.object(gui, "find_game_processes", return_value=[]), patch.object(gui.messagebox, "showerror") as error, patch.object(gui.threading, "Thread") as thread:
            self.app.refresh()
        self.assertFalse(self.app.busy)
        error.assert_called_once()
        thread.assert_not_called()

    def test_reader_failure_is_sent_to_existing_ui_cleanup(self):
        with patch.object(gui, "find_game_processes", return_value=self.clients[:1]), patch.object(gui.threading, "Thread") as thread, patch.object(gui, "extract_snapshot", side_effect=ProcessLookupError("exited")):
            self.app.refresh()
            thread.call_args.kwargs["target"]()
        self.assertEqual(self.app.events.get_nowait()[0], "error")

    def test_cli_auto_default_and_explicit_pid(self):
        self.assertIsNone(build_parser().parse_args([]).process)
        args = build_parser().parse_args(["--process", "StellaSora.exe", "--pid", "20"])
        self.assertEqual((args.process, args.pid), ("StellaSora.exe", 20))


class SelectedProcessServiceTests(unittest.TestCase):
    def test_revalidates_selection_before_reading_or_writing(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "find_process_id", side_effect=ProcessLookupError("exited")) as find, patch.object(service, "RemoteProcess") as process:
            root = Path(directory)
            with self.assertRaises(ProcessLookupError):
                service.extract_snapshot(root, "StellaSora.exe", process_id=20)
            find.assert_called_once_with("StellaSora.exe", pid=20)
            process.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_failed_uid_read_never_reuses_previous_archive(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "find_process_id", return_value=20), patch.object(service, "RemoteProcess"), patch.object(service, "read_game_uid_from_process", side_effect=LookupError("missing UID")):
            root = Path(directory)
            service._write_archive(root, "100000001", {1: []})
            before = (root / "100000001.json").read_bytes()
            with self.assertRaises(LookupError):
                service.extract_snapshot(root, process_id=20)
            self.assertEqual((root / "100000001.json").read_bytes(), before)
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_different_prefix_uids_remain_separate_without_region_fields(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "find_process_id", return_value=20), patch.object(service, "RemoteProcess") as process, patch.object(service, "LuaTableDiscovery") as discovery, patch.object(service, "read_game_uid_from_process") as read_uid:
            root = Path(directory)
            for uid in ("100000001", "300000001", "900000001"):
                process.return_value.__enter__.return_value.get_creation_time.return_value = int(uid)
                read_uid.return_value = uid
                discovery.return_value.read_target_field.return_value = {}
                snapshot = service.extract_snapshot(root, "StellaSora.exe", process_id=20)
                self.assertEqual(snapshot.uid, uid)
                self.assertTrue((root / f"{uid}.json").is_file())
            self.assertEqual(len(list(root.glob("[139]00000001.json"))), 3)
