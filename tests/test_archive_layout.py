import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import accounts, archive_layout, service, rem_upload
from stellasora_toolkit.account_guard import AccountSafetyError, check_account_records

UID = '100000001'
OTHER = '100000002'


def group(time=100):
    return {'Gid': 1001, 'Time': time, 'Ids': [162], 'NextPackage': ''}


def payload(uid=UID, times=(100,)):
    return {'version': 1, 'uid': uid, 'categories': {'6': [group(t) for t in times]}}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class FlatArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def legacy_account(self, uid=UID):
        account = accounts.create(self.root, uid=uid)
        directory = accounts.data_dir(self.root, account.key)
        save(directory / service.ARCHIVE_FILENAME, payload(uid))
        return account, directory

    def test_opens_multiple_b_archives_and_remembers_selection(self):
        save(self.root / f'{UID}.json', payload())
        save(self.root / f'{OTHER}.json', payload(OTHER, (200,)))
        os.utime(self.root / f'{UID}.json', (100, 100))
        os.utime(self.root / f'{OTHER}.json', (200, 200))
        state = accounts.ensure_ready(self.root)
        self.assertEqual({a.uid for a in state.accounts}, {UID, OTHER})
        self.assertEqual(state.active_account.uid, OTHER)
        accounts.switch(self.root, UID)
        self.assertEqual(accounts.load_state(self.root).active_account.uid, UID)
        self.assertEqual(service.load_latest_snapshot(self.root).gacha, [group()])

    def test_migration_merges_all_sources_once_and_preserves_original_bytes(self):
        _, directory = self.legacy_account()
        legacy = directory / service.ARCHIVE_FILENAME
        share = directory / f'{UID}.json'
        save(share, payload(times=(100, 200)))
        flat = self.root / f'{UID}.json'
        save(flat, payload(times=(300,)))
        original = {p: p.read_bytes() for p in (legacy, share, flat)}
        expected = [group(t) for t in (100, 200, 300)]
        self.assertEqual(service.load_archive_categories(self.root), {6: expected})
        self.assertEqual(legacy.read_bytes(), original[legacy])
        self.assertEqual(share.read_bytes(), original[share])
        self.assertEqual((directory / f'pre_migration_{UID}.json').read_bytes(), original[flat])
        # The preserved old archive must never be treated as current data again.
        legacy.write_bytes(b'{old broken backup')
        save(flat, payload(times=(400,)))
        self.assertEqual(service.load_archive_categories(self.root), {6: [group(400)]})
        check_account_records(self.root, OTHER, {'6': [group(500)]})

    def test_new_import_writes_only_the_flat_primary_and_keeps_uid_config_private(self):
        source = self.root / 'incoming.json'
        save(source, payload())
        result = service.import_gacha_file(self.root, source)
        self.assertEqual(result.share_file, self.root / f'{UID}.json')
        self.assertEqual(service.active_archive_path(self.root), result.share_file)
        directory = accounts.active_data_dir(self.root)
        self.assertFalse((directory / service.ARCHIVE_FILENAME).exists())
        self.assertFalse((directory / f'{UID}.json').exists())
        service.save_uid_field(directory, '_uid')
        self.assertTrue((directory / 'uid.json').is_file())
        self.assertFalse((self.root / 'uid.json').exists())

    def test_wrong_owner_or_damaged_source_cannot_replace_flat_archive(self):
        _, directory = self.legacy_account()
        flat = self.root / f'{UID}.json'
        save(flat, payload(times=(200,)))
        before = flat.read_bytes()
        for data in (b'{broken', json.dumps(payload(OTHER)).encode(),
                     json.dumps({'categories': {'6': [group()]}}).encode()):
            (directory / service.ARCHIVE_FILENAME).write_bytes(data)
            with self.assertRaises(AccountSafetyError):
                service.read_owned_archive(directory, UID)
            self.assertEqual(flat.read_bytes(), before)
            self.assertFalse((directory / archive_layout.RECEIPT_NAME).exists())

    def test_bad_flat_archive_blocks_migration_without_touching_source(self):
        _, directory = self.legacy_account()
        flat = self.root / f'{UID}.json'
        flat.write_bytes(b'{broken')
        legacy = (directory / service.ARCHIVE_FILENAME).read_bytes()
        with self.assertRaises(AccountSafetyError):
            service.read_owned_archive(directory, UID)
        self.assertEqual(flat.read_bytes(), b'{broken')
        self.assertEqual((directory / service.ARCHIVE_FILENAME).read_bytes(), legacy)

    def test_missing_migrated_primary_does_not_resurrect_preserved_old_records(self):
        _, directory = self.legacy_account()
        path = archive_layout.ensure_archive(directory)
        path.unlink()
        with self.assertRaises(AccountSafetyError):
            service.read_owned_archive(directory, UID)
        self.assertFalse(path.exists())

    def test_failed_receipt_can_retry_without_losing_or_duplicating_records(self):
        _, directory = self.legacy_account()
        original = archive_layout.write_atomic

        def fail_receipt(path, value):
            if path.name == archive_layout.RECEIPT_NAME:
                raise OSError('fixture: disk full')
            original(path, value)

        with patch.object(archive_layout, 'write_atomic', side_effect=fail_receipt):
            with self.assertRaises(AccountSafetyError):
                archive_layout.ensure_archive(directory)
        self.assertFalse(archive_layout.migrated(directory, UID))
        self.assertEqual(service.load_archive_categories(self.root), {6: [group()]})
        self.assertTrue(archive_layout.migrated(directory, UID))

    def test_removal_preserves_primary_and_does_not_rediscover_removed_account(self):
        account, directory = self.legacy_account()
        path = archive_layout.ensure_archive(directory)
        before = path.read_bytes()
        self.assertTrue(accounts.remove(self.root, account.key))
        self.assertFalse(path.exists())
        self.assertNotIn(UID, {a.uid for a in accounts.load_state(self.root).accounts})
        kept = list((self.root / 'accounts').glob(f'{account.key}.deleted_*'))
        self.assertEqual((kept[0] / f'removed_{UID}.json').read_bytes(), before)

    def test_failed_removal_rolls_back_primary_and_directory(self):
        account, directory = self.legacy_account()
        path = archive_layout.ensure_archive(directory)
        before = path.read_bytes()
        with patch.object(accounts, 'save_state', return_value=False):
            self.assertFalse(accounts.remove(self.root, account.key))
        self.assertTrue(directory.is_dir())
        self.assertEqual(path.read_bytes(), before)
        self.assertIn(account.key, {a.key for a in accounts.load_state(self.root).accounts})

    def test_same_uid_duplicate_account_removal_keeps_shared_primary(self):
        first, directory = self.legacy_account()
        second = accounts.Account('duplicate', UID)
        accounts.save_state(self.root, accounts.AccountState((first, second), first.key))
        save(accounts.data_dir(self.root, second.key) / service.ARCHIVE_FILENAME, payload(times=(200,)))
        archive_layout.ensure_archive(directory)
        self.assertTrue(accounts.remove(self.root, second.key))
        self.assertEqual(service.load_archive_categories(self.root), {6: [group(), group(200)]})

    def test_legacy_upload_receipts_survive_the_archive_move(self):
        _, directory = self.legacy_account()
        save(directory / rem_upload.STATE_FILENAME, {
            'uploadedUids': [UID], 'fingerprints': {rem_upload.UPLOAD_URL: 'hash-a'}})
        path = archive_layout.ensure_archive(directory)
        self.assertTrue(rem_upload.was_uploaded(path, 'hash-a', rem_upload.UPLOAD_URL))
        self.assertFalse(rem_upload.mark_uploaded(path.parent, UID, fingerprint='hash-b'))
        self.assertTrue(rem_upload.was_uploaded(path, 'hash-b', rem_upload.UPLOAD_URL))
        self.assertFalse(rem_upload.was_uploaded(path, 'hash-a', rem_upload.UPLOAD_URL))

    def test_upload_hashes_for_two_uid_files_at_root_never_overwrite_each_other(self):
        for uid in (UID, OTHER):
            rem_upload.mark_uploaded(self.root, uid, fingerprint=f'hash-{uid}')
        for uid in (UID, OTHER):
            self.assertTrue(rem_upload.was_uploaded(self.root / f'{uid}.json', f'hash-{uid}', rem_upload.UPLOAD_URL))
            self.assertFalse(rem_upload.was_uploaded(self.root / f'{uid}.json', 'other-hash', rem_upload.UPLOAD_URL))


if __name__ == '__main__':
    unittest.main()
