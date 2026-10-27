"""Persistent, cancellable update workflow without a Qt event loop."""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from . import app_updater, archive_layout
from .application import read_preferences, safe_message
from .project import GITHUB_REPOSITORY
from .constants import APP_VERSION


class DesktopUpdates:
    def __init__(self, application, app_root: Path):
        self.app = application
        self.root = Path(app_root).resolve()
        self.directory = self.app.output/'updates'
        self.receipt = self.directory/'ready.json'
        self.cancel = threading.Event()
        self.generation = 0
        self.state = {'status': 'idle', 'automatic': False}
        self._gate = threading.RLock()
        self.restore()

    def publish(self):
        self.app.emit({'type': 'event', 'name': 'update', 'payload': self.state.copy()})

    def restore(self):
        import json
        try:
            receipt = json.loads(self.receipt.read_text('utf-8'))
            update = app_updater.parse_update_manifest(receipt['update'])
            preferences = read_preferences(self.app.output)
            if receipt.get('automatic') and not preferences['auto_update']:
                return
            if receipt.get('channel', preferences['update_channel']) != preferences['update_channel']:
                return
            name = receipt['package']
            if not isinstance(name, str) or Path(name).name != name:
                return
            path = self.directory/name
            if app_updater.is_newer_version(update.version, APP_VERSION) and path.is_file() and app_updater.sha256_file(path) == update.sha256:
                self.state = {'status': 'ready', 'automatic': bool(receipt.get('automatic')), 'channel': preferences['update_channel'], 'update': asdict(update), 'package': str(path)}
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def check(self, automatic=False):
        with self._gate:
            if self.state['status'] in ('checking', 'downloading', 'verifying', 'ready'):
                self.publish()
                return self.state
            if self.app.offline:
                raise ValueError('离线模式不检查网络更新')
            if automatic and not read_preferences(self.app.output)['auto_update']:
                return self.state
            self.generation += 1
            generation = self.generation
            channel = read_preferences(self.app.output)['update_channel']
            self.state = {'status': 'checking', 'automatic': bool(automatic)}
            self.publish()

        def work(progress, _operation):
            override = os.environ.get(app_updater.UPDATE_MANIFEST_ENV_VAR, '').strip()
            name = 'app_update_beta.json' if channel == 'beta' else 'app_update_github.json'
            urls = [override or f'https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main/{name}']
            try:
                update = app_updater.check_for_update(urls, APP_VERSION)
                with self._gate:
                    if generation != self.generation:
                        return
                    self.state = {'status': 'available' if update else 'upToDate', 'automatic': bool(automatic),
                                  'update': asdict(update) if update else None, 'channel': channel}
                    self.publish()
                progress(f'发现版本 {update.version}' if update else '当前已是最新版本')
            except Exception as error:
                with self._gate:
                    if generation == self.generation:
                        self.state = {'status': 'failed', 'automatic': bool(automatic), 'error': safe_message(error), 'stage': 'check'}
                        self.publish()
                raise
        return self.app.job('检查更新', work, exclusive=False)

    def download(self):
        with self._gate:
            if self.state['status'] not in ('available', 'failed', 'cancelled') or not self.state.get('update'):
                raise ValueError('请先检查并确认可用版本')
            update = app_updater.parse_update_manifest(self.state['update'])
            automatic = self.state.get('automatic', False)
            channel = self.state.get('channel', read_preferences(self.app.output)['update_channel'])
            self.cancel = threading.Event()
            cancel = self.cancel
            self.generation += 1
            generation = self.generation
            self.state = {'status': 'downloading', 'automatic': automatic, 'channel': channel, 'update': asdict(update),
                          'received': 0, 'total': 0, 'speed': 0, 'eta': None}
            self.publish()

        def work(progress, _operation):
            def metrics(values):
                with self._gate:
                    if generation != self.generation:
                        return
                    self.state.update(values, status=values['phase'])
                    self.publish()
            try:
                package = app_updater.download_update(update, self.directory, progress=progress,
                                                     cancelled=cancel.is_set, metrics=metrics)
                with self._gate:
                    if generation != self.generation or cancel.is_set():
                        package.unlink(missing_ok=True)
                        raise app_updater.UpdateCancelled('下载已取消')
                    archive_layout.write_atomic(self.receipt, {'update': asdict(update), 'package': package.name, 'automatic': automatic, 'channel': channel})
                    self.state.update(status='ready', package=str(package), speed=0, eta=None)
                    self.publish()
                progress('更新包通过 SHA-256 校验，可以立即安装或稍后安装')
            except Exception as error:
                with self._gate:
                    if generation == self.generation:
                        self.state.update(status='cancelled' if isinstance(error, app_updater.UpdateCancelled) else 'failed',
                                          error=safe_message(error), stage='download')
                        self.publish()
                raise
        return self.app.job('下载更新', work, exclusive=False)

    def cancel_download(self):
        with self._gate:
            self.cancel.set()
            self.generation += 1
            self.state.update(status='cancelled', speed=0, eta=None)
            self.publish()
        return self.state

    def disable_automatic(self):
        with self._gate:
            if self.state.get('automatic'):
                self.cancel.set()
                self.generation += 1
                try:
                    if self.state.get('package'):
                        Path(self.state['package']).unlink(missing_ok=True)
                    self.receipt.unlink(missing_ok=True)
                except OSError:
                    pass  # The automatic flag in the receipt still prevents a future prompt.
                self.state = {'status': 'idle', 'automatic': False}
                self.publish()

    def channel_changed(self):
        with self._gate:
            self.cancel.set()
            self.generation += 1
            self.state = {'status': 'idle', 'automatic': False}
            self.restore()
            self.publish()

    def install(self, wait_pids):
        with self._gate:
            if self.app.busy or self.state['status'] != 'ready':
                raise ValueError('请等待当前操作完成，并确认更新已下载')
            package = Path(self.state['package'])
            update = app_updater.parse_update_manifest(self.state['update'])
            if not package.is_file() or app_updater.sha256_file(package) != update.sha256:
                self.state.update(status='failed', stage='download', error='更新包校验失败，请重新下载')
                self.publish()
                raise ValueError('更新包校验失败，请重新下载')
            executable = self.root/app_updater.APP_EXE_NAME
            if not getattr(sys, 'frozen', False) or not executable.is_file():
                raise ValueError('开发预览不能替换程序，请在打包版中安装更新')
            app_updater.launch_update_installer(package, executable, wait_pids=[os.getpid(), *wait_pids])
            self.state.update(status='installing')
            self.publish()
            return {'installing': True}
