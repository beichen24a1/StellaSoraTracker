import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import update_installer
from stellasora_toolkit.update_installer import (
    APP_EXE_NAME,
    acl_grants,
    apply_update,
    extract_update_package,
    plain_user_can_use,
    verify_installation,
)

GENERIC_READ = 0x120089
GENERIC_EXECUTE = 0x1200A0
GENERIC_READ_EXECUTE = GENERIC_READ | GENERIC_EXECUTE
USER_SID = 'S-1-5-21-1000'
OTHER_USER_SID = 'S-1-5-21-2000'
USERS_SID = 'S-1-5-32-545'


class UpdateInstallerTests(unittest.TestCase):
    def _write_package(self, path: Path, files: dict[str, bytes]) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def _allow_any_launch(self):
        # Machine ACLs differ between developer machines, so the installer tests
        # stub the "ordinary user can start it" probe. Its own behaviour is
        # covered by AclDecisionTests and VerificationTests.
        return patch("stellasora_toolkit.update_installer.plain_user_can_use", return_value=True)

    def test_applies_wrapped_portable_package_and_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            (target / APP_EXE_NAME).write_bytes(b"old")
            (target / "_internal").mkdir()
            (target / "_internal" / "old.dll").write_bytes(b"old dll")
            (target / "exports").mkdir()
            (target / "exports" / "history.json").write_bytes(b"user data")
            package = root / "update.zip"
            self._write_package(
                package,
                {
                    f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new",
                    "StellaSoraGachaTool/_internal/new.dll": b"new dll",
                },
            )

            with self._allow_any_launch():
                work_dir = apply_update(package, target)

            self.assertEqual((target / APP_EXE_NAME).read_bytes(), b"new")
            self.assertTrue((target / "_internal" / "new.dll").is_file())
            self.assertFalse((target / "_internal" / "old.dll").exists())
            self.assertEqual((target / "exports" / "history.json").read_bytes(), b"user data")
            self.assertTrue(work_dir.is_dir())

    def test_payload_is_copied_so_installed_files_inherit_program_folder(self):
        """Renaming a payload entry keeps the updater's temporary ACL; copying inherits."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            (target / APP_EXE_NAME).write_bytes(b"old")
            package = root / "update.zip"
            self._write_package(package, {f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new"})

            with self._allow_any_launch():
                work_dir = apply_update(package, target)

            payload = work_dir / "new" / "StellaSoraGachaTool" / APP_EXE_NAME
            self.assertTrue(payload.is_file(), "payload must be copied, not moved into place")
            self.assertEqual((target / APP_EXE_NAME).read_bytes(), b"new")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "update.zip"
            self._write_package(package, {"../outside.txt": b"bad", APP_EXE_NAME: b"new"})
            destination = root / "extract"
            destination.mkdir()
            with self.assertRaises(ValueError):
                extract_update_package(package, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_packages_that_contain_user_data_directories(self):
        for private in ('exports', 'updates', 'backups', '.desktop'):
            with self.subTest(directory=private), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = root / "update.zip"
                self._write_package(
                    package,
                    {
                        f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new",
                        f"StellaSoraGachaTool/{private}/history.json": b"must not overwrite",
                    },
                )
                destination = root / "extract"
                destination.mkdir()
                with self.assertRaises(ValueError):
                    extract_update_package(package, destination)

    def test_rolls_back_when_installing_new_files_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            original = target / APP_EXE_NAME
            original.write_bytes(b"old")
            package = root / "update.zip"
            self._write_package(package, {APP_EXE_NAME: b"new", "second.dat": b"new data"})

            real_install = update_installer._install_entry
            calls = 0

            def failing_install(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated failure")
                return real_install(source, destination)

            with patch("stellasora_toolkit.update_installer._install_entry", side_effect=failing_install):
                with self.assertRaises(OSError):
                    apply_update(package, target)

            self.assertEqual(original.read_bytes(), b"old")
            self.assertFalse((target / "second.dat").exists())

    def test_rolls_back_when_verification_rejects_the_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            original = target / APP_EXE_NAME
            original.write_bytes(b"old")
            package = root / "update.zip"
            self._write_package(package, {APP_EXE_NAME: b"new", "second.dat": b"new data"})

            with patch("stellasora_toolkit.update_installer.verify_installation",
                       side_effect=RuntimeError("主程序权限异常")):
                with self.assertRaises(RuntimeError):
                    apply_update(package, target)

            self.assertEqual(original.read_bytes(), b"old")
            self.assertFalse((target / "second.dat").exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_work_directory_does_not_keep_the_administrators_only_acl(self):
        """mkdtemp(0o700) would hand the extracted payload an admin-only DACL."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app"
            target.mkdir()
            (target / APP_EXE_NAME).write_bytes(b"old")
            package = root / "update.zip"
            self._write_package(package, {f"StellaSoraGachaTool/{APP_EXE_NAME}": b"new"})

            with self._allow_any_launch():
                work_dir = apply_update(package, target)

            self.assertIs(update_installer._dacl_is_protected(work_dir), False,
                          "the work directory must inherit the temp folder's ACL")
            self.assertIs(update_installer._dacl_is_protected(work_dir / "new"), False)
            self.assertIs(update_installer._dacl_is_protected(target / APP_EXE_NAME), False,
                          "installed files must inherit the program folder's ACL")


class InheritanceResetTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_inherit_security_clears_a_protected_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(tempfile.mkdtemp(prefix='stellasora-update-work-test', dir=directory))
            self.assertIs(update_installer._dacl_is_protected(work), True,
                          'mkdtemp(0o700) is expected to create a protected DACL')
            self.assertTrue(update_installer.inherit_security(work))
            self.assertIs(update_installer._dacl_is_protected(work), False)

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_inherit_security_reports_a_failing_icacls(self):
        with patch.object(update_installer.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 5)):
            self.assertFalse(update_installer.inherit_security(Path('whatever')))

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_repairs_a_folder_damaged_by_a_legacy_moved_install(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'app'
            target.mkdir()
            damaged = target / APP_EXE_NAME
            damaged.write_bytes(b'old')
            # A legacy "move" install kept the updater's temporary descriptor:
            # an explicit ACL instead of one inherited from the program folder.
            setup = subprocess.run(['icacls', str(damaged), '/inheritance:r'], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(setup.returncode, 0)
            self.assertIs(update_installer._dacl_is_protected(damaged), True)

            self.assertTrue(update_installer.repair_install_permissions(target))
            self.assertIs(update_installer._dacl_is_protected(damaged), False)
            self.assertFalse(update_installer.repair_install_permissions(target),
                             'a repaired folder needs no second reset')

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_leaves_a_healthy_folder_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / APP_EXE_NAME).write_bytes(b'program')
            (target / 'exports').mkdir()
            with patch.object(update_installer.subprocess, 'run') as icacls:
                self.assertFalse(update_installer.repair_install_permissions(target))
            icacls.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_skips_repair_when_the_program_folder_itself_is_locked_down(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / APP_EXE_NAME).write_bytes(b'program')
            with patch.object(update_installer, '_dacl_is_protected', return_value=True), \
                    patch.object(update_installer, 'inherit_security') as reset:
                self.assertFalse(update_installer.repair_install_permissions(target))
            reset.assert_not_called()


class AclDecisionTests(unittest.TestCase):
    def test_read_and_execute_grants_can_be_split_across_matching_aces(self):
        aces = [
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, USER_SID, update_installer._READ_RIGHTS),
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, USERS_SID, update_installer._FILE_EXECUTE),
        ]
        self.assertTrue(acl_grants({USER_SID, USERS_SID}, update_installer._EXECUTE_RIGHTS, aces))
    def test_read_execute_allow_for_the_user_is_accepted(self):
        aces = [(update_installer._ACCESS_ALLOWED_ACE_TYPE, USER_SID, GENERIC_READ_EXECUTE)]
        self.assertTrue(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces))

    def test_allow_for_users_group_is_accepted(self):
        aces = [(update_installer._ACCESS_ALLOWED_ACE_TYPE, USERS_SID, GENERIC_READ_EXECUTE)]
        self.assertTrue(acl_grants({USER_SID, USERS_SID}, update_installer._EXECUTE_RIGHTS, aces))

    def test_administrators_only_acl_is_rejected(self):
        """The regression behind a launcher that stops starting after an update."""
        aces = [
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-5-18', GENERIC_READ_EXECUTE),
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-5-32-544', GENERIC_READ_EXECUTE),
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-3-4', GENERIC_READ_EXECUTE),
        ]
        self.assertFalse(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces))

    def test_deny_wins_over_allow(self):
        aces = [
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, USER_SID, GENERIC_READ_EXECUTE),
            (update_installer._ACCESS_DENIED_ACE_TYPE, USER_SID, update_installer._FILE_EXECUTE),
        ]
        self.assertFalse(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces))

    def test_owner_rights_apply_to_the_owner(self):
        aces = [(update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-3-4', GENERIC_READ_EXECUTE)]
        self.assertTrue(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces, owner=USER_SID))
        self.assertFalse(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces, owner=OTHER_USER_SID))

    def test_allow_must_cover_every_requested_bit(self):
        aces = [(update_installer._ACCESS_ALLOWED_ACE_TYPE, USER_SID, update_installer._FILE_READ_DATA)]
        self.assertFalse(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces))
        self.assertTrue(acl_grants({USER_SID}, update_installer._FILE_READ_DATA, aces))

    def test_read_execute_requires_read_control_and_extended_attributes(self):
        for missing in (0x00020000, 0x0008):
            with self.subTest(missing=missing):
                aces = [(update_installer._ACCESS_ALLOWED_ACE_TYPE, USER_SID, GENERIC_READ_EXECUTE & ~missing)]
                self.assertFalse(acl_grants({USER_SID}, update_installer._EXECUTE_RIGHTS, aces))


class PlainUserProbeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_empty_dacl_is_blocked_instead_of_treated_as_unknown(self):
        with patch('stellasora_toolkit.update_installer._file_security', return_value=(USER_SID, [])), \
             patch('stellasora_toolkit.update_installer._current_user_sid', return_value=USER_SID):
            self.assertIs(plain_user_can_use(Path('whatever'), execute=True), False)
    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_missing_security_descriptor_is_reported_as_unknown(self):
        with patch("stellasora_toolkit.update_installer._file_security", side_effect=OSError("denied")):
            self.assertIsNone(plain_user_can_use(Path('whatever')))

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_administrators_only_descriptor_is_reported_as_blocked(self):
        aces = [
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-5-18', GENERIC_READ_EXECUTE),
            (update_installer._ACCESS_ALLOWED_ACE_TYPE, 'S-1-5-32-544', GENERIC_READ_EXECUTE),
        ]
        with patch("stellasora_toolkit.update_installer._file_security", return_value=(None, aces)), \
                patch("stellasora_toolkit.update_installer._current_user_sid", return_value=USER_SID):
            self.assertIs(plain_user_can_use(Path('whatever'), execute=True), False)

    @unittest.skipUnless(os.name == 'nt', 'Windows security descriptors only')
    def test_null_dacl_means_everyone_is_allowed(self):
        with patch("stellasora_toolkit.update_installer._file_security", return_value=None), \
                patch("stellasora_toolkit.update_installer._current_user_sid", return_value=USER_SID):
            self.assertIs(plain_user_can_use(Path('whatever')), True)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.target = Path(self.directory.name)
        self.executable = self.target / APP_EXE_NAME
        self.executable.write_bytes(b"new")

    def tearDown(self):
        self.directory.cleanup()

    def test_requires_the_main_executable(self):
        self.executable.unlink()
        with self.assertRaises(RuntimeError):
            verify_installation(self.target, [])

    def test_rejects_an_executable_only_administrators_can_start(self):
        with patch("stellasora_toolkit.update_installer.plain_user_can_use", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "权限"):
                verify_installation(self.target, [self.executable])

    def test_accepts_an_unknown_launch_probe(self):
        with patch("stellasora_toolkit.update_installer.plain_user_can_use", return_value=None):
            verify_installation(self.target, [self.executable])

    def test_rejects_unreadable_payload_files(self):
        payload = self.target / APP_EXE_NAME
        payload.write_bytes(b"new")
        with patch("stellasora_toolkit.update_installer.plain_user_can_use", return_value=True), \
                patch.object(Path, "open", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeError, "无法读取"):
                verify_installation(self.target, [payload])

    def test_checks_runtime_dependencies_as_an_ordinary_user(self):
        directory = self.target/'resources'; directory.mkdir()
        dependency = directory/'engine.dll'; dependency.write_bytes(b'dependency')
        with patch('stellasora_toolkit.update_installer.plain_user_can_use',
                   side_effect=lambda path, **_kwargs: path != dependency):
            with self.assertRaisesRegex(RuntimeError, 'engine.dll'):
                verify_installation(self.target, [self.executable, directory])

    def test_checks_program_directory_access_before_accepting_update(self):
        with patch('stellasora_toolkit.update_installer.plain_user_can_use',
                   side_effect=lambda path, **_kwargs: path != self.target):
            with self.assertRaisesRegex(RuntimeError, '新文件夹'):
                verify_installation(self.target, [self.executable])

    def test_rejects_entries_that_keep_a_protected_descriptor(self):
        """An entry carrying the updater's temporary admin-only ACL is not usable."""
        with patch('stellasora_toolkit.update_installer._dacl_is_protected', return_value=True), \
                patch('stellasora_toolkit.update_installer.plain_user_can_use', return_value=True):
            with self.assertRaisesRegex(RuntimeError, '未继承'):
                verify_installation(self.target, [self.executable])

    def test_tolerates_an_unreadable_security_descriptor(self):
        with patch('stellasora_toolkit.update_installer._dacl_is_protected', return_value=None), \
                patch('stellasora_toolkit.update_installer.plain_user_can_use', return_value=True):
            verify_installation(self.target, [self.executable])


class RestartRollbackTests(unittest.TestCase):
    def test_restart_requests_elevation_when_the_manifest_requires_it(self):
        """The packaged client needs UAC, so CreateProcess fails with WinError 740."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / APP_EXE_NAME).write_bytes(b'new')
            refused = OSError(740, '请求的操作需要提升')
            refused.winerror = 740
            with patch.object(update_installer.subprocess, 'Popen', side_effect=refused), \
                    patch('stellasora_toolkit.admin.request_elevation') as elevate:
                update_installer.restart_application(target, APP_EXE_NAME)
            elevate.assert_called_once()
            self.assertEqual(Path(elevate.call_args.args[0]), target / APP_EXE_NAME)
            self.assertEqual(elevate.call_args.kwargs['working_directory'], target)

    def test_restart_failures_other_than_elevation_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / APP_EXE_NAME).write_bytes(b'new')
            with patch.object(update_installer.subprocess, 'Popen', side_effect=OSError(5, 'access denied')), \
                    patch('stellasora_toolkit.admin.request_elevation') as elevate:
                with self.assertRaises(OSError):
                    update_installer.restart_application(target, APP_EXE_NAME)
            elevate.assert_not_called()

    def test_missing_backup_does_not_delete_current_program(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'app'; target.mkdir()
            executable = target/APP_EXE_NAME; executable.write_bytes(b'current program')
            work = root/'work'; work.mkdir()
            (work/'backup').mkdir()
            (work/'installed.json').write_text(json.dumps({
                'target':str(target.resolve()), 'entries':[APP_EXE_NAME], 'replaced':[APP_EXE_NAME],
            }), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, '备份不完整'):
                update_installer.rollback_completed_update(work, target)
            self.assertEqual(executable.read_bytes(), b'current program')

    def test_invalid_rollback_record_cannot_remove_user_data(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'app'; target.mkdir()
            (target/'exports').mkdir()
            archive = target/'exports/history.json'; archive.write_bytes(b'private records')
            work = root/'work'; work.mkdir()
            for name in ('exports', '.desktop', '..', '../outside'):
                (work/'installed.json').write_text(json.dumps({'target':str(target.resolve()),'entries':[name]}), encoding='utf-8')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    update_installer.rollback_completed_update(work, target)
                self.assertEqual(archive.read_bytes(), b'private records')

    def test_access_denied_on_restart_restores_program_and_keeps_download_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'app'; target.mkdir()
            (target/APP_EXE_NAME).write_bytes(b'old program')
            (target/'StellaSoraUpdater.exe').write_bytes(b'old updater')
            (target/'exports').mkdir()
            (target/'exports/history.json').write_bytes(b'private records')
            package = root/'update.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                for name, content in {APP_EXE_NAME:b'new program', 'StellaSoraUpdater.exe':b'new updater', 'extra.dll':b'new'}.items():
                    archive.writestr('StellaSoraGachaTool/'+name, content)
            with patch.object(update_installer, 'plain_user_can_use', return_value=True), \
                 patch.object(update_installer, 'prune_stale_directories', return_value=[]), \
                 patch.object(update_installer, 'wait_for_process_exit'), \
                 patch.object(update_installer, 'restart_application', side_effect=PermissionError('access denied')), \
                 patch.object(update_installer, 'show_error') as error:
                code = update_installer.main(['--package', str(package), '--target-dir', str(target), '--parent-pid', '10'])
            self.assertEqual(code, 1)
            error.assert_called_once()
            self.assertEqual((target/APP_EXE_NAME).read_bytes(), b'old program')
            self.assertEqual((target/'StellaSoraUpdater.exe').read_bytes(), b'old updater')
            self.assertFalse((target/'extra.dll').exists())
            self.assertEqual((target/'exports/history.json').read_bytes(), b'private records')
            self.assertTrue(package.exists())


@unittest.skipUnless(os.name == 'nt', 'Real Windows execute ACL regression')
class WindowsLaunchPermissionTests(unittest.TestCase):
    def test_copied_program_starts_when_legacy_moved_program_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.exe'
            source.write_bytes((Path(os.environ['SystemRoot'])/'System32/cmd.exe').read_bytes())
            target = root/'app'; target.mkdir()
            quote = lambda value: str(value).replace("'", "''")
            script = f'''
$ErrorActionPreference = 'Stop'
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -LiteralPath '{quote(source)}'
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, [Security.AccessControl.FileSystemRights]::ExecuteFile, [Security.AccessControl.AccessControlType]::Deny))
Set-Acl -LiteralPath '{quote(source)}' -AclObject $acl
$folder = Get-Acl -LiteralPath '{quote(target)}'
$folder.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
Set-Acl -LiteralPath '{quote(target)}' -AclObject $folder
'''
            setup = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                   env={key:value for key,value in os.environ.items() if key.casefold() != 'psmodulepath'})
            self.assertEqual(setup.returncode, 0, setup.stderr.decode('utf-8', errors='replace'))
            legacy = root/'legacy-moved.exe'
            shutil.move(source, legacy)
            with self.assertRaises(PermissionError):
                subprocess.run([str(legacy), '/d', '/c', 'exit', '0'], check=True,
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            executable = target/APP_EXE_NAME
            second = target/'StellaSoraUpdater.exe'
            update_installer._install_entry(legacy, executable)
            update_installer._install_entry(legacy, second)
            verify_installation(target, [executable, second])
            result = subprocess.run([str(second), '/d', '/c', 'exit', '0'], capture_output=True,
                                    timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0)


@unittest.skipUnless(os.name == 'nt', 'temp cleanup only runs on Windows')
class TempCleanupTests(unittest.TestCase):
    def test_self_cleanup_uses_windows_powershell_without_path_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory)/'stellasora-updater-qa'; helper.mkdir()
            with patch.object(update_installer.sys, 'frozen', True, create=True), \
                    patch.object(update_installer.subprocess, 'Popen') as launch, \
                    patch.dict(os.environ, {'PATH':'', 'SystemRoot':r'C:\Windows'}):
                update_installer.schedule_self_cleanup(helper)
            self.assertEqual(launch.call_args.args[0][0],
                             str(Path(r'C:\Windows')/'System32/WindowsPowerShell/v1.0/powershell.exe'))

    def test_self_cleanup_launch_failure_does_not_fail_a_completed_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'app'; target.mkdir()
            package = root/'update.zip'; package.write_bytes(b'consumed package')
            work = root/'work'; work.mkdir()
            helper = root/'stellasora-updater-qa'; helper.mkdir()
            with patch.object(update_installer.sys, 'frozen', True, create=True), \
                    patch.object(update_installer, 'prune_stale_directories', return_value=[]), \
                    patch.object(update_installer, 'wait_for_process_exit'), \
                    patch.object(update_installer, 'apply_update', return_value=work), \
                    patch.object(update_installer, 'restart_application') as restart, \
                    patch.object(update_installer.subprocess, 'Popen', side_effect=FileNotFoundError('PowerShell unavailable')), \
                    patch.object(update_installer, 'show_error') as show_error:
                code = update_installer.main(['--package',str(package),'--target-dir',str(target),
                                               '--parent-pid','10','--cleanup-dir',str(helper)])
            self.assertEqual(code, 0)
            restart.assert_called_once()
            show_error.assert_not_called()
            self.assertFalse(package.exists())
            self.assertFalse(work.exists())
            self.assertTrue(helper.exists(), 'failed cleanup is left for a later run')

    def test_removes_only_stale_directories_and_keeps_the_active_one(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            stale_helper = temp / 'stellasora-updater-aaaaaaaa'
            stale_helper.mkdir()
            (stale_helper / 'StellaSoraUpdater.exe').write_bytes(b'fixture')
            stale_work = temp / 'stellasora-update-work-bbbbbbbb'
            (stale_work / 'backup').mkdir(parents=True)
            active_helper = temp / 'stellasora-updater-active00'
            active_helper.mkdir()
            young_work = temp / 'stellasora-update-work-young000'
            young_work.mkdir()
            old = time.time() - 8 * 24 * 60 * 60
            for path in (stale_helper, stale_work, active_helper):
                os.utime(path, (old, old))

            with patch.object(update_installer.tempfile, 'gettempdir', return_value=str(temp)):
                removed = update_installer.prune_stale_directories(keep=active_helper, roots=[temp])

            self.assertEqual({path.name for path in removed}, {stale_helper.name, stale_work.name})
            self.assertFalse(stale_helper.exists())
            self.assertFalse(stale_work.exists())
            self.assertTrue(active_helper.exists(), 'the running update helper must survive')
            self.assertTrue(young_work.exists(), 'a recent work directory may still be in use')

    def test_leaves_recent_directories_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            recent = temp / 'stellasora-updater-recent00'
            recent.mkdir()
            with patch.object(update_installer.tempfile, 'gettempdir', return_value=str(temp)):
                self.assertEqual(update_installer.prune_stale_directories(roots=[temp]), [])
            self.assertTrue(recent.exists())

    def test_resets_permissions_and_retries_before_giving_up(self):
        import time

        real_rmtree = update_installer.shutil.rmtree
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            stuck = temp / 'stellasora-updater-stuck000'
            stuck.mkdir()
            (stuck / 'StellaSoraUpdater.exe').write_bytes(b'fixture')
            old = time.time() - 8 * 24 * 60 * 60
            os.utime(stuck, (old, old))

            attempts = {'count': 0}

            def delete_after_reset(path, ignore_errors=False):
                attempts['count'] += 1
                if attempts['count'] >= 2:  # only after the permission reset
                    real_rmtree(path, ignore_errors=ignore_errors)

            with patch.object(update_installer.shutil, 'rmtree', side_effect=delete_after_reset), \
                    patch.object(update_installer.subprocess, 'run') as reset:
                removed = update_installer.prune_stale_directories(roots=[temp])

            reset.assert_called_once()
            self.assertIn('/reset', reset.call_args.args[0])
            self.assertEqual(removed, [stuck])
            self.assertFalse(stuck.exists())

    def test_does_not_report_directories_it_could_not_remove(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            stuck = temp / 'stellasora-updater-stuck111'
            stuck.mkdir()
            (stuck / 'StellaSoraUpdater.exe').write_bytes(b'fixture')
            old = time.time() - 8 * 24 * 60 * 60
            os.utime(stuck, (old, old))

            with patch.object(update_installer.shutil, 'rmtree'), \
                    patch.object(update_installer.subprocess, 'run'):
                removed = update_installer.prune_stale_directories(roots=[temp])

            self.assertEqual(removed, [])
            self.assertTrue(stuck.exists())


if __name__ == "__main__":
    unittest.main()
