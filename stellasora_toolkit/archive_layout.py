"""UID archives live at exports/<UID>.json; account folders retain private metadata.

Migration is idempotent and never removes its input files. A per-account receipt
prevents preserved legacy exports from being merged into the live archive again.
No dependency on accounts/service: path lookup must not recursively load state.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

LEGACY_NAME = 'stellasora_gacha_archive.json'
RECEIPT_NAME = 'archive_layout.json'
UID_RE = re.compile(r'[0-9]{5,15}')


def context(directory: Path) -> tuple[Path, str, list[Path]]:
    directory = Path(directory)
    root = directory.parent.parent if directory.parent.name == 'accounts' else directory
    try:
        state = json.loads((root / 'accounts.json').read_text('utf-8'))
        rows = state['accounts']
        key = directory.name if directory.parent.name == 'accounts' else state['active']
        row = next(row for row in rows if row.get('key') == key)
        uid = str(row.get('uid') or '')
        if not UID_RE.fullmatch(uid):
            return root, '', []
        # Keys are checked again here because this also reads externally supplied JSON.
        peers = [root / 'accounts' / row['key'] for row in rows
                 if row.get('uid') == uid and isinstance(row.get('key'), str)
                 and re.fullmatch(r'[0-9A-Za-z_-]{1,64}', row['key'])]
        return root, uid, peers
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return root, '', []


def archive_path(directory: Path) -> Path:
    root, uid, _ = context(directory)
    return root / f'{uid}.json' if uid else Path(directory) / LEGACY_NAME


def migrated(directory: Path, uid: str) -> bool:
    try:
        receipt = json.loads((directory / RECEIPT_NAME).read_text('utf-8'))
        return receipt == {'version': 1, 'uid': uid}
    except (OSError, ValueError):
        return False


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.archive-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read(path: Path, uid: str) -> dict:
    payload = json.loads(path.read_text('utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('version', 1) != 1:
        raise ValueError('不支持的归档格式')
    owner = payload.get('uid')
    if owner is None and path.name == f'{uid}.json':
        owner = uid  # B also accepts an unambiguous numeric filename.
    if owner != uid:
        raise ValueError('旧归档 UID 缺失或不一致')
    categories = payload.get('categories')
    if not isinstance(categories, dict) or set(categories) - {'1', '2', '3', '4', '6'}:
        raise ValueError('无效的抽卡分类')
    for groups in categories.values():
        if not isinstance(groups, list):
            raise ValueError('无效的记录列表')
        for group in groups:
            if not isinstance(group, dict) or any(type(group.get(k)) is not int or group[k] <= 0
                                                  for k in ('Gid', 'Time')):
                raise ValueError('无效的卡池或时间')
            ids = group.get('Ids')
            if not isinstance(ids, list) or not ids or any(type(v) is not int or v <= 0 for v in ids):
                raise ValueError('无效的抽卡结果')
    return dict(payload, uid=uid)


def ensure_archive(directory: Path) -> Path:
    """Prepare the flat archive, or fail before a writer can replace suspect data."""
    from .account_guard import AccountSafetyError
    root, uid, peers = context(directory)
    target = archive_path(directory)
    if not uid:
        return target
    pending = [peer for peer in peers if not migrated(peer, uid)]
    if not pending:
        if not target.is_file():
            raise AccountSafetyError(f'UID {uid} 的主归档缺失，已停止写入；请从备份恢复 {target.name}')
        return target
    try:
        sources = []
        for peer in pending:
            canonical = peer / LEGACY_NAME
            share = peer / f'{uid}.json'
            sources.extend(path for path in (canonical, share) if path.is_file())
            if not canonical.exists() and not share.exists():
                exports = sorted((p for p in peer.glob('stellasora_gacha_*.json')
                                  if p.name != LEGACY_NAME), key=lambda p: p.stat().st_mtime)
                if exports:
                    sources.append(exports[-1])
        # The pre-account layout is normally copied into a peer by accounts.load_state.
        payloads = [_read(path, uid) for path in sources]
        existing = _read(target, uid) if target.exists() else None
        if existing is not None:
            payloads.append(existing)  # Current primary wins duplicate metadata.
        if payloads:
            from .exporter import normalize_category_keys
            merged: dict[int, dict[tuple, dict]] = {}
            for payload in payloads:
                categories = normalize_category_keys({int(k): v for k, v in payload['categories'].items()})
                for category, groups in categories.items():
                    for group in groups:
                        key = (group['Gid'], group['Time'], tuple(group['Ids']))
                        merged.setdefault(category, {})[key] = group
            result = dict(payloads[-1], version=1, uid=uid, categories={
                str(k): sorted(v.values(), key=lambda g: (g['Time'], g['Gid']))
                for k, v in sorted(merged.items())})
            if existing != result:
                if target.exists():
                    backup = pending[0] / f'pre_migration_{uid}.json'
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    # Exclusive creation preserves the original even after a retry.
                    if not backup.exists():
                        with backup.open('xb') as handle:
                            handle.write(target.read_bytes())
                write_atomic(target, result)
        if target.is_file():
            for peer in pending:
                write_atomic(peer / RECEIPT_NAME, {'version': 1, 'uid': uid})
        return target
    except (OSError, ValueError, TypeError) as error:
        raise AccountSafetyError(
            f'UID {uid} 的归档迁移未完成：{error}。已停止写入，旧文件保留；请先备份 exports 并核对归属或恢复损坏文件。'
        ) from error
