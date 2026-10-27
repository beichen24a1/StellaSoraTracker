import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import app_updater


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
