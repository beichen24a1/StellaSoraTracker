import hashlib
import io
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

    def test_downloads_split_release_in_manifest_order_and_validates_full_hash(self):
        from dataclasses import asdict
        from stellasora_toolkit.app_updater import download_update

        parts = [b"first", b"second"]
        update = parse_update_manifest({
            "version": "2.1.0",
            "url": "https://example.test/archive.zip",
            "sha256": hashlib.sha256(b"".join(parts)).hexdigest(),
            "parts": [{"url": f"https://example.test/archive.zip.{i:03d}", "size": len(part)}
                      for i, part in enumerate(parts, 1)],
        })
        # Saved update receipts use dataclasses.asdict and reparse after restart.
        update = parse_update_manifest(asdict(update))
        with tempfile.TemporaryDirectory() as directory, \
                patch("stellasora_toolkit.app_updater.urlopen", side_effect=map(io.BytesIO, parts)) as open_url:
            metrics = []
            path = download_update(update, Path(directory), metrics=metrics.append)
            self.assertEqual(path.suffix, ".zip")
            self.assertEqual(path.read_bytes(), b"".join(parts))
            self.assertEqual([call.args[0].full_url for call in open_url.call_args_list],
                             [part.url for part in update.parts])
            self.assertEqual(metrics[-1]["received"], sum(map(len, parts)))
            self.assertTrue(all(item["total"] == sum(map(len, parts)) for item in metrics))

    def test_split_release_rejects_wrong_length_or_hash_without_leaving_package(self):
        from stellasora_toolkit.app_updater import download_update

        update = parse_update_manifest({
            "version": "2.1.0",
            "url": "https://example.test/archive.zip",
            "sha256": hashlib.sha256(b"good").hexdigest(),
            "parts": [{"url": "https://example.test/archive.zip.001", "size": 4}],
        })
        for payload, failure in [(b"end", "大小不符"), (b"extra", "大小不符"), (b"bad!", "checksum mismatch")]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory, \
                    patch("stellasora_toolkit.app_updater.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(ValueError, failure):
                    download_update(update, Path(directory), retries=1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_gitee_update_source_has_its_own_override(self):
        from stellasora_toolkit.app_updater import update_urls

        with patch.dict(os.environ, {"STELLASORA_UPDATE_MANIFEST_GITHUB": "https://example.test/github.json",
                                     "STELLASORA_UPDATE_MANIFEST_GITEE": ""}):
            self.assertEqual(update_urls("beta"), ["https://example.test/github.json"])
            self.assertEqual(update_urls("gitee"),
                             ["https://gitee.com/beichen_24/StellaSoraTracker/raw/main/app_update_gitee.json"])
            with patch.dict(os.environ, {"STELLASORA_UPDATE_MANIFEST_GITEE": "https://example.test/gitee.json"}):
                self.assertEqual(update_urls("gitee"), ["https://example.test/gitee.json"])

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
            self.assertNotEqual(Path(args[0]).parent.resolve(), root.resolve())
            # GitHub runner 的 tempfile 目录可能带 8.3 短名（RUNNER~1），
            # 更新器内部会 resolve 成长名，比较前两端都要规范化。
            self.assertEqual(Path(args[args.index("--target-dir") + 1]).resolve(), root.resolve())
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
