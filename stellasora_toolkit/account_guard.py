from __future__ import annotations

import json
import re
from pathlib import Path

from .history_schema import HISTORY_CATEGORY_KEYS


SESSION_DIRECTORY = "account_sessions"
UID_PATTERN = re.compile(r"[0-9]{5,15}")


class AccountSafetyError(ValueError):
    pass


def _session_path(output_dir: Path, pid: int, creation_time: int) -> Path:
    if type(pid) is not int or pid <= 0 or type(creation_time) is not int or creation_time <= 0:
        raise AccountSafetyError("无法确认游戏进程的启动标识，已停止读取，请重启游戏后重试")
    return output_dir / SESSION_DIRECTORY / f"{pid}-{creation_time}.json"


def block_process_session(output_dir: Path, pid: int, creation_time: int) -> None:
    path = _session_path(output_dir, pid, creation_time)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".blocked").touch(exist_ok=True)


def check_process_account(output_dir: Path, pid: int, creation_time: int, uid: str) -> None:
    if not isinstance(uid, str) or UID_PATTERN.fullmatch(uid) is None:
        raise AccountSafetyError("无效的游戏 UID，已停止读取")
    path = _session_path(output_dir, pid, creation_time)
    blocked = path.with_suffix(".blocked")
    if blocked.exists() and not path.exists():
        # 旧版本在"只是没读到 UID"时也会写阻断标记, 那种标记没有绑定过任何 UID,
        # 不能证明发生过切号。清掉它, 避免一次临时读取失败把整个游戏会话锁死。
        try:
            blocked.unlink()
        except OSError:
            pass
    if blocked.exists():
        raise AccountSafetyError(
            "这次游戏启动期间已检测到账号切换或 UID 异常，已停止保存。"
            "请完全退出并重启游戏，再登录目标账号、依次打开各类招募记录后读取。"
            "只重启工具或切回原账号不能解除保护。"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation keeps the first UID immutable, including across tool restarts.
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"version": 1, "uid": uid}, handle)
    except FileExistsError:
        pass
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or type(state.get("version")) is not int or state.get("version") != 1:
            raise ValueError("invalid session state")
        previous_uid = state.get("uid")
        if not isinstance(previous_uid, str) or UID_PATTERN.fullmatch(previous_uid) is None:
            raise ValueError("invalid session UID")
    except (OSError, ValueError) as error:
        raise AccountSafetyError("无法校验本次游戏的账号标记，已停止保存。请完全退出并重启游戏后重试。") from error
    if previous_uid != uid:
        block_process_session(output_dir, pid, creation_time)
        raise AccountSafetyError(
            f"同一次游戏启动中，UID 从 {previous_uid} 变为 {uid}，可能残留上一个账号的招募记录。"
            "已停止保存，未修改抽卡归档。请完全退出并重启游戏，"
            "再登录目标账号、依次打开各类招募记录后读取。"
        )
    if blocked.exists():
        raise AccountSafetyError("本次游戏进程已被标记为账号不安全，已停止保存，请完全退出并重启游戏")


def _record_keys(categories: dict) -> set[tuple]:
    if not isinstance(categories, dict):
        raise ValueError("invalid categories")
    keys: set[tuple] = set()
    for category, groups in categories.items():
        if str(category) not in HISTORY_CATEGORY_KEYS or not isinstance(groups, list):
            raise ValueError("invalid category")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("invalid group")
            gid, timestamp, ids = group.get("Gid"), group.get("Time"), group.get("Ids")
            if any(type(value) is not int or value <= 0 for value in (gid, timestamp)):
                raise ValueError("invalid group identity")
            if not isinstance(ids, list) or not ids or any(type(value) is not int or value <= 0 for value in ids):
                raise ValueError("invalid pull results")
            keys.add((int(category), gid, timestamp, tuple(ids)))
    return keys


def check_account_records(output_dir: Path, uid: str, categories: dict) -> None:
    """Reject suspicious cross-account overlap without guessing which account owns it."""
    try:
        current = _record_keys(categories)
    except ValueError as error:
        raise AccountSafetyError("抽卡记录格式异常，无法完成防串号校验，已停止操作") from error
    if not current:
        return
    root = Path(output_dir)
    if root.parent.name == 'accounts':
        root = root.parent.parent
    paths = set(path for path in root.glob('*.json') if UID_PATTERN.fullmatch(path.stem))
    for directory in (root / 'accounts').glob('*'):
        if not directory.is_dir() or '.deleted_' in directory.name:
            continue
        archive = directory / 'stellasora_gacha_archive.json'
        if archive.is_file():
            paths.add(archive)
        paths.update(path for path in directory.glob('*.json') if UID_PATTERN.fullmatch(path.stem))
    for path in sorted(paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError('archive is not an object')
            other_uid = payload.get('uid', path.stem if UID_PATTERN.fullmatch(path.stem) else '')
            if not other_uid and path.name == 'stellasora_gacha_archive.json':
                continue  # Unclaimed legacy data is preserved, never adopted here.
            if not isinstance(other_uid, str) or not UID_PATTERN.fullmatch(other_uid):
                raise ValueError('invalid archive UID')
            if UID_PATTERN.fullmatch(path.stem) and other_uid != path.stem:
                raise ValueError("archive UID mismatch")
            if other_uid == uid:
                continue
            other = _record_keys(payload.get("categories"))
        except (OSError, ValueError) as error:
            raise AccountSafetyError(
                f"无法核验账号归档 {path.name}，已停止操作。请先备份并检查该文件，不会自动覆盖或删除。"
            ) from error
        overlap = current & other
        # A same-second single pull can coincide; require multiple batches and times.
        if len(overlap) >= 3 and len({key[2] for key in overlap}) >= 2:
            raise AccountSafetyError(
                f"UID {uid} 与 UID {other_uid} 存在 {len(overlap)} 条卡池、时间和结果完全相同的招募记录，疑似混号。"
                "已停止操作，未保存或上传本次记录。请先备份整个 exports 文件夹，"
                "分别重启游戏并在全新目录重新读取、核对归属。已经混入的旧档不会因重读而自动清除，"
                "请保留原档，确认后再处理。"
            )
