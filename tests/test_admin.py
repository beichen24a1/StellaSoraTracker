import ctypes
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stellasora_toolkit.admin import ensure_administrator
from stellasora_toolkit import gui


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.IsUserAnAdmin.return_value = False
        self.api.ShellExecuteW.return_value = 42
        self.native = patch("stellasora_toolkit.admin.ctypes.WinDLL", return_value=self.api).start()
        patch.object(sys, "frozen", True, create=True).start()
        self.addCleanup(patch.stopall)

    def test_source_mode_does_not_request_elevation(self):
        with patch.object(sys, "frozen", False):
            self.assertTrue(ensure_administrator([]))
        self.native.assert_not_called()

    def test_admin_instance_runs_without_relaunch(self):
        self.api.IsUserAnAdmin.return_value = True
        self.assertTrue(ensure_administrator([], relaunch_attempted=True))
        self.api.ShellExecuteW.assert_not_called()

    def test_non_admin_relaunch_preserves_output_path_and_working_directory(self):
        output = "E:\\Saved Records\\\u661f\u5854\\exports"
        self.assertFalse(ensure_administrator(["--output", output]))
        self.api.ShellExecuteW.assert_called_once_with(
            None, "runas", str(Path(sys.executable).resolve()),
            subprocess.list2cmdline(["--output", output, "--elevated"]), str(Path.cwd()), 1,
        )
        self.assertIs(self.api.ShellExecuteW.restype, ctypes.c_void_p)

    def test_denied_or_cancelled_uac_never_silently_runs_without_privileges(self):
        for result in (None, 0, 5, 32):
            self.api.ShellExecuteW.return_value = result
            with self.subTest(result=result), self.assertRaises(OSError):
                ensure_administrator([])

    def test_failed_elevated_instance_cannot_start_an_infinite_prompt_loop(self):
        with self.assertRaises(PermissionError):
            ensure_administrator([], relaunch_attempted=True)
        self.api.ShellExecuteW.assert_not_called()


class StartupTests(unittest.TestCase):
    def test_relaunch_exits_before_creating_window_or_loading_records(self):
        with patch.object(gui, "ensure_administrator", return_value=False) as ensure, patch.object(gui.tk, "Tk") as root, patch.object(gui, "StellaSoraApp") as app:
            self.assertEqual(gui.main(["--output", "build/test exports"]), 0)
        ensure.assert_called_once_with(["--output", str(Path("build/test exports").resolve())], relaunch_attempted=False)
        root.assert_not_called()
        app.assert_not_called()

    def test_denied_startup_reports_error_without_opening_app(self):
        with patch.object(gui, "ensure_administrator", side_effect=PermissionError("cancelled")), patch.object(gui.tk, "Tk") as root, patch.object(gui, "StellaSoraApp") as app, patch.object(gui.messagebox, "showerror") as error:
            self.assertEqual(gui.main(["--elevated"]), 1)
        error.assert_called_once()
        root.return_value.destroy.assert_called_once()
        app.assert_not_called()

    def test_smoke_test_never_requests_uac_or_runs_mainloop(self):
        with patch.object(gui, "ensure_administrator") as ensure, patch.object(gui.tk, "Tk") as root, patch.object(gui, "StellaSoraApp"):
            self.assertEqual(gui.main(["--smoke-test"]), 0)
        ensure.assert_not_called()
        root.return_value.update_idletasks.assert_called_once()
        root.return_value.destroy.assert_called_once()
        root.return_value.mainloop.assert_not_called()
