import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stellasora_toolkit.admin import AdminRequired, is_administrator, request_elevation


class AdministratorProbeTests(unittest.TestCase):
    def test_reports_an_administrator_token(self):
        api = Mock()
        api.IsUserAnAdmin.return_value = True
        with patch("stellasora_toolkit.admin.ctypes.WinDLL", return_value=api):
            self.assertTrue(is_administrator())

    def test_reports_a_normal_user_token(self):
        api = Mock()
        api.IsUserAnAdmin.return_value = False
        with patch("stellasora_toolkit.admin.ctypes.WinDLL", return_value=api):
            self.assertFalse(is_administrator())

    @unittest.skipUnless(os.name == 'nt', 'Windows shell elevation only')
    def test_request_elevation_starts_the_executable_through_runas(self):
        api = Mock()
        api.ShellExecuteW.return_value = 42
        target = Path(sys.executable)
        with patch("stellasora_toolkit.admin.ctypes.WinDLL", return_value=api):
            request_elevation(target, ['--x'], working_directory=Path.cwd())
        api.ShellExecuteW.assert_called_once_with(
            None, "runas", str(target.resolve()), subprocess.list2cmdline(['--x']), str(Path.cwd().resolve()), 1,
        )

    @unittest.skipUnless(os.name == 'nt', 'Windows shell elevation only')
    def test_request_elevation_reports_a_refused_prompt(self):
        for result in (None, 0, 5, 32):
            api = Mock()
            api.ShellExecuteW.return_value = result
            with self.subTest(result=result), patch("stellasora_toolkit.admin.ctypes.WinDLL", return_value=api):
                with self.assertRaises(OSError):
                    request_elevation(Path(sys.executable))

    def test_admin_required_is_a_permission_error(self):
        self.assertTrue(issubclass(AdminRequired, PermissionError))
