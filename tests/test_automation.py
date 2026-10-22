import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from stellasora_toolkit import app_updater, rem_upload, service
from stellasora_toolkit.ui.automation import UpdateReply
from stellasora_toolkit.ui.preferences import load_automation, load_theme, save_theme, save_automation
from stellasora_toolkit.ui.window import StellaSoraApp


class AutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.window = StellaSoraApp(self.root / 'exports', online_sync=False)

    def tearDown(self):
        self.window._set_busy(False)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def wait(self, predicate):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail('Background operation did not complete')

    def source(self, uid='100000001', time=100):
        path = self.root / f'{uid}.json'
        path.write_text(json.dumps({'uid': uid, 'categories': {
            '1': [{'Gid': 10162, 'Time': time, 'Ids': [162, 107]}], '2': [], '3': [], '4': []
        }}), encoding='utf-8')
        return path

    def enable_upload(self):
        self.window.online_sync = True
        self.window.automation_checks['auto_upload'].click()

    def successful_upload(self, path, **kwargs):
        return rem_upload.RemUploadResult(200, {'ok': True}, path.stem)

    def test_switches_persist_independently_of_theme_and_accounts(self):
        output = self.window.output
        self.assertEqual(load_automation(output), {'auto_upload': False, 'auto_update': True})
        self.window.automation_checks['auto_upload'].click()
        self.window.automation_checks['auto_update'].click()
        self.window.change_variant('sky')
        self.assertEqual(load_theme(output), 'sky')
        self.assertEqual(load_automation(output), {'auto_upload': True, 'auto_update': False})
        restarted = StellaSoraApp(output, online_sync=False)
        try:
            self.assertTrue(restarted.automation_checks['auto_upload'].isChecked())
            self.assertFalse(restarted.automation_checks['auto_update'].isChecked())
        finally:
            restarted.close()

    def test_invalid_preferences_default_and_save_failure_rolls_back_switch(self):
        (self.window.output / 'ui_settings.json').write_text(
            '{"auto_upload":"true","auto_update":0}', encoding='utf-8')
        self.assertEqual(load_automation(self.window.output), {'auto_upload': False, 'auto_update': True})
        with patch('stellasora_toolkit.ui.automation.save_automation', return_value=False):
            self.window.automation_checks['auto_upload'].click()
        self.assertFalse(self.window.automation['auto_upload'])
        self.assertFalse(self.window.automation_checks['auto_upload'].isChecked())

    def test_import_uploads_matching_uid_once_and_new_records_upload_again(self):
        self.enable_upload()
        with patch('stellasora_toolkit.rem_upload.upload_file', side_effect=self.successful_upload) as upload:
            self.window._import_paths([self.source()])
            self.wait(lambda: upload.call_count == 1 and not self.window._busy)
            path = upload.call_args.args[0]
            self.assertEqual(json.loads(path.read_text())['uid'], path.stem)
            self.assertEqual(upload.call_args.kwargs['endpoint'], rem_upload.UPLOAD_URL)
            self.window._import_paths([self.source()])
            self.window._run_pending_upload()
            self.assertEqual(upload.call_count, 1)
            self.window._import_paths([self.source(time=200)])
            self.wait(lambda: upload.call_count == 2 and not self.window._busy)
            self.assertIn('绑定指令', self.window._account._state.text())

    def test_capture_upload_waits_for_busy_and_failed_capture_never_uploads(self):
        self.window._import_paths([self.source()])
        snapshot = service.load_latest_snapshot(self.window.output)
        path = service.refresh_share_file(self.window.output)
        snapshot = service.Snapshot(snapshot.gacha, uid=path.stem, share_file=path)
        self.enable_upload()
        with patch('stellasora_toolkit.rem_upload.upload_file', side_effect=self.successful_upload) as upload:
            self.window._on_snapshot(snapshot)
            self.window._set_busy(True)  # catalog synchronization still running
            self.window._run_pending_upload()
            upload.assert_not_called()
            self.window._set_busy(False)
            self.window._run_pending_upload()
            self.wait(lambda: not self.window._busy)
            self.assertEqual(upload.call_count, 1)
            with patch('stellasora_toolkit.ui.controller.QMessageBox.critical'):
                self.window._on_read_error('UID could not be verified')
            self.assertFalse(self.window._pending_uploads)
            self.assertEqual(upload.call_count, 1)

    def test_multi_account_import_uploads_each_accounts_own_archive(self):
        self.enable_upload()
        with patch('stellasora_toolkit.rem_upload.upload_file', side_effect=self.successful_upload) as upload:
            self.window._import_paths([self.source('100000001'), self.source('100000002', time=200)])
            self.wait(lambda: upload.call_count == 2 and not self.window._busy)
            self.assertEqual({call.args[0].stem for call in upload.call_args_list}, {'100000001','100000002'})
            for call in upload.call_args_list:
                self.assertEqual(json.loads(call.args[0].read_text())['uid'], call.args[0].stem)

    def test_off_clears_queue_and_manual_upload_still_works(self):
        self.enable_upload()
        with patch('stellasora_toolkit.rem_upload.upload_file', side_effect=self.successful_upload) as upload:
            self.window._import_paths([self.source()])
            self.window.automation_checks['auto_upload'].click()
            self.window._run_pending_upload()
            upload.assert_not_called()
            self.window._account._upload_btn.click()
            self.wait(lambda: upload.call_count == 1 and not self.window._busy)

    def test_failed_upload_preserves_archive_and_does_not_mark_success(self):
        self.enable_upload()
        with patch('stellasora_toolkit.rem_upload.upload_file', side_effect=rem_upload.RemUploadError('429')) as upload:
            self.window._import_paths([self.source()])
            self.wait(lambda: upload.called and not self.window._busy)
        path = service.refresh_share_file(self.window.output)
        self.assertEqual(len(json.loads(path.read_text())['categories']['1']), 1)
        self.assertFalse((path.parent / rem_upload.STATE_FILENAME).exists())

    def test_automatic_update_downloads_then_defers_install_during_capture(self):
        update = app_updater.AppUpdate('9.0.0', 'https://example.test/update.zip', '0' * 64, 'test')
        package = self.root / 'verified.zip'
        package.write_bytes(b'fixture')
        self.window.online_sync = True
        with patch('sys.frozen', True, create=True), \
             patch('stellasora_toolkit.app_updater.check_for_update', return_value=update) as check, \
             patch('stellasora_toolkit.app_updater.download_update', return_value=package) as download, \
             patch('stellasora_toolkit.app_updater.launch_update_installer') as install, \
             patch('stellasora_toolkit.ui.automation.QMessageBox.question', return_value=QMessageBox.No) as question:
            self.window._automatic_update()
            self.wait(lambda: self.window._update_state == 'ready')
            self.assertEqual(check.call_count, 1)
            self.assertEqual(download.call_count, 1)
            self.window._set_busy(True)
            self.window._offer_update()
            question.assert_not_called()
            install.assert_not_called()
            self.window._set_busy(False)
            self.window._offer_update()
            self.assertEqual(question.call_count, 1)
            install.assert_not_called()
            self.window._restart_for_update()
            install.assert_called_once()

    def test_disabling_auto_update_ignores_stale_check_and_keeps_manual_check(self):
        update = app_updater.AppUpdate('9.0.0', 'https://example.test/update.zip', '0' * 64, '')
        self.window._update_automatic = True
        old_generation = self.window._update_generation
        self.window.automation_checks['auto_update'].click()
        with patch('stellasora_toolkit.app_updater.download_update') as download:
            self.window._update_checked(UpdateReply(update, True, old_generation))
            download.assert_not_called()
        with patch('stellasora_toolkit.app_updater.check_for_update', return_value=None) as check:
            self.window._check_update()
            self.wait(lambda: self.window._update_state == 'idle')
            check.assert_called_once()

    def test_auto_update_off_cancels_download_and_removes_stale_package(self):
        package = self.root / 'stale.zip'
        package.write_bytes(b'fixture')
        self.window._update_automatic = True
        generation = self.window._update_generation
        self.window.automation_checks['auto_update'].click()
        self.assertTrue(self.window._update_cancel.is_set())
        self.window._install_update(UpdateReply(package, True, generation))
        self.assertFalse(package.exists())
        self.assertIsNone(self.window._ready_update)

    def test_demo_and_offline_testing_never_schedule_network(self):
        self.assertFalse(self.window._update_timer.isActive())
        demo = StellaSoraApp(self.root / 'demo', demo=True)
        try:
            self.assertFalse(demo._update_timer.isActive())
            self.assertTrue(all(not checkbox.isEnabled() for checkbox in demo.automation_checks.values()))
            demo._queue_auto_upload(self.source())
            self.assertFalse(demo._pending_uploads)
        finally:
            demo.close()


class DownloadCancellationTests(unittest.TestCase):
    def test_cancel_during_stream_removes_partial_file_without_retry(self):
        update = app_updater.AppUpdate('9.0.0', 'https://example.test/update.zip', '0' * 64, '')
        cancelled = threading.Event()
        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                cancelled.set()
                return b'chunk'
        with tempfile.TemporaryDirectory() as directory, \
             patch('stellasora_toolkit.app_updater.urlopen', return_value=Response()) as request:
            with self.assertRaises(app_updater.UpdateCancelled):
                app_updater.download_update(update, Path(directory), cancelled=cancelled.is_set)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])
