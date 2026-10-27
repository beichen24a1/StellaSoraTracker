"""JSON Lines entrypoint. stdout is protocol-only; diagnostics go to stderr."""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from . import server_config, service
from .application import Application, safe_message
from .desktop_updates import DesktopUpdates
from .process import find_game_processes

METHODS = frozenset({
    'app.state', 'app.lifecycle', 'app.shutdown', 'records.query', 'records.capture', 'records.import', 'records.export', 'records.share',
    'affinity.read', 'affinity.load',
    'accounts.create', 'accounts.switch', 'accounts.rename', 'accounts.remove', 'accounts.merge',
    'uid.save', 'uid.read', 'processes.list', 'server.save', 'preferences.save', 'archive.backup',
    'resources.sync', 'upload.send', 'updates.check', 'updates.download', 'updates.cancel', 'updates.install',
})

class Engine:
    def __init__(self, output: Path, app_root: Path, emit, *, offline=False):
        self.app = Application(output, emit, offline=offline)
        self.updates = DesktopUpdates(self.app, app_root)
        self.stopping = False

    def dispatch(self, method: str, params: dict):
        if method not in METHODS or not isinstance(params, dict):
            raise ValueError('不支持的请求')
        app = self.app
        if method == 'app.state':
            return {**app.state(), 'update': self.updates.state, 'packaged': bool(getattr(sys, 'frozen', False))}
        if method == 'app.lifecycle':
            return {'busy': app.busy, 'update': {'status': self.updates.state['status']}}
        if method == 'app.shutdown':
            if app.busy:
                raise ValueError('正在保存数据，请稍后关闭')
            self.updates.cancel.set()
            deadline = __import__('time').monotonic()+35
            for worker in list(app._threads):
                if worker.name in ('stella-下载更新', 'stella-检查更新'):
                    worker.join(max(0, deadline-__import__('time').monotonic()))
            if any(worker.is_alive() and worker.name in ('stella-下载更新', 'stella-检查更新') for worker in list(app._threads)):
                raise ValueError('正在停止网络请求，请稍后关闭')
            self.stopping = True
            return {'ok': True}
        if method == 'records.query':
            return app.query_records(params)
        if method == 'processes.list':
            return [asdict(process) for process in find_game_processes()]
        if method == 'preferences.save':
            if 'update_channel' in params and self.updates.state['status'] in ('downloading', 'verifying', 'installing'):
                raise ValueError('请先取消当前更新，再切换渠道')
            result = app.save_preferences(params)
            if 'update_channel' in params:
                self.updates.channel_changed()
            if params.get('auto_update') is False:
                self.updates.disable_automatic()
            return result
        if method == 'updates.check':
            return self.updates.check(params.get('automatic') is True)
        if method == 'updates.download':
            return self.updates.download()
        if method == 'updates.cancel':
            return self.updates.cancel_download()
        if method == 'updates.install':
            pids = params.get('waitPids', [])
            if not isinstance(pids, list) or any(type(pid) is not int or pid <= 0 for pid in pids):
                raise ValueError('更新进程标识无效')
            return self.updates.install(pids)
        if method == 'server.save':
            if app.busy:
                raise ValueError('请等待当前操作完成')
            key = params.get('key')
            if not server_config.set_active(key):
                raise ValueError('服务器无效')
            if not server_config.save_key(server_config.config_path(app.output), key, manual=params.get('manual', True) is True):
                raise OSError('服务器设置保存失败')
            app.invalidate()
            return app.job('同步资源', lambda progress, _id: app.sync_resources(progress))
        if method.startswith('accounts.'):
            return app.job('账号操作', lambda _progress, _id: app.account_action(method.split('.')[1], params))
        if method == 'uid.save':
            return app.job('保存 UID', lambda _progress, _id: app.save_uid(params.get('uid', '')))
        if method == 'uid.read':
            return app.job('读取游戏 UID', lambda progress, _id: app.read_game_uid(params.get('pid'), progress))
        if method == 'records.capture':
            return app.job('抓取抽卡记录', lambda progress, _id: app.capture(params.get('pid'), progress))
        if method == 'affinity.read':
            # 只读内存, 不与抓取/上传互斥(不写抽卡归档)
            return app.job('读取好感度', lambda progress, _id: app.read_affinity(params.get('pid'), progress), exclusive=False)
        if method == 'affinity.load':
            return app.load_affinity()
        if method == 'records.import':
            paths = params.get('paths')
            if not isinstance(paths, list) or not paths or len(paths) > 100 or any(not isinstance(p, str) or Path(p).suffix.lower() not in ('.json', '.csv') for p in paths):
                raise ValueError('请选择 JSON / CSV 文件')
            return app.job('导入记录', lambda progress, _id: app.import_files(paths, progress))
        if method == 'records.export':
            directory = params.get('directory')
            if not isinstance(directory, str) or not Path(directory).is_dir():
                raise ValueError('导出目录无效')
            return app.job('导出记录', lambda progress, _id: app.export_records(directory, progress))
        if method == 'records.share':
            return app.job('导出分享文件', lambda progress, _id: self._share(params.get('uid', ''), progress))
        if method == 'archive.backup':
            return app.job('创建备份', lambda _progress, _id: self._backup())
        if method == 'resources.sync':
            return app.job('同步资源', lambda progress, _id: app.sync_resources(progress), exclusive=params.get('background') is not True)
        if method == 'upload.send':
            uid = params.get('uid') or service.effective_uid(app.output)
            return app.job('上传记录', lambda progress, _id: app.upload(uid, progress))
        raise ValueError('不支持的请求')

    def _share(self, uid, progress):
        path = service.export_share_for_uid(self.app.output, uid)
        progress(f'已导出 {path.name}')
        return {'path': str(path)}

    def _backup(self):
        path = self.app.backup()
        if path is None:
            raise ValueError('尚未找到本地招募归档，请先抓取或导入记录')
        return {'path': path}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    if args.assets:
        os.environ['SSTEMU_ASSETS_DIR'] = str(args.assets.resolve())
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    protocol = sys.stdout
    output_lock = threading.Lock()
    def emit(value):
        with output_lock:
            protocol.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')
            protocol.flush()
    sys.stdout = sys.stderr
    engine = Engine(args.output, args.app_root, emit, offline=args.offline)
    emit({'type': 'event', 'name': 'ready', 'payload': {'protocolVersion': 1}})
    for line in sys.stdin:
        request = None
        try:
            if len(line) > 1024*1024:
                raise ValueError('请求过大')
            request = json.loads(line)
            if not isinstance(request, dict) or not isinstance(request.get('id'), (str, int)):
                raise ValueError('请求编号无效')
            result = engine.dispatch(request.get('method'), request.get('params', {}))
            emit({'id': request['id'], 'result': result})
        except Exception as error:
            emit({'id': request.get('id') if isinstance(request, dict) else None,
                  'error': {'code': type(error).__name__, 'message': safe_message(error)}})
        if engine.stopping:
            break
    engine.updates.cancel.set()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
