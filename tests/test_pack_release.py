import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import pack_release
from stellasora_toolkit.project import GITHUB_REPOSITORY
import json


class ReleasePackagingTests(unittest.TestCase):
    def test_zip_uses_current_notices_even_if_build_folder_has_old_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            source.mkdir()
            for name in ('LICENSE', 'readme.md'):
                (source/name).write_text('stale build notice', encoding='utf-8')
            with patch.object(pack_release, 'RELEASE_DIR', root/'release'):
                result = pack_release.build_zip('fixture', source)
            with zipfile.ZipFile(result) as archive:
                self.assertEqual(set(archive.namelist()), {
                    'StellaSoraGachaTool/LICENSE', 'StellaSoraGachaTool/README.md'})
                for name in pack_release.DISTRIBUTION_NOTICES:
                    self.assertEqual(archive.read('StellaSoraGachaTool/'+name), (pack_release.ROOT/name).read_bytes())

    def test_excludes_personal_data_but_keeps_program_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            files = (
                "StellaSoraGachaTool.exe", "StellaSoraUpdater.exe",
                "_internal/assets/travelers/133.png", "_internal/catalog.json",
                "exports/accounts/100123456/100123456.json", "UID.JSON",
                "accounts.json", "ui_settings.json", "fortune.json", "100123456.json",
                "crash.log", "logs/session.log", "stellasora_gacha_archive.json",
                "account_sessions/20-1000.json", "account_sessions/20-1000.blocked",
            )
            for name in files:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            with patch.object(pack_release, "RELEASE_DIR", root / "release"):
                result = pack_release.build_zip("1.2.26", source)
            with zipfile.ZipFile(result) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "StellaSoraGachaTool/StellaSoraGachaTool.exe",
                    "StellaSoraGachaTool/StellaSoraUpdater.exe",
                    "StellaSoraGachaTool/_internal/assets/travelers/133.png",
                    "StellaSoraGachaTool/_internal/catalog.json",
                    "StellaSoraGachaTool/LICENSE",
                    "StellaSoraGachaTool/README.md",
                })
                self.assertEqual(archive.read('StellaSoraGachaTool/LICENSE'), (pack_release.ROOT/'LICENSE').read_bytes())

    def test_failed_rebuild_preserves_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "app.exe").write_bytes(b"program")
            prior = root / "StellaSoraGachaTool-1.2.25-win64.zip"
            current = root / "StellaSoraGachaTool-1.2.26-win64.zip"
            prior.write_bytes(b"prior release")
            current.write_bytes(b"current release")
            with patch.object(pack_release, "RELEASE_DIR", root), patch.object(
                zipfile.ZipFile, "write", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    pack_release.build_zip("1.2.26", source)
            self.assertEqual(prior.read_bytes(), b"prior release")
            self.assertEqual(current.read_bytes(), b"current release")
            self.assertEqual(list(root.glob("*.part")), [])

    def test_manifest_download_url_uses_distribution_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'app_update.json'
            manifest.write_text('{}', encoding='utf-8')
            pack_release.update_manifest(manifest, '1.3.0', 'StellaSoraGachaTool-1.3.0-win64.zip', 'a'*64, 'release')
            data = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual(data['url'], f'https://github.com/{GITHUB_REPOSITORY}/releases/download/v1.3.0/StellaSoraGachaTool-1.3.0-win64.zip')
            self.assertEqual(data['version'], '1.3.0')
            self.assertEqual(data['sha256'], 'a'*64)
