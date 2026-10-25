"""Regressions for the five issues reproduced in the repository audit."""
import json
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import accounts, archive_layout, catalog, catalog_sync, official_banners, server_config, service
from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.storage_lock import storage_transaction

UID = '100000001'


def group(timestamp=100, gid=1001, item=162):
    return {'Gid': gid, 'Time': timestamp, 'Ids': [item]}


def hold_storage(root, ready, release):
    with storage_transaction(Path(root)):
        ready.set()
        release.wait(15)


def concurrent_import(root, source, start, result):
    start.wait(15)
    original = service.read_owned_archive
    first = True

    def slow_read(directory, uid):
        nonlocal first
        payload = original(directory, uid)
        if first:
            first = False
            time.sleep(0.1)  # Widen the read/write race; the transaction must still serialize it.
        return payload

    try:
        with patch.object(service, 'read_owned_archive', side_effect=slow_read):
            imported = service.import_gacha_file(Path(root), Path(source))
        result.put(('ok', imported.added_groups))
    except Exception as error:
        result.put(('error', str(error)))


class ArchiveSafetyRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.account = accounts.create(self.root, uid=UID)
        self.directory = accounts.data_dir(self.root, self.account.key)
        service._write_archive(self.directory, {6: [group()]}, uid=UID)
        self.primary = self.root/f'{UID}.json'

    def test_malformed_categories_never_get_silently_dropped_after_migration(self):
        source = self.root/'incoming.json'
        source.write_text(json.dumps({'uid': UID, 'categories': {'6': [group(200)]}}), encoding='utf-8')
        for categories in ({'6': [group()], '4': {'old': [group(150)]}},
                           {'6': [group()], '5': []}, [], None):
            with self.subTest(categories=categories):
                self.primary.write_text(json.dumps({'version': 1, 'uid': UID, 'categories': categories}), encoding='utf-8')
                before = self.primary.read_bytes()
                self.assertTrue(archive_layout.migrated(self.directory, UID))
                with self.assertRaises(AccountSafetyError):
                    service.import_gacha_file(self.root, source)
                self.assertEqual(self.primary.read_bytes(), before)

    def test_simultaneous_process_imports_preserve_both_batches(self):
        ctx = multiprocessing.get_context('spawn')
        start, result = ctx.Event(), ctx.Queue()
        processes = []
        try:
            for timestamp in (200, 300):
                source = self.root/f'incoming-{timestamp}.json'
                source.write_text(json.dumps({'uid': UID, 'categories': {'6': [group(timestamp)]}}), encoding='utf-8')
                process = ctx.Process(target=concurrent_import, args=(str(self.root), str(source), start, result))
                process.start()
                processes.append(process)
            start.set()
            replies = [result.get(timeout=20) for _ in processes]
            self.assertEqual(sorted(replies), [('ok', 1), ('ok', 1)])
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual([g['Time'] for g in service.load_archive_categories(self.root)[6]], [100, 200, 300])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(5)
            result.close()

    def test_lock_timeout_is_cross_process_and_does_not_affect_other_directories(self):
        ctx = multiprocessing.get_context('spawn')
        ready, release = ctx.Event(), ctx.Event()
        process = ctx.Process(target=hold_storage, args=(str(self.root), ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            with self.assertRaises(OSError):
                with storage_transaction(self.root, timeout=0.05):
                    self.fail('A second process acquired the held directory')
            with storage_transaction(self.root/'independent', timeout=0.05):
                pass
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
        with storage_transaction(self.root, timeout=0.1):
            # Nested helpers use account directories but share the same root lock.
            with storage_transaction(self.directory, timeout=0.1):
                pass

    def test_process_exit_releases_the_lock(self):
        ctx = multiprocessing.get_context('spawn')
        ready, release = ctx.Event(), ctx.Event()
        process = ctx.Process(target=hold_storage, args=(str(self.root), ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
        finally:
            process.terminate()
            process.join(10)
        with storage_transaction(self.root, timeout=0.2):
            pass

    def test_keyword_api_calls_still_use_the_transaction(self):
        source = self.root/'incoming.json'
        source.write_text(json.dumps({'uid': UID, 'categories': {'6': [group(200)]}}), encoding='utf-8')
        result = service.import_gacha_file(output_dir=self.root, source=source)
        self.assertEqual(result.added_groups, 1)
        self.assertEqual(accounts.active_account(self.root).uid, UID)

    def test_failed_transaction_releases_the_lock(self):
        with self.assertRaises(ValueError):
            with storage_transaction(self.root):
                raise ValueError('fixture failure')
        with storage_transaction(self.root, timeout=0.1):
            pass


class CatalogRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = server_config.active().key
        self.addCleanup(server_config.set_active, self.profile)
        for table in (catalog.TRAVELER_NAMES, catalog.DISC_NAMES, catalog.FIVE_STAR_DISCS):
            saved = table.copy()
            self.addCleanup(lambda table=table, saved=saved: (table.clear(), table.update(saved)))
        for table in (catalog.FIVE_STAR_TRAVELERS, catalog.FIVE_STAR_ITEMS):
            saved = table.copy()
            self.addCleanup(lambda table=table, saved=saved: (table.clear(), table.update(saved)))
        for name, options in (
            ('missing_icon_targets', {'return_value': []}),
            ('_download_icon', {'return_value': False}),
            ('asset_root', {'return_value': self.root/'images'}),
        ):
            patcher = patch.object(catalog_sync, name, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_switch_server_fetches_correct_language_and_keeps_both_caches(self):
        state = self.root/'catalog_sync_state.json'
        def item(name):
            return {'id': 103, 'kind': 'traveler', 'name': name, 'rarity': 4, 'five_star': False, 'icon': ''}
        server_config.set_active('cn')
        cn_cache = catalog_sync._catalog_cache_path(state)
        catalog_sync._save_catalog_cache(cn_cache, [item('中文名字')])
        server_config.set_active('jp')
        jp_cache = catalog_sync._catalog_cache_path(state)
        with patch.object(catalog_sync, '_fetch_five_star_catalog', return_value=[item('日本語の名前')]) as fetch:
            catalog_sync._sync_once(state, None)
        fetch.assert_called_once()
        self.assertNotEqual(cn_cache, jp_cache)
        self.assertEqual(catalog.gacha_item_name(103), '日本語の名前')
        self.assertTrue(cn_cache.is_file() and jp_cache.is_file())
        server_config.set_active('cn')
        with patch.object(catalog_sync, '_fetch_five_star_catalog') as fetch:
            catalog_sync._sync_once(state, None)
        fetch.assert_not_called()
        self.assertEqual(catalog.gacha_item_name(103), '中文名字')

    def test_disc_up_fallback_does_not_register_a_traveler(self):
        with patch.object(catalog_sync, '_fetch_five_star_catalog', return_value=[]), \
             patch.object(official_banners, 'fetch_banners', return_value={}), \
             patch.object(official_banners, 'rate_up_entries', return_value=[
                 {'id': 162, 'name': '旅人', 'rarity': 5},
                 {'id': 214066, 'name': '秘纹', 'rarity': 5}]), \
             patch.object(catalog_sync, 'fetch_failures', return_value=2):
            report = catalog_sync._sync_once(self.root/'state.json', None)
        self.assertEqual(catalog.gacha_item_kind(214066), 'disc')
        self.assertNotIn(214066, catalog.TRAVELER_NAMES)
        self.assertEqual(report['audit_after']['clash'], [])
        self.assertIn(162, catalog.TRAVELER_NAMES)


class ResultLabelRegressions(unittest.TestCase):
    def test_only_limited_pools_with_up_metadata_get_up_or_off_banner(self):
        from PySide6.QtWidgets import QApplication, QTableWidget
        from stellasora_toolkit.ui.window import StellaSoraApp
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            window = StellaSoraApp(Path(directory), demo=True, online_sync=False)
            window.records.all_pulls = True
            window.records.current = 'all'
            metadata = {
                1001: ('周年特选', '', '', ''), 1: ('常驻', '', '', ''),
                10162: ('旅人限时', '', '', catalog.gacha_item_name(162)),
                20162: ('秘纹限时', '', '', catalog.gacha_item_name(214066)),
            }
            with patch('stellasora_toolkit.ui.beta_views.official_pool_info', side_effect=metadata.get):
                window.records.render([group(100, gid=1001), group(200, gid=1),
                                       group(300, gid=10162), group(400, gid=20162, item=214015)])
            table = window.records.findChild(QTableWidget)
            results = {table.item(row, 3).text(): table.item(row, 4).text() for row in range(table.rowCount())}
            self.assertEqual(results, {'周年特选': '—', '常驻': '—', '旅人限时': 'UP', '秘纹限时': '歪'})
            window.close()
            window.deleteLater()
            app.processEvents()
