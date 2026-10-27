import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit.app_updater import (
    APP_EXE_NAME,
    APP_INSTALL_FOLDER,
    is_installed_application,
    is_newer_version,
    parse_update_manifest,
    sha256_file,
)


class AppUpdaterTests(unittest.TestCase):
    def test_bata_release_name_and_prerelease_ordering(self):
        self.assertFalse(is_newer_version('1.3.0.bata1', '1.3.0.bata1'))
        self.assertTrue(is_newer_version('1.3.0.bata2', '1.3.0.bata1'))
        self.assertTrue(is_newer_version('1.3.0', '1.3.0.bata1'))
        self.assertFalse(is_newer_version('1.3.0.bata1', '1.3.0'))
        self.assertTrue(is_newer_version('1.3.1', '1.3.0.bata1'))
        self.assertFalse(is_newer_version('1.3.0b1', '1.3.0.bata1'))

    def test_detects_newer_semantic_version(self):
        self.assertTrue(is_newer_version("1.1.0", "1.0.2"))
        self.assertTrue(is_newer_version("v2.0", "1.9.9"))

    def test_equal_or_older_version_is_not_newer(self):
        self.assertFalse(is_newer_version("1.1", "1.1.0"))
        self.assertFalse(is_newer_version("1.0.9", "1.1.0"))

    def test_rejects_invalid_version(self):
        with self.assertRaises(ValueError):
            is_newer_version("latest", "1.0.0")

    def test_hashes_downloaded_update_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "update.exe"
            path.write_bytes(b"verified update")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"verified update").hexdigest())

    def test_download_suffix_follows_asset_url(self):
        from unittest.mock import patch

        from stellasora_toolkit.app_updater import AppUpdate, download_update

        update = AppUpdate("1.2.1", "https://example.test/tool.zip", "a" * 64, "")
        with tempfile.TemporaryDirectory() as directory:
            with patch("stellasora_toolkit.app_updater.urlopen") as open_url:
                response = open_url.return_value.__enter__.return_value
                response.headers.get.return_value = "4"
                response.read.side_effect = [b"data", b""]
                with patch("stellasora_toolkit.app_updater.hashlib.sha256") as sha:
                    sha.return_value.hexdigest.return_value = "a" * 64
                    path = download_update(update, Path(directory))
            self.assertEqual(path.suffix, ".zip")

    def test_parses_installer_asset_with_its_own_hash(self):
        update = parse_update_manifest(
            {
                "version": "1.2.0",
                "url": "https://example.test/portable.exe",
                "sha256": "a" * 64,
                "installer_url": "https://example.test/setup.exe",
                "installer_sha256": "b" * 64,
            }
        )
        self.assertTrue(update.has_installer)
        self.assertEqual(update.installer_sha256, "b" * 64)

    def test_recognizes_only_the_default_installed_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            app_data = Path(directory)
            installed = app_data / APP_INSTALL_FOLDER / APP_EXE_NAME
            portable = app_data / "Downloads" / APP_EXE_NAME
            with patch.dict("stellasora_toolkit.app_updater.os.environ", {"LOCALAPPDATA": str(app_data)}, clear=False):
                self.assertTrue(is_installed_application(installed))
                self.assertFalse(is_installed_application(portable))

    def test_recognizes_legacy_custom_install_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / APP_INSTALL_FOLDER / APP_EXE_NAME
            self.assertTrue(is_installed_application(executable))

    def test_uses_downloaded_updater_instead_of_older_bundled_helper(self):
        from stellasora_toolkit.app_updater import UPDATER_EXE_NAME, launch_update_installer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / APP_EXE_NAME
            executable.write_bytes(b"app")
            (root / UPDATER_EXE_NAME).write_bytes(b"old updater")
            package = root / "update.zip"
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('StellaSoraGachaTool/'+UPDATER_EXE_NAME, b'new updater')
            with patch("stellasora_toolkit.app_updater._directory_is_writable", return_value=True), patch(
                "stellasora_toolkit.app_updater.subprocess.Popen"
            ) as popen:
                launch_update_installer(package, executable)

            args = popen.call_args.args[0]
            self.assertEqual(Path(args[0]).read_bytes(), b'new updater')
            self.assertNotEqual(Path(args[0]).parent, root)
            self.assertEqual(args[args.index("--target-dir") + 1], str(root))
            self.assertEqual(args[args.index("--parent-pid") + 1], str(os.getpid()))
            self.assertEqual(args[args.index("--cleanup-dir") + 1], str(Path(args[0]).parent))

    def test_invalid_or_missing_package_helper_never_falls_back_to_old_helper(self):
        from stellasora_toolkit import app_updater
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root/APP_EXE_NAME; executable.write_bytes(b'app')
            (root/app_updater.UPDATER_EXE_NAME).write_bytes(b'old updater')
            for entries in (None, {}, {'a/StellaSoraUpdater.exe': b'one', 'b/StellaSoraUpdater.exe': b'two'}):
                package = root/'update.zip'
                if entries is None:
                    package.write_bytes(b'broken download')
                else:
                    with zipfile.ZipFile(package, 'w') as archive:
                        for name, content in entries.items(): archive.writestr(name, content)
                with self.subTest(entries=entries), patch.object(app_updater.subprocess, 'Popen') as start:
                    with self.assertRaises((zipfile.BadZipFile, FileNotFoundError)):
                        app_updater.launch_update_installer(package, executable)
                    start.assert_not_called()
                self.assertEqual(executable.read_bytes(), b'app')

    def test_refused_elevation_cleans_helper_and_leaves_program_unchanged(self):
        from stellasora_toolkit import app_updater
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root/APP_EXE_NAME; executable.write_bytes(b'old app')
            package = root/'update.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr('StellaSoraUpdater.exe', b'new updater')
            with patch.object(app_updater, '_directory_is_writable', return_value=False), \
                 patch('stellasora_toolkit.admin.request_elevation', side_effect=OSError('cancelled')) as elevate:
                with self.assertRaises(OSError): app_updater.launch_update_installer(package, executable)
            self.assertFalse(elevate.call_args.args[0].parent.exists())
            self.assertEqual(executable.read_bytes(), b'old app')

    def test_detects_bundled_update_installer(self):
        from stellasora_toolkit.app_updater import UPDATER_EXE_NAME, update_installer_available

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / APP_EXE_NAME
            executable.write_bytes(b"app")
            self.assertFalse(update_installer_available(executable))
            (root / UPDATER_EXE_NAME).write_bytes(b"updater")
            self.assertTrue(update_installer_available(executable))

    def test_extracts_updater_from_package_for_legacy_versions(self):
        import zipfile

        from stellasora_toolkit.app_updater import UPDATER_EXE_NAME, launch_update_installer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / APP_EXE_NAME
            executable.write_bytes(b"app")
            package = root / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(f"StellaSoraGachaTool/{UPDATER_EXE_NAME}", b"new updater")

            with patch("stellasora_toolkit.app_updater._directory_is_writable", return_value=True), patch(
                "stellasora_toolkit.app_updater.subprocess.Popen"
            ) as popen:
                launch_update_installer(package, executable)

            helper = Path(popen.call_args.args[0][0])
            self.assertEqual(helper.read_bytes(), b"new updater")


if __name__ == "__main__":
    unittest.main()
