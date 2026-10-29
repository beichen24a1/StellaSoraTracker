import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import failure_window, update_installer


class FailureWindowTests(unittest.TestCase):
    def test_theme_mapping_and_invalid_settings_preserve_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ui_settings.json'
            for value, expected in [({'color_mode': 'dark'}, '10151c'), ({'theme': 'orbit'}, '10151c'),
                                    ({'color_mode': 'light', 'theme': 'orbit'}, 'f2f7fb'), ({}, 'f2f7fb')]:
                path.write_text(json.dumps(value), encoding='utf-8')
                original = path.read_bytes()
                self.assertEqual(failure_window.presentation('error', path)[1]['bg'], expected)
                self.assertEqual(path.read_bytes(), original)
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(failure_window.presentation('error', path)[1]['bg'], 'f2f7fb')

    def test_error_details_are_bounded_and_do_not_expose_service_credentials(self):
        text, _colors = failure_window.presentation('失败 https://user:secret@example.test/private\n'+'x'*20000)
        self.assertNotIn('secret', text)
        self.assertIn('[服务地址]', text)
        self.assertEqual(len(text), 16000)

    def test_display_failure_is_logged_without_masking_original_update_error(self):
        with patch.object(failure_window, 'show_failure', side_effect=OSError('window unavailable')), patch.object(update_installer, 'log') as log:
            update_installer.show_error('original failure')
            log.assert_called_once()
            self.assertIn('无法显示故障详情窗口', log.call_args.args[0])
