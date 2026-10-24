from __future__ import annotations

import re
import struct
from bisect import bisect_left

from .discovery import LuaTableDiscovery
from .lua53 import Lua53Reader, STRING_TAGS, TAG_INTEGER
from .process import RemoteProcess, find_process_id


UID_PATTERN = re.compile(r"UID:([0-9]{5,15})\Z")
UID_PREFIX_UTF16 = "UID:".encode("utf-16le")
UID_PREFIX_ASCII = b"UID:"
PLAYER_UID_FIELD = "_nPlayerId"


def _player_uid_value(lua: Lua53Reader, address: int) -> str | None:
    value = lua.read_tvalue(address)
    if value.tag not in STRING_TAGS | {TAG_INTEGER}:
        return None
    text = str(lua.decode_tvalue(value))
    return text if re.fullmatch(r"[0-9]{5,15}", text) else None


def _is_player_table(lua: Lua53Reader, table: int) -> bool:
    nickname = lua.get_table_field_tvalue(table, "_sPlayerNickName")
    if nickname is None or nickname.tag not in STRING_TAGS:
        return False
    if not isinstance(lua.decode_tvalue(nickname), str):
        return False
    for name in ("_nWorldClass", "_nCurEnergy"):
        value = lua.get_table_field_tvalue(table, name)
        if value is None or value.tag != TAG_INTEGER or lua.decode_tvalue(value) < 0:
            return False
    return True


def _read_player_uids(process: RemoteProcess) -> set[str]:
    lua = Lua53Reader(process)
    discovery = LuaTableDiscovery(process, lua)
    nodes: set[int] = set()
    for node in discovery._find_key_nodes(discovery._find_tstrings(PLAYER_UID_FIELD)):
        try:
            if _player_uid_value(lua, node) is not None:
                nodes.add(node)
        except (OSError, ValueError, struct.error):
            continue
    if not nodes:
        return set()
    ordered = sorted(nodes)
    candidates: set[str] = set()
    checked: set[tuple[int, int]] = set()
    chunk_size = 1024 * 1024
    # Index every matching node, including distant allocator regions. A field
    # can belong to multiple live/cached players; never choose the first match.
    for region in process.regions():
        for offset in range(0, region.size, chunk_size):
            base = region.base + offset
            data = process.try_read(base, min(chunk_size + 47, region.size - offset))
            if not data:
                continue
            start = (-base) % 8
            tags = data[start + 8::8]
            hit = tags.find(b"\x05")
            while hit >= 0:
                pos = start + hit * 8
                hit = tags.find(b"\x05", hit + 1)
                if pos + 48 > len(data) or data[pos + 11] > 16:
                    continue
                count = 1 << data[pos + 11]
                if count + struct.unpack_from("<I", data, pos + 12)[0] > lua.max_table_entries:
                    continue
                pointer = struct.unpack_from("<Q", data, pos + 24)[0]
                index = bisect_left(ordered, pointer)
                while index < len(ordered) and ordered[index] < pointer + count * 32:
                    node = ordered[index]
                    index += 1
                    table = base + pos
                    if (node - pointer) % 32 or (table, node) in checked:
                        continue
                    checked.add((table, node))
                    try:
                        # Revalidate the live header before field iteration.
                        lsize, array_size, _, live_pointer = lua.table_header(table)
                        if lsize > 16 or (1 << lsize) + array_size > lua.max_table_entries or live_pointer != pointer:
                            continue
                        if not 0 <= node - live_pointer < (1 << lsize) * 32:
                            continue
                        key = lua.read_tvalue(node + 16)
                        if key.tag not in STRING_TAGS or lua.decode_tvalue(key) != PLAYER_UID_FIELD:
                            continue
                        uid = _player_uid_value(lua, node)
                        if uid is not None and _is_player_table(lua, table):
                            candidates.add(uid)
                    except (OSError, ValueError, struct.error):
                        continue
    return candidates


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

    Read UI/cache labels and the Lua player profile used by overseas clients.
    Never write to the process or inspect network credentials.
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

    candidates.extend(_read_player_uids(process))
    if not candidates:
        raise LookupError("未找到游戏 UID，请确认已登录游戏并进入主界面或个人资料页")
    unique = set(candidates)
    if len(unique) != 1:
        raise AmbiguousUidError("检测到多个 UID，可能存在切换账号后的缓存。请重新启动游戏后再读取，避免归档混入其他账号")
    return unique.pop()
