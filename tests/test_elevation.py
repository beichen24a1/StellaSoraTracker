import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import desktop_engine
from stellasora_toolkit.admin import AdminRequired
from stellasora_toolkit.app_updater import APP_EXE_NAME
from stellasora_toolkit.desktop_engine import Engine


def make_engine(directory: str) -> Engine:
    return Engine(Path(directory) / 'exports', Path(directory), lambda _value: None, offline=True)


class AdministrationGateTests(unittest.TestCase):
    def test_packaged_client_without_administration_needs_it(self):
        with patch.object(sys, 'frozen', True, create=True), \
                patch('stellasora_toolkit.admin.is_administrator', return_value=False):
            self.assertTrue(desktop_engine.administrator_required())

    def test_source_runs_and_elevated_clients_are_allowed(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertFalse(desktop_engine.administrator_required())
        with patch.object(sys, 'frozen', True, create=True), \
                patch('stellasora_toolkit.admin.is_administrator', return_value=True):
            self.assertFalse(desktop_engine.administrator_required())

    def test_memory_reads_are_refused_before_touching_the_application(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = make_engine(directory)
            engine.app = None  # any use of the application would fail loudly
            with patch.object(desktop_engine, 'administrator_required', return_value=True):
                for method in sorted(desktop_engine.ADMIN_METHODS):
                    with self.subTest(method=method), self.assertRaises(AdminRequired):
                        engine.dispatch(method, {'pid': 1})

    def test_non_privileged_methods_still_work_in_normal_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = make_engine(directory)
            with patch.object(desktop_engine, 'administrator_required', return_value=True):
                state = engine.dispatch('app.state', {})
            self.assertEqual(state['protocolVersion'], 1)
            self.assertIn('preferences', state)


class LauncherCommandLineTests(unittest.TestCase):
    def test_launcher_target_sits_next_to_the_launcher(self):
        from launcher_client import launch_target
        self.assertEqual(launch_target(Path('C:/Program')), Path('C:/Program') / APP_EXE_NAME)

    def test_launcher_drops_node_mode_variables(self):
        from launcher_client import strip_node_mode_environment
        with patch.dict(os.environ, {'ELECTRON_RUN_AS_NODE': '1', 'NODE_OPTIONS': '--x'}, clear=False):
            self.assertEqual(sorted(strip_node_mode_environment()), ['ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS'])
            self.assertNotIn('ELECTRON_RUN_AS_NODE', os.environ)
            self.assertNotIn('NODE_OPTIONS', os.environ)

    def test_admin_flag_is_consumed_and_other_arguments_forwarded(self):
        from launcher_client import ADMIN_FLAG, split_arguments
        self.assertEqual(split_arguments([ADMIN_FLAG, '--output', 'x']), (True, ['--output', 'x']))
        self.assertEqual(split_arguments([]), (False, []))

    def test_missing_client_is_reported_instead_of_starting_nothing(self):
        from launcher_client import main
        with tempfile.TemporaryDirectory() as directory, \
                patch('launcher_client.launch_target', return_value=Path(directory) / APP_EXE_NAME), \
                patch('launcher_client.show_error') as error:
            self.assertEqual(main([]), 1)
        error.assert_called_once()
        self.assertIn(APP_EXE_NAME, error.call_args.args[0])

    def test_normal_launch_does_not_request_administrator_rights(self):
        from launcher_client import main
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / APP_EXE_NAME
            executable.write_bytes(b'fixture')
            with patch('launcher_client.launch_target', return_value=executable), \
                    patch('launcher_client.subprocess.Popen') as start, \
                    patch('launcher_client.request_elevation') as elevation:
                self.assertEqual(main(['--output', 'x']), 0)
        elevation.assert_not_called()
        start.assert_called_once_with([str(executable), '--output', 'x'], cwd=str(executable.parent))

    def test_admin_mode_starts_the_client_elevated(self):
        from launcher_client import main
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / APP_EXE_NAME
            executable.write_bytes(b'fixture')
            with patch('launcher_client.launch_target', return_value=executable), \
                    patch('launcher_client.request_elevation') as elevation, \
                    patch('launcher_client.subprocess.Popen') as start:
                self.assertEqual(main(['--admin']), 0)
        start.assert_not_called()
        elevation.assert_called_once_with(executable, [])

    def test_refused_elevation_is_reported(self):
        from launcher_client import main
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / APP_EXE_NAME
            executable.write_bytes(b'fixture')
            with patch('launcher_client.launch_target', return_value=executable), \
                    patch('launcher_client.request_elevation', side_effect=OSError('cancelled')), \
                    patch('launcher_client.show_error') as error:
                self.assertEqual(main(['--admin']), 1)
        error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
