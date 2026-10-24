from __future__ import annotations

import re
import struct
from bisect import bisect_left

from .discovery import LuaTableDiscovery
from .lua53 import Lua53Reader, STRING_TAGS, TAG_INTEGER
from .process import RemoteProcess, find_process_id


UID_PATTERN = re.compile(
    r"UID[ \t\u3000]*[:\uff1a][ \t\u3000]*([0-9]{5,15})[ \t\u3000]*\Z"
)
# 标签写法可能是 "UID:123"（半角冒号）、"UID：123"（全角冒号）或带空格。
UID_PREFIX_UTF16 = "UID:".encode("utf-16le")
UID_PREFIX_UTF8 = b"UID:"
# 只在玩家表读不到时才扫标签；全角冒号/空格也覆盖国服与部分语言。
UID_LABEL_PREFIXES = tuple(
    (text.encode(encoding), encoding)
    for text in ("UID:", "UID：", "UID :", "UID ：")
    for encoding in ("utf-16le", "utf-8")
)
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
        # 在成对的 NUL 终止符处截断，避免把后面的无关内存当成标签的一部分。
        end = next((i for i in range(0, len(raw) - 1, 2) if raw[i:i + 2] == b"\0\0"), len(raw))
        raw = raw[:end]
    else:
        raw = process.try_read(address, limit)
        if not raw:
            return None
        raw = raw.split(b"\x00", 1)[0]
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        return None
    match = UID_PATTERN.fullmatch(text)
    return match.group(1) if match else None


def _read_label_uids(process: RemoteProcess) -> set[str]:
    candidates: set[str] = set()
    for prefix, encoding in UID_LABEL_PREFIXES:
        for address in process.scan(prefix):
            value = _read_candidate(process, address, encoding=encoding)
            if value:
                candidates.add(value)
    return candidates


def read_game_uid(process_name: str | None = None, *, process_id: int | None = None) -> str:
    """Read the currently loaded game UID through a read-only process handle.

    Read the Lua player profile first (the UID shown in-game and used by the
    upload service), then fall back to UI/cache labels. Never write to the
    process or inspect network credentials.
    """

    pid = find_process_id(process_name, pid=process_id)
    with RemoteProcess(pid) as process:
        return read_game_uid_from_process(process)


class AmbiguousUidError(LookupError):
    pass


def read_game_uid_from_process(process: RemoteProcess) -> str:
    # 玩家表是游戏当前账号的权威来源；国服客户端还把内部账号 ID 放在 nUid
    # 之类的字段里，不能用它覆盖玩家表里的 _nPlayerId（否则会误判成两个 UID）。
    player_uids = _read_player_uids(process)
    if player_uids:
        if len(player_uids) != 1:
            raise AmbiguousUidError("检测到多个玩家 UID，可能存在切换账号后的缓存。请重新启动游戏后再读取，避免归档混入其他账号")
        return player_uids.pop()

    # 玩家表不可用时才退回 UI/cache 标签；这里只扫具体的标签前缀，
    # 不扫裸 "UID"（那会把大量无关字符串一起扫进来，读取会明显变慢）。
    label_uids = _read_label_uids(process)
    if not label_uids:
        raise LookupError("未找到游戏 UID，请确认已登录游戏并进入主界面或个人资料页")
    if len(label_uids) != 1:
        raise AmbiguousUidError("检测到多个 UID，可能存在切换账号后的缓存。请重新启动游戏后再读取，避免归档混入其他账号")
    return label_uids.pop()
