"""Small, account-scoped summaries of existing sidecar data; never reads the game."""
from pathlib import Path

from . import affinity, roster


def cached_summary(root: Path, uid: str, *, kind: str) -> dict:
    adapter = roster if kind == 'roster' else affinity
    path = adapter.cache_path(root, uid)
    empty = {'available': False, 'count': 0, 'highestLevel': 0, 'updatedAt': '', 'portraits': [], 'emblems': 0}
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return {**empty, 'error': '缓存过大，请到对应页面重新读取'}
        payload = adapter.load_cache(path)
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError, OverflowError):
        return {**empty, 'error': '缓存暂不可读，请到对应页面重新读取'}
    if payload is None or payload['uid'] != uid:
        return {**empty, 'error': '缓存损坏或 UID 不匹配，请重新读取'}
    entries = payload['characters' if kind == 'roster' else 'entries']
    ordered = sorted(entries, key=lambda row: (-row['level'], row['id']))
    return {'available': True, 'count': len(entries), 'highestLevel': max((row['level'] for row in entries), default=0),
            'updatedAt': payload['updatedAt'], 'portraits': [
                {key: row[key] for key in ('id', 'name', 'level')} for row in ordered[:3]],
            'emblems': sum(len(row['emblems']) for row in entries) if kind == 'roster' else 0}
