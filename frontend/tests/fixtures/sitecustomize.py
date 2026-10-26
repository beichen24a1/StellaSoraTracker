"""Network fixtures loaded only by the explicit E2E PYTHONPATH. Not distributed."""
import hashlib
import os
import time
import sys
from pathlib import Path

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
