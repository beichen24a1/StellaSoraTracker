"""Exercise urllib upload/update flows against a local server with synthetic records."""
import hashlib
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from stellasora_toolkit import app_updater, rem_upload


class NetworkWorkflowTests(unittest.TestCase):
    def test_upload_contract_and_verified_update_download(self):
        requests = []
        package = b'local update fixture'
        digest = hashlib.sha256(package).hexdigest()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true,"uid":"100000001"}')
            def do_GET(self):
                payload = (json.dumps({'version': '9.0.0', 'url': 'https://example.test/update.zip',
                                       'sha256': digest, 'notes': 'fixture'}).encode()
                           if self.path == '/manifest.json' else package)
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        base = f'http://127.0.0.1:{server.server_port}'
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = {'version': 1, 'uid': '100000001', 'categories': {
                    '1': [{'Gid': 10162, 'Time': 100, 'Ids': [162]}]}}
                archive = root / '100000001.json'
                archive.write_text(json.dumps(record))
                result = rem_upload.upload_file(archive, endpoint=base + '/upload')
                self.assertEqual(result.bind_command, '星塔抽卡绑定 UID 100000001')
                self.assertEqual(requests, [{'uid': '100000001', 'record': record}])
                update = app_updater.check_for_update(base + '/manifest.json', '1.0.0')
                # Production manifests require HTTPS. Route the verified fixture URL
                # to our local HTTP server solely for this transport test.
                update = replace(update, url=base + '/update.zip')
                downloaded = app_updater.download_update(update, root / 'updates')
                self.assertEqual(downloaded.read_bytes(), package)
                wrong = app_updater.AppUpdate('9.0.0', base + '/update.zip', '0' * 64, '')
                with self.assertRaises(ValueError):
                    app_updater.download_update(wrong, root / 'bad-updates', retries=1)
                self.assertEqual(list((root / 'bad-updates').iterdir()), [])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
