from __future__ import annotations

import re

from .process import RemoteProcess, find_process_id


UID_PATTERN = re.compile(r"UID:([0-9]{5,15})\Z")
UID_PREFIX_UTF16 = "UID:".encode("utf-16le")
UID_PREFIX_ASCII = b"UID:"


def _read_candidate(process: RemoteProcess, address: int, *, encoding: str, limit: int = 64) -> str | None:
    if encoding == "utf-16le":
        raw = process.try_read(address, limit * 2)
        if not raw:
            return None
        text = raw.decode(encoding, errors="ignore").split("\x00", 1)[0]
    else:
        raw = process.try_read(address, limit)
        if not raw:
            return None
        text = raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
    match = UID_PATTERN.fullmatch(text)
    return match.group(1) if match else None


def read_game_uid(process_name: str | None = None, *, process_id: int | None = None) -> str:
    """Read the currently loaded game UID through a read-only process handle.

    StellaSora currently keeps a UTF-16 UI/cache string such as ``UID:123456789``
    in the client process. We only scan readable memory and never write to the
    process or inspect network credentials.
    """

    pid = find_process_id(process_name, pid=process_id)
    with RemoteProcess(pid) as process:
        return read_game_uid_from_process(process)


class AmbiguousUidError(LookupError):
    pass


def read_game_uid_from_process(process: RemoteProcess) -> str:
    candidates: list[str] = []
    for address in process.scan(UID_PREFIX_UTF16):
        value = _read_candidate(process, address, encoding="utf-16le")
        if value:
            candidates.append(value)
    # Keep an ASCII fallback for client versions that render the label in a
    # narrow string instead of a managed UTF-16 string.
    for address in process.scan(UID_PREFIX_ASCII):
        value = _read_candidate(process, address, encoding="ascii")
        if value:
            candidates.append(value)

    if not candidates:
        raise LookupError("未找到游戏 UID，请确认已登录游戏并进入主界面或个人资料页")
    unique = set(candidates)
    if len(unique) != 1:
        raise AmbiguousUidError("检测到多个 UID，可能存在切换账号后的缓存。请重新启动游戏后再读取，避免归档混入其他账号")
    return unique.pop()
