"""Network fixtures loaded only by the explicit E2E PYTHONPATH. Not distributed."""
import hashlib
import os
import time
import sys
from pathlib import Path

if os.environ.get('STELLA_E2E_CLOSE') == '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from stellasora_toolkit.application import Application
    def lifecycle(self, update_status):
        case = self.output/'close-case.txt'
        value = case.read_text('utf-8') if case.exists() else 'ready'
        if value == 'waiting':
            raise ValueError('后台暂未响应（验收场景）')
        return {'busy': value == 'busy', 'update': {'status': 'downloading' if value == 'update' else 'idle'}}
    Application.lifecycle = lifecycle

if os.environ.get('STELLA_E2E_EXIT_WORK') == '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from stellasora_toolkit import app_updater, archive_layout
    from stellasora_toolkit.application import Application
    from stellasora_toolkit.desktop_updates import DesktopUpdates
    check_update, download_update = DesktopUpdates.check, DesktopUpdates.download
    # Keep real dispatch and workers; stall only external work.
    def check(self, automatic=False):
        self.app.offline = False
        def network(*_args):
            (self.app.output/'network-started.txt').write_text(str(os.getpid()), encoding='utf-8')
            time.sleep(120)
        app_updater.check_for_update = network
        return check_update(self, automatic)
    def download(self):
        self.state = {'status': 'available', 'update': {
            'version': '9.9.9', 'url': 'https://example.test/update.zip', 'sha256': '0'*64}}
        def network(*_args, **_kwargs):
            (self.app.output/'network-started.txt').write_text(str(os.getpid()), encoding='utf-8')
            time.sleep(120)
        app_updater.download_update = network
        return download_update(self)
    def save(self, _pid, _progress):
        (self.output/'save-started.txt').write_text('started', encoding='utf-8')
        deadline = time.monotonic()+30
        while not (self.output/'allow-save.txt').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        archive_layout.write_atomic(self.output/'saved-before-exit.json', {'uid': '100000001'})
    DesktopUpdates.check, DesktopUpdates.download = check, download
    Application.capture = save

if os.environ.get('STELLA_E2E_UPDATES') == '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from stellasora_toolkit import app_updater
    from stellasora_toolkit.application import Application
    DATA = b'electron update workflow fixture'
    app_updater.check_for_update = lambda *_args: app_updater.AppUpdate(
        '9.9.9', 'https://example.test/update.zip', hashlib.sha256(DATA).hexdigest(),
        '改进归档保护\n更新说明可以滚动浏览\n<script>window.bad=true</script>')
    Application.sync_resources = lambda *_args: {'offlineFixture': True}
    def download(update, directory, progress=None, *, cancelled=None, metrics=None, **kwargs):
        directory.mkdir(parents=True, exist_ok=True)
        attempt = directory/'attempt.txt'
        first = not attempt.exists()
        attempt.write_text('attempted', encoding='utf-8')
        for index in range(20):
            if cancelled and cancelled(): raise app_updater.UpdateCancelled('下载已取消')
            if metrics: metrics({'phase':'downloading','received':index*100,'total':2000,'speed':500,'eta':4-index/5})
            time.sleep(.08)
        if first: raise OSError('网络中断（验收场景）')
        package = directory/'verified.zip'; package.write_bytes(DATA)
        return package
    app_updater.download_update = download

if os.environ.get('STELLA_E2E_HHMX') == '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from types import SimpleNamespace
    from stellasora_toolkit import archive_layout, service
    from stellasora_toolkit.application import Application

    def read_fixture(root, kind, rows_key, row):
        uid = '100000001'
        payload = {'version': 1, 'uid': uid, 'updatedAt': '2026-10-27T12:00:00+08:00', rows_key: [row]}
        archive_layout.write_atomic(root/f'{uid}_{kind}.json', payload)
        return payload

    Application.select_process = lambda self, pid: SimpleNamespace(pid=pid, name='xtlr.exe')
    service.read_affinity = lambda root, **kwargs: read_fixture(
        root, 'affinity', 'entries', {'id': 103, 'name': '琥珀', 'level': 10, 'exp': 12, 'need': 100})
    service.read_roster = lambda root, **kwargs: read_fixture(
        root, 'roster', 'characters', {'id': 103, 'name': '琥珀', 'level': 20})
