import ctypes
import unittest
from unittest.mock import Mock, patch

from stellasora_toolkit import process


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.running = patch.object(process, "running_processes").start()
        self.path = patch.object(process, "_process_image_path", return_value="C:/Games/client.exe").start()
        self.addCleanup(patch.stopall)

    def test_detects_both_names_case_insensitively_and_ignores_other_programs(self):
        self.running.return_value = [("XTlR.EXE", 30), ("stellasora.EXE", 20), ("launcher.exe", 10)]
        self.assertEqual([p.pid for p in process.find_game_processes()], [20, 30])
        self.assertEqual(self.path.call_count, 2)

    def test_single_client_auto_selects_without_region(self):
        for name in process.GAME_EXECUTABLES:
            with self.subTest(name=name):
                self.running.return_value = [(name, 20)]
                self.assertEqual(process.find_process_id(), 20)

    def test_multiple_instances_never_silently_choose_first(self):
        for names in (("xtlr.exe", "StellaSora.exe"), ("StellaSora.exe", "StellaSora.exe")):
            self.running.return_value = [(names[0], 10), (names[1], 20)]
            with self.subTest(names=names), self.assertRaisesRegex(ProcessLookupError, "--pid"):
                process.find_process_id()
            self.assertEqual(process.find_process_id(pid=20), 20)

    def test_selected_pid_must_still_match_selected_executable(self):
        self.running.return_value = [("StellaSora.exe", 20), ("notepad.exe", 10)]
        for name, pid in ((None, 10), ("xtlr.exe", 20), (None, 999)):
            with self.subTest(name=name, pid=pid), self.assertRaises(ProcessLookupError):
                process.find_process_id(name, pid=pid)

    def test_explicit_executable_remains_supported(self):
        self.running.return_value = [("custom.exe", 30), ("xtlr.exe", 40)]
        self.assertEqual(process.find_process_id("custom.exe"), 30)
        self.assertEqual(process.find_process_id(["custom.exe"], pid=30), 30)

    def test_no_game_lists_both_supported_names(self):
        self.running.return_value = []
        with self.assertRaises(ProcessLookupError) as error:
            process.find_process_id()
        for name in process.GAME_EXECUTABLES:
            self.assertIn(name, str(error.exception))

    def test_invalid_selection_is_rejected(self):
        for pid in (-1, 0, True, "20"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                process.find_process_id(pid=pid)
        for name in ("", [], [""]):
            with self.subTest(name=name), self.assertRaises(ValueError):
                process.find_process_id(name)


class ProcessEnumerationTests(unittest.TestCase):
    def test_snapshot_is_closed_and_all_entries_are_returned(self):
        api = Mock()
        api.CreateToolhelp32Snapshot.return_value = 99

        def first(_snapshot, pointer):
            pointer._obj.szExeFile = "xtlr.exe"
            pointer._obj.th32ProcessID = 10
            return True

        def second(_snapshot, pointer):
            pointer._obj.szExeFile = "StellaSora.exe"
            pointer._obj.th32ProcessID = 20
            api.Process32NextW.side_effect = None
            api.Process32NextW.return_value = False
            return True

        api.Process32FirstW.side_effect = first
        api.Process32NextW.side_effect = second
        with patch.object(process, "kernel32", api), patch.object(ctypes, "get_last_error", return_value=18):
            self.assertEqual(process.running_processes(), [("xtlr.exe", 10), ("StellaSora.exe", 20)])
        api.CloseHandle.assert_called_once_with(99)

    def test_invalid_snapshot_raises(self):
        api = Mock()
        api.CreateToolhelp32Snapshot.return_value = process.INVALID_HANDLE_VALUE
        with patch.object(process, "kernel32", api), self.assertRaises(OSError):
            process.running_processes()
        api.CloseHandle.assert_not_called()

    def test_partial_enumeration_failure_does_not_select_an_incomplete_list(self):
        api = Mock()
        api.CreateToolhelp32Snapshot.return_value = 99
        api.Process32FirstW.return_value = False
        with patch.object(process, "kernel32", api), patch.object(ctypes, "get_last_error", return_value=5), self.assertRaises(OSError):
            process.running_processes()
        api.CloseHandle.assert_called_once_with(99)

    def test_path_lookup_denied_is_nonfatal(self):
        api = Mock()
        api.OpenProcess.return_value = 0
        with patch.object(process, "kernel32", api):
            self.assertEqual(process._process_image_path(10), "")
        api.CloseHandle.assert_not_called()

    def test_path_query_failure_still_closes_handle(self):
        api = Mock()
        api.OpenProcess.return_value = 99
        api.QueryFullProcessImageNameW.return_value = False
        with patch.object(process, "kernel32", api):
            self.assertEqual(process._process_image_path(10), "")
        api.CloseHandle.assert_called_once_with(99)
