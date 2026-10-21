from __future__ import annotations

import re
import struct
from bisect import bisect_left

from .discovery import LuaTableDiscovery
from .lua53 import Lua53Reader, STRING_TAGS, TAG_INTEGER
from .process import RemoteProcess, find_process_id


UID_PATTERN = re.compile(r"UID[ \t\u3000]*[:\uff1a][ \t\u3000]*([0-9]{5,15})[ \t\u3000]*\Z")
UID_FIELDS = ("_uid", "_sUid", "_nUid", "uid", "_userUid", "_accountUid", "_playerUid", "_roleUid", "_uidStr")


def _lua_uid_candidates(process: RemoteProcess) -> set[str]:
    lua = Lua53Reader(process)
    discovery = LuaTableDiscovery(process, lua)
    nodes: set[int] = set()
    for field in UID_FIELDS:
        nodes.update(discovery._find_key_nodes(discovery._find_tstrings(field)))
    if not nodes:
        return set()
    ordered = sorted(nodes)
    confirmed: set[int] = set()
    candidates: set[str] = set()
    # Scan table headers once across all regions: table and nodes can be far apart.
    for region in process.regions():
        for offset in range(0, region.size, 1024 * 1024):
            base = region.base + offset
            block = process.try_read(base, min(1024 * 1024 + 47, region.size - offset))
            if not block:
                continue
            start = (-base) % 8
            tags = block[start + 8::8]
            hit = tags.find(b"\x05")
            while hit != -1:
                pos = start + hit * 8
                hit = tags.find(b"\x05", hit + 1)
                if pos + 48 > len(block) or block[pos + 11] > 16:
                    continue
                count = 1 << block[pos + 11]
                array_size = struct.unpack_from("<I", block, pos + 12)[0]
                if count + array_size > lua.max_table_entries:
                    continue
                pointer = struct.unpack_from("<Q", block, pos + 24)[0]
                index = bisect_left(ordered, pointer)
                while index < len(ordered) and ordered[index] < pointer + count * 32:
                    node = ordered[index]
                    index += 1
                    if (node - pointer) % 32 or node in confirmed:
                        continue
                    try:
                        key = lua.read_tvalue(node + 16)
                        if key.tag not in STRING_TAGS or lua.decode_tvalue(key) not in UID_FIELDS:
                            continue
                        value = lua.read_tvalue(node)
                        if value.tag not in STRING_TAGS | {TAG_INTEGER}:
                            continue
                        decoded = lua.decode_tvalue(value)
                    except (OSError, ValueError, struct.error):
                        continue
                    confirmed.add(node)
                    text = str(decoded)
                    if re.fullmatch(r"[0-9]{5,15}", text):
                        candidates.add(text)
    return candidates


def _read_candidate(process: RemoteProcess, address: int, *, encoding: str, limit: int = 64) -> str | None:
    if encoding == "utf-16le":
        raw = process.try_read(address, limit * 2)
        if not raw:
            return None
        # Trim at an aligned terminator before decoding unrelated trailing memory.
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


def read_game_uid(process_name: str | None = None, *, process_id: int | None = None) -> str:
    """Read the currently loaded game UID through a read-only process handle.

    Read UI labels, then Lua account fields when labels are unavailable.
    Never write to the process or inspect network credentials.
    """

    pid = find_process_id(process_name, pid=process_id)
    with RemoteProcess(pid) as process:
        return read_game_uid_from_process(process)


class AmbiguousUidError(LookupError):
    pass


def read_game_uid_from_process(process: RemoteProcess) -> str:
    candidates: list[str] = []
    for address in process.scan("UID".encode("utf-16le")):
        value = _read_candidate(process, address, encoding="utf-16le")
        if value:
            candidates.append(value)
    # UTF-8 also covers ASCII labels and localized full-width punctuation.
    for address in process.scan(b"UID"):
        value = _read_candidate(process, address, encoding="utf-8")
        if value:
            candidates.append(value)

    if not candidates:
        candidates.extend(_lua_uid_candidates(process))
    if not candidates:
        raise LookupError("未找到游戏 UID，请确认已登录游戏并进入主界面或个人资料页")
    unique = set(candidates)
    if len(unique) != 1:
        raise AmbiguousUidError("检测到多个 UID，可能存在切换账号后的缓存。请重新启动游戏后再读取，避免归档混入其他账号")
    return unique.pop()
