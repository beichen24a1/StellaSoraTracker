"""Qt-independent application workflows used by the Electron JSONL engine."""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import accounts, archive_layout, catalog_sync, official_banners, rem_upload, server_config, service
from .catalog import gacha_item_kind, gacha_item_name, is_five_star_item, same_item_name
from .exporter import export_all, parse_import_text
from .gacha_display import SparkReward, insert_spark_rewards
from .gacha_stats import build_banner_stats_with_shared_pity
from .presentation import activity_pools, categories, overview
from .process import find_game_processes
from .storage_lock import storage_transaction
from .constants import APP_VERSION, GACHA_CATEGORY_NAMES, GACHA_CATEGORY_ORDER, GACHA_CATEGORY_PITY_LIMITS

MANUAL_UPLOAD_URL = 'https://share.fnnas.net/s/8b355174d383436899'
LIMITED = ('traveler_limited', 'disc_limited')


def safe_message(value: object) -> str:
    if re.search(r'[\"\'](?:categories|Ids|groups)[\"\']\s*:', str(value), re.I):
        return '操作未完成；错误详情包含归档内容，已隐藏。请核对文件格式与账号归属。'
    text = re.sub(r'https?://[^\s<>"\)]+', '[服务地址]', str(value))
    text = re.sub(r'(?i)(authorization|cookie|token|密码)\s*[:=]\s*\S+', r'\1=[已隐藏]', text)
    return text[:2000]


def read_preferences(output: Path) -> dict:
    try:
        data = json.loads((output/'ui_settings.json').read_text('utf-8'))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    mode = data.get('color_mode')
    if mode not in ('light', 'dark'):
        mode = 'dark' if data.get('theme') == 'orbit' else 'light'
    return {**data, 'color_mode': mode,
            'auto_upload': data.get('auto_upload') if type(data.get('auto_upload')) is bool else False,
            'auto_update': data.get('auto_update') if type(data.get('auto_update')) is bool else True,
            'update_channel': data.get('update_channel') if data.get('update_channel') in ('stable', 'beta') else 'beta',
            'pool_columns': data.get('pool_columns') if type(data.get('pool_columns')) is int and data['pool_columns'] in (1, 2) else None}


class Application:
    def __init__(self, output: Path, emit: Callable[[dict], None] | None = None, *, offline: bool = False):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.emit = emit or (lambda _event: None)
        self.offline = offline
        self.tasks: list[dict] = []
        self.busy = False
        self._gate = threading.RLock()
        self._threads: set[threading.Thread] = set()
        self._resource_gate = threading.Lock()
        self._view_key = None
        self._view_cache = None
        self._rows = []
        self._pools = []
        self._logs = self.output/'logs'/'desktop.jsonl'
        self._load_tasks()
        accounts.ensure_ready(self.output)
        accounts.repair(self.output)
        server_config.init_from(self.output)
        official_banners.set_active_banners(official_banners.load_banners(self.output/official_banners.cache_filename()))

    def _load_tasks(self):
        try:
            for line in reversed(self._logs.read_text('utf-8').splitlines()[-100:]):
                task = json.loads(line)
                if isinstance(task, dict) and task.get('id') and task.get('state') in ('succeeded', 'failed', 'cancelled'):
                    self.tasks.append(task)
        except (OSError, ValueError):
            pass

    def log(self, task: dict, message: str):
        entry = {'time': datetime.now().isoformat(timespec='seconds'), 'message': safe_message(message)}
        with self._gate:
            task['logs'].append(entry)
            task['logs'] = task['logs'][-100:]
        self.emit({'type': 'event', 'name': 'task', 'payload': task.copy()})

    def job(self, label: str, work: Callable, *, exclusive: bool = True) -> dict:
        with self._gate:
            if exclusive and self.busy:
                raise ValueError('正在完成当前操作，请稍候再试')
            if exclusive:
                self.busy = True
            task = {'id': uuid.uuid4().hex, 'label': label, 'state': 'running', 'logs': [],
                    'exclusive': exclusive, 'startedAt': datetime.now().isoformat(timespec='seconds')}
            self.tasks.insert(0, task)
            self.tasks = self.tasks[:100]

        def run():
            self.log(task, f'开始{label}')
            try:
                result = work(lambda message: self.log(task, message), task['id'])
                task['state'] = 'succeeded'
                self.log(task, f'{label}完成')
                if result is not None:
                    self.emit({'type': 'event', 'name': 'result', 'payload': {'operationId': task['id'], 'result': result}})
            except Exception as error:
                task['state'] = 'cancelled' if type(error).__name__ == 'UpdateCancelled' else 'failed'
                task['error'] = safe_message(error)
                self.log(task, error)
            finally:
                if exclusive:
                    self.busy = False
                task['finishedAt'] = datetime.now().isoformat(timespec='seconds')
                try:
                    self._logs.parent.mkdir(parents=True, exist_ok=True)
                    if self._logs.exists() and self._logs.stat().st_size > 1024*1024:
                        self._logs.replace(self._logs.with_suffix('.previous.jsonl'))
                    with self._logs.open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(task, ensure_ascii=False)+'\n')
                except OSError:
                    pass
                self.invalidate()
                self.emit({'type': 'event', 'name': 'task', 'payload': task.copy()})
                self.emit({'type': 'event', 'name': 'changed', 'payload': {'busy': self.busy}})
                with self._gate:
                    self._threads.discard(threading.current_thread())

        worker = threading.Thread(target=run, name=f'stella-{label}', daemon=True)
        with self._gate:
            self._threads.add(worker)
        worker.start()
        return {'operationId': task['id']}

    def invalidate(self):
        with self._gate:
            self._view_key = None

    def _snapshot(self):
        snapshot = service.load_latest_snapshot(self.output)
        return snapshot or service.Snapshot([])

    def _view(self):
        with storage_transaction(self.output), self._gate:
            path = service.active_archive_path(self.output)
            account = accounts.active_account(self.output)
            stat = path.stat() if path.exists() else None
            key = (account.key if account else '', stat.st_mtime_ns if stat else 0, stat.st_size if stat else 0, server_config.active().key)
            if key == self._view_key:
                return self._view_cache
            snapshot = self._snapshot()
            grouped = categories(snapshot.gacha)
            stats = overview(snapshot.gacha)
            cards = []
            self._rows = []
            self._pools = []
            for category in GACHA_CATEGORY_ORDER:
                value = stats.category_stats[category]
                if value:
                    total, five = value.total_pulls, len(value.five_stars)
                    cards.append({'key': category, 'name': GACHA_CATEGORY_NAMES[category], 'pulls': total, 'five': five,
                                  'pity': value.current_pity, 'limit': GACHA_CATEGORY_PITY_LIMITS[category],
                                  'average': round(total/five, 1) if five else None})
                else:
                    cards.append({'key': category, 'name': GACHA_CATEGORY_NAMES[category], 'pulls': 0, 'five': 0,
                                  'pity': 0, 'limit': GACHA_CATEGORY_PITY_LIMITS[category], 'average': None})
                for pool in build_banner_stats_with_shared_pity(grouped[category]):
                    info = official_banners.official_pool_info(pool.gid)
                    name = info[0] if info else official_banners.pool_display_name(pool.gid)
                    has_up = category in LIMITED and bool(info and info[3])
                    rewards = {pool.gid: stats.rewards[pool.gid]} if pool.gid in stats.rewards else {}
                    entries = insert_spark_rewards(pool.five_stars, rewards)
                    pulls = []
                    for pull in entries:
                        reward = isinstance(pull, SparkReward)
                        pulls.append({'itemId': pull.item_id, 'kind': pull.kind, 'name': pull.name,
                                      'time': pull.last_pull_time if reward else pull.timestamp,
                                      'interval': None if reward else pull.pity, 'reward': reward,
                                      'result': '井' if reward else ('UP' if same_item_name(pull.name, info[3]) else '歪') if has_up else '—'})
                    self._pools.append({'gid': pool.gid, 'name': name, 'category': category,
                                        'activity': official_banners.is_activity_pool(pool.gid), 'pulls': pool.total_pulls,
                                        'five': len(pool.five_stars), 'start': info[1] if info else '', 'end': info[2] if info else '',
                                        'lastTime': pool.end_time, 'well': pool.gid in stats.rewards, 'entries': pulls})
                since_five = 0
                for group_index, group in enumerate(sorted(grouped[category], key=lambda g: (g.get('Time', 0), g['Gid']))):
                    gid = group['Gid']
                    info = official_banners.official_pool_info(gid)
                    pool_name = info[0] if info else official_banners.pool_display_name(gid)
                    for index, item in enumerate(group.get('Ids', [])):
                        name = gacha_item_name(item)
                        star = is_five_star_item(item)
                        since_five += 1
                        interval = since_five if star else None
                        if star:
                            since_five = 0
                        has_up = category in LIMITED and bool(info and info[3])
                        self._rows.append({'key': f'{category}:{group_index}:{index}', 'category': category, 'gid': gid,
                                           'time': group.get('Time', 0), 'itemId': item, 'kind': gacha_item_kind(item),
                                           'name': name, 'five': star, 'poolName': pool_name,
                                           'interval': interval,
                                           'activity': official_banners.is_activity_pool(gid),
                                           'result': ('UP' if same_item_name(name, info[3]) else '歪') if star and has_up else '—',
                                           '_index': index})
            self._rows.sort(key=lambda row: (row['time'], row['gid'], row['_index']), reverse=True)
            self._pools.sort(key=lambda row: (row['lastTime'], row['gid']), reverse=True)
            self._view_cache = {'uid': snapshot.uid, 'pulls': stats.total_pulls, 'five': stats.total_five,
                                'rate': round(stats.total_five/stats.total_pulls*100, 2) if stats.total_pulls else 0,
                                'average': round(stats.total_pulls/stats.total_five, 1) if stats.total_five else None,
                                'groups': len(snapshot.gacha), 'categories': cards, 'activity': activity_pools(snapshot.gacha),
                                'firstTime': min((g.get('Time', 0) for g in snapshot.gacha), default=0),
                                'lastTime': max((g.get('Time', 0) for g in snapshot.gacha), default=0)}
            self._view_key = key
            return self._view_cache

    def state(self):
        view = self._view()
        state = accounts.load_state(self.output)
        return {'protocolVersion': 1, 'version': APP_VERSION, 'busy': self.busy, 'offline': self.offline,
                'preferences': read_preferences(self.output), 'accounts': [
                    {'key': account.key, 'uid': account.uid, 'name': account.name, 'label': account.label,
                     'groups': accounts.archive_group_count(self.output, account.key)} for account in state.accounts],
                'activeAccount': state.active, 'server': server_config.active().key,
                'serverManual': server_config.load_manual(server_config.config_path(self.output)),
                'servers': [{'key': p.key, 'label': p.label} for p in server_config.PROFILES.values()],
                'archivePath': str(service.active_archive_path(self.output)), 'summary': view,
                'tasks': self.tasks[:50], 'outputPath': str(self.output), 'bindCommand': rem_upload.bind_command_for(view['uid']) if re.fullmatch(r'\d{5,15}', view['uid']) else ''}

    def query_records(self, params: dict):
        self._view()
        category = params.get('category', 'all')
        query = str(params.get('query', '')).strip().casefold()[:200]
        page = max(1, int(params.get('page', 1)))
        size = min(200, max(1, int(params.get('pageSize', 50))))
        mode = params.get('mode', 'five')
        if mode not in ('five', 'all') or category not in (*GACHA_CATEGORY_ORDER, 'all', 'activity'):
            raise ValueError('记录筛选无效')
        source = self._rows if mode == 'all' else self._pools
        result = []
        for row in source:
            if params.get('gid') is not None and row['gid'] != params['gid']:
                continue
            if category == 'activity' and not row['activity']:
                continue
            if category not in ('all', 'activity') and row['category'] != category:
                continue
            if mode == 'all':
                if params.get('fiveOnly') is True and not row['five']:
                    continue
                if query and query not in (row['name']+' '+row['poolName']).casefold():
                    continue
                result.append({k: v for k, v in row.items() if not k.startswith('_')})
            else:
                entries = row['entries']
                if query and query not in row['name'].casefold():
                    entries = [entry for entry in entries if query in entry['name'].casefold()]
                    if not entries:
                        continue
                result.append({**row, 'entries': entries[:60], 'entriesTotal': len(entries)})
        if params.get('ascending') is True:
            result.reverse()
        total = len(result)
        page = min(page, max(1, (total+size-1)//size))
        return {'items': result[(page-1)*size:page*size], 'total': total, 'page': page, 'pageSize': size}

    def save_preferences(self, changes: dict):
        allowed = {'color_mode', 'auto_upload', 'auto_update', 'pool_columns', 'update_channel'}
        if not isinstance(changes, dict) or set(changes)-allowed:
            raise ValueError('不支持的设置项')
        for key, value in changes.items():
            if key == 'color_mode' and value not in ('light', 'dark'):
                raise ValueError('主题无效')
            if key == 'update_channel' and value not in ('stable', 'beta'):
                raise ValueError('更新渠道无效')
            if key.startswith('auto_') and type(value) is not bool:
                raise ValueError('开关必须为布尔值')
            if key == 'pool_columns' and value is not None and (type(value) is not int or value not in (1, 2)):
                raise ValueError('列数无效')
        with storage_transaction(self.output):
            values = read_preferences(self.output)
            values.update(changes)
            archive_layout.write_atomic(self.output/'ui_settings.json', values)
        return read_preferences(self.output)

    def backup(self, key: str | None = None):
        with storage_transaction(self.output):
            account = next((a for a in accounts.load_state(self.output).accounts if a.key == key), None) if key else accounts.active_account(self.output)
            if account is None:
                raise ValueError('账号不存在')
            directory = accounts.data_dir(self.output, account.key)
            path = archive_layout.archive_path(directory)
            if not path.exists():
                path = directory/service.ARCHIVE_FILENAME
            if not path.exists():
                return None
            destination = self.output/'backups'/f'{account.key}_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            return str(destination)

    def account_action(self, action: str, params: dict):
        with storage_transaction(self.output):
            key = str(params.get('key', ''))
            known = {a.key for a in accounts.load_state(self.output).accounts}
            if action != 'create' and key not in known:
                raise ValueError('账号不存在')
            if action == 'switch':
                success = accounts.switch(self.output, key)
            elif action == 'rename':
                success = accounts.rename(self.output, key, str(params.get('name', '')).strip()[:100])
            elif action == 'create':
                uid = str(params.get('uid', '')).strip()
                if uid:
                    rem_upload.validate_uid(uid)
                created = accounts.create(self.output, uid=uid, name=str(params.get('name', '')).strip()[:100])
                success = created is not None and accounts.switch(self.output, created.key)
            elif action == 'remove':
                if len(known) <= 1:
                    raise ValueError('至少保留一个账号')
                success = accounts.remove(self.output, key)
            elif action == 'merge':
                if str(params.get('target', '')) not in known:
                    raise ValueError('目标账号不存在')
                self.backup(key)
                self.backup(str(params['target']))
                service.merge_accounts(self.output, key, str(params['target']))
                success = True
            else:
                raise ValueError('不支持的账号操作')
            if not success:
                raise OSError('账号操作未完成，请检查目录写入权限')
        self.invalidate()
        return {'ok': True}

    def save_uid(self, uid: str):
        uid = str(uid).strip()
        if uid:
            rem_upload.validate_uid(uid)
        with storage_transaction(self.output):
            current = accounts.active_account(self.output)
            if current is None:
                raise ValueError('账号不存在')
            payload = service.read_owned_archive(accounts.data_dir(self.output, current.key), current.uid)
            if uid and payload.get('categories') and payload.get('uid') != uid:
                raise ValueError('当前归档 UID 缺失或属于其他账号，已停止修改；请核对归属并切换账号')
            other = accounts.find_by_uid(self.output, uid) if uid else None
            if other and other.key != current.key:
                accounts.switch(self.output, other.key)
            else:
                if not service.save_manual_uid(accounts.data_dir(self.output, current.key), uid):
                    raise OSError('UID 保存失败')
                if uid and not accounts.set_uid(self.output, current.key, uid):
                    raise OSError('账号 UID 登记失败')
        self.invalidate()
        return {'uid': service.effective_uid(self.output)}

    def select_process(self, pid):
        if type(pid) is not int or pid <= 0:
            raise ValueError('请选择具体游戏进程')
        selected = next((p for p in find_game_processes() if p.pid == pid), None)
        if selected is None:
            raise ValueError('所选游戏进程已退出，请重新选择')
        current = server_config.active().key
        key = 'cn' if selected.name.casefold() == 'xtlr.exe' else current if current in ('intl', 'jp', 'tw') else 'intl'
        if key != current:
            server_config.set_active(key)
            if not server_config.save_key(server_config.config_path(self.output), key, manual=False):
                raise OSError('服务器设置保存失败')
        return selected

    def capture(self, pid, progress):
        selected = self.select_process(pid)
        result = service.extract_snapshot(self.output, selected.name, progress=progress, verify_uid=True, process_id=selected.pid)
        self.invalidate()
        self.emit({'type': 'event', 'name': 'changed', 'payload': {'busy': self.busy}})
        warnings = []
        if not self.offline:
            try:
                self.sync_resources(progress)
            except Exception as error:
                warnings.append(f'本地归档已保存；资源补全未完成：{safe_message(error)}')
        if read_preferences(self.output)['auto_upload']:
            try:
                self.upload(result.uid, progress, automatic=True)
            except Exception as error:
                warnings.append(f'本地归档已保存；自动上传未完成：{safe_message(error)}')
        for warning in warnings:
            progress(warning)
        return {'uid': result.uid, 'pulls': result.pull_count, 'warnings': warnings}

    def read_game_uid(self, pid, progress):
        selected = self.select_process(pid)
        result = service.read_game_uid(self.output, progress=progress, process_name=selected.name, process_id=selected.pid)
        if not result.found:
            raise ValueError(result.summary())
        return self.save_uid(result.uid)

    def read_affinity(self, pid, progress=None):
        """读取角色好感度: 只读内存, 结果单独存到账号目录的 affinity.json。"""
        selected = self.select_process(pid)
        return service.read_affinity(
            self.output, progress=progress, process_name=selected.name, process_id=selected.pid)

    def load_affinity(self):
        """上次保存的好感度(游戏没开也能看)。"""
        return service.load_affinity(self.output)

    def import_files(self, paths: list[str], progress):
        results, failures = [], []
        for name in paths:
            path = Path(name)
            try:
                _categories, uid = parse_import_text(service.read_import_text(path), path.suffix)
                if uid:
                    rem_upload.validate_uid(uid)
                target = accounts.find_by_uid(self.output, uid) if uid else accounts.active_account(self.output)
                if target is not None:
                    self.backup(target.key)  # Exceptions stop this file before any merge.
                progress(f'正在导入 {path.name}')
                imported = service.import_gacha_file(self.output, path)
                self.invalidate()
                results.append({'name': path.name, 'uid': imported.uid, 'addedGroups': imported.added_groups, 'addedPulls': imported.added_pulls})
                if read_preferences(self.output)['auto_upload'] and imported.uid:
                    try:
                        self.upload(imported.uid, progress, automatic=True)
                    except Exception as error:
                        progress(f'本地归档已保存；自动上传未完成：{safe_message(error)}')
            except Exception as error:
                failures.append(f'{path.name}: {safe_message(error)}')
        if failures:
            progress('；'.join(failures))
        if not results:
            raise ValueError('；'.join(failures) or '未选择有效文件')
        return {'files': results, 'failures': failures}

    def export_records(self, directory: str, progress):
        snapshot = self._snapshot()
        if not snapshot.gacha:
            raise ValueError('暂无可导出的记录')
        files = export_all(Path(directory), snapshot.gacha, None, snapshot.gacha_categories, uid=snapshot.uid)
        progress('JSON / CSV 已导出')
        return {'files': [str(path) for path in files]}

    def sync_resources(self, progress):
        if not self._resource_gate.acquire(blocking=False):
            progress('资源补全已在后台进行')
            return {'pending': True}
        try:
            for _attempt in range(3):
                profile = server_config.active().key
                try:
                    result = self._sync_resources(progress)
                except catalog_sync.CatalogLanguageChanged:
                    progress('版本已切换，正在按当前语言重新补全')
                    continue
                if profile == server_config.active().key:
                    return result
                progress('版本已切换，正在按当前语言重新补全')
            return {'deferred': True}
        finally:
            self._resource_gate.release()

    def _sync_resources(self, progress):
        if self.offline:
            progress('离线模式，保留内置资源与缓存')
            return {'offline': True}
        try:
            profile = server_config.active()
            if not official_banners.refresh_from_network(self.output/official_banners.cache_filename(), lang=profile.api_lang):
                progress('卡池在线更新失败，沿用缓存')
            if profile.key != server_config.active().key:
                raise catalog_sync.CatalogLanguageChanged('服务器已切换')
        except (OSError, ValueError) as error:
            progress(f'卡池更新未完成：{safe_message(error)}')
        snapshot = self._snapshot()
        ids = [int(item) for group in snapshot.gacha for item in group.get('Ids', [])]
        report = catalog_sync.sync_with_report(self.output/'catalog_sync_state.json', ids, progress=progress)
        self.invalidate()
        progress(f"资源同步完成 · 补充名称 {len(report['registered'])} · 头像 {len(report['downloaded'])}")
        return {'registered': len(report['registered']), 'downloaded': len(report['downloaded']),
                'failed': len(report['icon_failed']), 'audit': report['audit_after']}

    def upload(self, uid: str, progress, *, automatic=False):
        if self.offline:
            raise ValueError('离线模式不进行上传')
        path = service.export_share_for_uid(self.output, uid)
        fingerprint = rem_upload.record_fingerprint(path)
        if automatic and rem_upload.was_uploaded(path, fingerprint, rem_upload.UPLOAD_URL):
            progress(f'UID {path.stem} 的记录没有变化，跳过重复上传')
            return {'skipped': True}
        progress(f'正在上传 UID {path.stem}')
        result = rem_upload.upload_file(path)
        rem_upload.mark_uploaded(path.parent, result.uid, fingerprint=fingerprint)
        progress(f'上传成功，仍需向蕾姆发送绑定指令确认更新：{result.bind_command}')
        return {'uid': result.uid, 'bindCommand': result.bind_command}
