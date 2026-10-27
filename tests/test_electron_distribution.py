import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.pack_electron_local import build_zip, ROOT, CURRENT_NOTICES
from stellasora_toolkit import app_updater, update_installer


class ElectronDistributionTests(unittest.TestCase):
    def source(self, root):
        source=root/'source';source.mkdir()
        for name in ('StellaSoraGachaTool.exe','StellaSoraUpdater.exe','resources/app.asar',
                     'resources/engine/StellaSoraEngine.exe','LICENSE','README.md','THIRD_PARTY_NOTICES.txt',
                     'LICENSE.electron.txt','LICENSES.chromium.html'):
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        return source

    def test_local_zip_excludes_personal_data_and_keeps_runtime_and_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root)
            for name in ('exports/100000001.json','.desktop/Cookies','logs/private.log','accounts.json','uid.json','fortune.json',
                         'stellasora_gacha_archive.json','accounts/default/private.json','account_sessions/10-1000.blocked',
                         'UID.JSON','100123456.json','crash.log','archive_layout.json','.storage.lock','updates/ready.json',
                         'backups/private.json','ui_settings.json','rem_upload_endpoint.txt'):
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'private')
            target=root/'local.zip';result=build_zip(source,target)
            self.assertEqual(len(result['sha256']),64)
            with zipfile.ZipFile(target) as archive:
                names=archive.namelist()
                self.assertEqual(len(names),9)
                self.assertIn('StellaSoraGachaTool/resources/engine/StellaSoraEngine.exe',names)
                self.assertIn('StellaSoraGachaTool/THIRD_PARTY_NOTICES.txt',names)

    def test_zip_uses_current_notices_instead_of_stale_build_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root)
            for name in CURRENT_NOTICES:
                (source/name).write_text('stale build notice', encoding='utf-8')
            target=root/'local.zip';build_zip(source,target)
            with zipfile.ZipFile(target) as archive:
                for name in CURRENT_NOTICES:
                    self.assertEqual(archive.read('StellaSoraGachaTool/'+name), (ROOT/name).read_bytes())

    def test_disk_error_preserves_previous_zip_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root)
            target=root/'local.zip';target.write_bytes(b'previous zip')
            checksum=target.with_suffix('.sha256');checksum.write_bytes(b'previous checksum')
            with patch.object(zipfile.ZipFile,'write',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):build_zip(source,target)
            self.assertEqual(target.read_bytes(),b'previous zip')
            self.assertEqual(checksum.read_bytes(),b'previous checksum')
            self.assertEqual(list(root.glob('*.part')),[])

    def test_qt_runtime_causes_packaging_failure_and_preserves_previous_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=self.source(root)
            (source/'PySide6.dll').write_bytes(b'forbidden runtime')
            target=root/'local.zip';target.write_bytes(b'previous local build')
            with self.assertRaises(ValueError):build_zip(source,target)
            self.assertEqual(target.read_bytes(),b'previous local build')

    def test_updater_accepts_extra_processes_to_wait_for(self):
        args=update_installer.build_parser().parse_args(['--package','fixture.zip','--target-dir','fixture',
            '--parent-pid','10','--wait-pid','11','--wait-pid','12'])
        self.assertEqual(args.wait_pid,[11,12])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            executable=root/app_updater.APP_EXE_NAME;executable.write_bytes(b'fixture')
            (root/app_updater.UPDATER_EXE_NAME).write_bytes(b'updater')
            package=root/'update.zip'
            with zipfile.ZipFile(package,'w') as archive:
                archive.writestr('StellaSoraUpdater.exe',b'new updater')
            with patch.object(app_updater,'_directory_is_writable',return_value=True),patch.object(app_updater.subprocess,'Popen') as start:
                app_updater.launch_update_installer(package,executable,wait_pids=[11,12,11])
            command=start.call_args.args[0]
            self.assertEqual(command.count('--wait-pid'),2)
            self.assertIn('11',command);self.assertIn('12',command)
