# -*- coding: utf-8 -*-
"""从游戏 Lua 运行时读取角色好感度(游戏内叫 Affinity)。

数据位置(用真实客户端内存转储核对过):

    _mapChar[<角色ID>] = {
        nId            = 角色ID
        nAffinityLevel = 好感等级(如 65)
        nAffinityExp   = 当前等级内的好感经验(如 6040)
        bIsFavorite    = 是否收藏
        ...
    }

好感等级上限经验来自配置表 ``AffinityLevel`` 的 ``NeedExp`` 列
(等级 65 -> 33100), 所以界面显示的 "6040/33100" 正好是
``nAffinityExp / NeedExp[nAffinityLevel]``。

读取结果按 UID 单独存放: ``exports/<UID>_affinity.json``, 与抽卡归档
``exports/<UID>.json`` 分开; UID 没读到时落在 ``exports/unverified_affinity.json``。

读取方式与抽卡记录一致: 只读 ``ReadProcessMemory``, 在 Lua 堆里按字段名
定位表; 不写游戏内存、不抓包。和 ``discovery.find_instance_table`` 相比,
这里不需要全内存扫表头(那是刷新抽卡时最贵的一步), 只做两步指针扫描,
所以好感度页刷新也够快。
"""

from __future__ import annotations

import json
import re
import struct
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalog import traveler_name
from .lua53 import (
    STRING_TAGS,
    TAG_INTEGER,
    TAG_TABLE,
    Lua53Reader,
)

# 玩家数据表里的角色表
CHAR_TABLE_FIELD = "_mapChar"
# 每个角色表里的字段
CHAR_ID_FIELD = "nId"
CHAR_LEVEL_FIELD = "nAffinityLevel"
CHAR_EXP_FIELD = "nAffinityExp"
CHAR_FAVORITE_FIELD = "bIsFavorite"
# 好感等级配置表(AffinityLevel)里的一行: NeedExp = 该等级升级所需经验
CONFIG_NEED_FIELD = "NeedExp"
CONFIG_LEVEL_FIELD = "AffinityLevel"
CONFIG_ID_FIELD = "Id"

# 好感度数据单独存放(和 <UID>.json 抽卡归档分开), 文件名形如 <UID>_affinity.json
AFFINITY_SUFFIX = "_affinity.json"
UNVERIFIED_NAME = "unverified"


@dataclass(frozen=True)
class Affinity:
    """单个角色的好感度。"""

    id: int
    name: str
    level: int
    exp: int
    need: int
    favorite: bool = False

    @property
    def ratio(self) -> float:
        """当前等级进度 0~1; 配置缺失或已满级时为 0。"""
        if self.need <= 0:
            return 0.0
        return max(0.0, min(1.0, self.exp / self.need))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "exp": self.exp,
            "need": self.need,
            "ratio": round(self.ratio, 4),
            "favorite": self.favorite,
        }


def cache_path(root: Path, uid: str) -> Path:
    """好感度文件路径: ``exports/<UID>_affinity.json``, 与 ``<UID>.json`` 抽卡归档分开。"""
    name = str(uid or "") if re.fullmatch(r"[0-9]{5,15}", str(uid or "")) else UNVERIFIED_NAME
    return Path(root) / f"{name}{AFFINITY_SUFFIX}"


def save_cache(root: Path, uid: str, entries: list[Affinity]) -> dict:
    """把一次读取结果写进 ``exports/affinity/<UID>.json``, 返回写入的内容。"""
    from .archive_layout import write_atomic

    owner = str(uid or "")
    payload = {
        "version": 1,
        "uid": owner,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entries": [entry.as_dict() for entry in entries],
    }
    write_atomic(cache_path(root, owner), payload)
    return payload


def load_cache(path: Path) -> dict | None:
    """读回某一份好感度文件; 文件缺失/损坏返回 None(界面按"尚未读取"处理)。"""
    try:
        payload = json.loads(Path(path).read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version", 1) != 1:
        return None
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            row = Affinity(
                id=int(entry["id"]),
                name=str(entry["name"]),
                level=int(entry["level"]),
                exp=int(entry["exp"]),
                need=int(entry.get("need") or 0),
                favorite=bool(entry.get("favorite")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(row.as_dict())
    uid = payload.get("uid")
    return {
        "uid": uid if isinstance(uid, str) else "",
        "updatedAt": str(payload.get("updatedAt") or ""),
        "entries": rows,
    }


def latest_cache(root: Path) -> tuple[Path, dict] | None:
    """最近一次写入的好感度文件(没有就返回 None)。"""
    folder = Path(root)
    try:
        files = sorted(
            (path for path in folder.glob(f"*{AFFINITY_SUFFIX}") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for path in files:
        payload = load_cache(path)
        if payload is not None:
            return path, payload
    return None


def read_affinity(process, *, lua: Lua53Reader | None = None) -> list[Affinity]:
    """读取全部角色的好感度, 按好感等级从高到低排序。

    ``process`` 只需要 read/try_read/scan/regions 四个方法(与 RemoteProcess 一致),
    方便用内存转储或假内存做测试。
    """
    lua = lua or Lua53Reader(process)
    char_table = _find_char_table(process, lua)
    need_by_level = _read_need_by_level(process, lua)

    rows: list[Affinity] = []
    for key, value in _shallow_entries(lua, char_table):
        if value.tag != TAG_TABLE:
            continue
        char_table_address = struct.unpack("<Q", value.raw_value)[0]
        fields = _read_int_fields(
            lua, char_table_address,
            (CHAR_LEVEL_FIELD, CHAR_EXP_FIELD, CHAR_FAVORITE_FIELD, CHAR_ID_FIELD),
        )
        character_id = fields.get(CHAR_ID_FIELD)
        if character_id is None:
            character_id = int(key) if isinstance(key, int) else None
        if character_id is None:
            continue
        level = fields.get(CHAR_LEVEL_FIELD, 0)
        exp = fields.get(CHAR_EXP_FIELD, 0)
        rows.append(
            Affinity(
                id=int(character_id),
                name=traveler_name(character_id),
                level=int(level),
                exp=int(exp),
                need=int(need_by_level.get(int(level), 0)),
                favorite=bool(fields.get(CHAR_FAVORITE_FIELD, 0)),
            )
        )
    rows.sort(key=lambda item: (-item.level, -item.exp, item.id))
    return rows


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _iter_field_values(process, lua: Lua53Reader, field: str):
    """产出所有"以 field 为键"的表值 TValue(只认短字符串键)。"""
    encoded = field.encode("utf-8")
    for data_address in process.scan(encoded):
        object_address = data_address - 24
        header = process.try_read(object_address, 24)
        if header is None or header[8] != 4 or header[11] != len(encoded):
            continue
        if process.try_read(data_address, len(encoded) + 1) != encoded + b"\0":
            continue
        for reference in process.scan(struct.pack("<Q", object_address)):
            tag_raw = process.try_read(reference + 8, 4)
            if tag_raw is None or struct.unpack("<i", tag_raw)[0] not in STRING_TAGS:
                continue
            try:
                value = lua.read_tvalue(reference - 16)
            except (OSError, ValueError):
                continue
            yield value


def _find_char_table(process, lua: Lua53Reader) -> int:
    """定位玩家数据里的角色表 ``_mapChar``。

    内存里可能有别的地方也叫 ``_mapChar``(例如类定义/序列化描述), 所以要求
    它的值是一个表, 并且表里的条目确实带 ``nAffinityLevel`` 字段。
    """
    for value in _iter_field_values(process, lua, CHAR_TABLE_FIELD):
        if value.tag != TAG_TABLE:
            continue
        candidate = struct.unpack("<Q", value.raw_value)[0]
        try:
            for _key, entry in _shallow_entries(lua, candidate)[:8]:
                if entry.tag != TAG_TABLE:
                    continue
                address = struct.unpack("<Q", entry.raw_value)[0]
                if _field_tvalue(lua, address, CHAR_LEVEL_FIELD) is not None:
                    return candidate
        except (OSError, ValueError, struct.error):
            continue
    raise LookupError(
        "没有在游戏内存里找到角色数据表 _mapChar。\n\n"
        "请确认：1) 游戏已登录并进入主界面；2) 工具以管理员身份运行；"
        "3) 打开过一次「角色」界面让客户端把角色数据加载进内存。\n"
        "若仍失败，可能是游戏更新改了 Lua 字段名，需要适配新版本。"
    )


def _read_need_by_level(process, lua: Lua53Reader) -> dict[int, int]:
    """读取配置表 ``AffinityLevel``：好感等级 -> 升级所需经验。

    配置表每一行都有 ``NeedExp`` / ``Id`` / ``AffinityLevel``, 且所有行的字段名
    共用同一个 Lua 字符串对象, 所以扫一次 ``NeedExp`` 的引用就能拿到全部行。

    注意: 游戏里还有别的配置表也带 ``NeedExp``(角色升级、秘纹等), 它们没有
    ``AffinityLevel`` 字段; 如果只按"最近的同级字段"配对, 这些行的 NeedExp 会被
    错配到旁边好感行的等级上, 导致部分等级的最大经验错误。这里用配置行自身的
    ``Id`` 与 ``AffinityLevel`` 的固定差值(实测 ``Id = 2000 + 等级``)做一致性校验,
    只保留对得上的行, 再把同一等级里字段距离最近的那条留下。
    """
    rows: list[tuple[int, int, int | None, int]] = []   # (等级, 经验, Id, 与 NeedExp 的距离)
    for key_slot in _key_nodes(process, CONFIG_NEED_FIELD):
        # _key_nodes 给的是键槽(节点 + 16), 值在同一个节点的开头
        node = key_slot - 16
        need_value = _tvalue_or_none(lua, node)
        if need_value is None or need_value.tag != TAG_INTEGER:
            continue
        need = int(struct.unpack("<q", need_value.raw_value)[0])
        level, level_step = _neighbour_int(lua, node, CONFIG_LEVEL_FIELD)
        if level is None or not 0 <= level <= 1000:
            continue
        ident, _ident_step = _neighbour_int(lua, node, CONFIG_ID_FIELD)
        rows.append((level, need, ident, level_step))

    if not rows:
        return {}

    # 用多数行的 (Id - 等级) 作为"这确实是一行好感等级配置"的指纹
    with_id = [row for row in rows if row[2] is not None]
    offsets = Counter(ident - level for level, _need, ident, _step in with_id)
    if offsets:
        offset, votes = offsets.most_common(1)[0]
        if votes >= 2 and votes * 5 >= len(with_id) * 3:
            rows = [row for row in with_id if row[2] - row[0] == offset]

    # 同一等级若有多条候选, 取字段离 NeedExp 最近的那条(最可能同属一行)
    best: dict[int, tuple[int, int]] = {}
    for level, need, _ident, step in rows:
        current = best.get(level)
        if current is None or step < current[0]:
            best[level] = (step, need)
    return {level: need for level, (_step, need) in best.items()}


def _key_nodes(process, field: str) -> list[int]:
    """返回"值为 field 字符串的键槽地址"(键槽 = 节点地址 + 16)。"""
    encoded = field.encode("utf-8")
    nodes: list[int] = []
    seen: set[int] = set()
    for data_address in process.scan(encoded):
        object_address = data_address - 24
        header = process.try_read(object_address, 24)
        if header is None or header[8] != 4 or header[11] != len(encoded):
            continue
        if process.try_read(data_address, len(encoded) + 1) != encoded + b"\0":
            continue
        for reference in process.scan(struct.pack("<Q", object_address)):
            tag_raw = process.try_read(reference + 8, 4)
            if tag_raw is None or struct.unpack("<i", tag_raw)[0] not in STRING_TAGS:
                continue
            if reference % 8:
                continue
            if reference in seen:
                continue
            seen.add(reference)
            nodes.append(reference)
    return nodes


def _neighbour_int(lua: Lua53Reader, node: int, field: str,
                   span: int = 16) -> tuple[int | None, int]:
    """找同一行里字段 field 的整数值, 返回 (值, 与 node 的距离)。

    节点数组是连续的 32 字节单元, 字段离 ``NeedExp`` 越近越可能属于同一行,
    所以先试 ±1, 再 ±2 ……; 找不到返回 (None, span)。
    """
    for distance in range(1, span + 1):
        for step in (distance, -distance):
            sibling = node + step * 32
            key = _tvalue_or_none(lua, sibling + 16)
            if key is None or key.tag not in STRING_TAGS:
                continue
            try:
                name = lua.read_string(struct.unpack("<Q", key.raw_value)[0])
            except (OSError, ValueError, struct.error):
                continue
            if name != field:
                continue
            value = _tvalue_or_none(lua, sibling)
            if value is None or value.tag != TAG_INTEGER:
                continue
            return int(struct.unpack("<q", value.raw_value)[0]), distance
    return None, span


def _tvalue_or_none(lua: Lua53Reader, address: int):
    try:
        return lua.read_tvalue(address)
    except (OSError, ValueError, struct.error):
        return None


def _shallow_entries(lua: Lua53Reader, table: int) -> list[tuple[object, object]]:
    """读表的键值 TValue, 不递归解码表值(抽卡/角色表里有大量嵌套表)。

    返回 [(键, TValue)], 键只解码成 int/str。
    """
    lsize_node, size_array, array_ptr, node_ptr = lua.table_header(table)
    entries: list[tuple[object, object]] = []
    for index in range(size_array):
        value = _tvalue_or_none(lua, array_ptr + index * 16)
        if value is None or value.tag == 0:
            continue
        entries.append((index + 1, value))
    for index in range(1 << lsize_node):
        node = node_ptr + index * 32
        key = _tvalue_or_none(lua, node + 16)
        if key is None or key.tag == 0:
            continue
        value = _tvalue_or_none(lua, node)
        if value is None or value.tag == 0:
            continue
        entries.append((_decode_key(lua, key), value))
    return entries


def _decode_key(lua: Lua53Reader, key):
    if key.tag == TAG_INTEGER:
        return int(struct.unpack("<q", key.raw_value)[0])
    if key.tag in STRING_TAGS:
        try:
            return lua.read_string(struct.unpack("<Q", key.raw_value)[0])
        except (OSError, ValueError, struct.error):
            return None
    return None


def _field_tvalue(lua: Lua53Reader, table: int, field: str):
    try:
        return lua.get_table_field_tvalue(table, field)
    except (OSError, ValueError, struct.error):
        return None


def _read_int_fields(lua: Lua53Reader, table: int, names: tuple[str, ...]) -> dict[str, int]:
    """一次遍历节点数组, 取出多个整数字段。"""
    wanted = set(names)
    found: dict[str, int] = {}
    try:
        lsize_node, _size_array, _array_ptr, node_ptr = lua.table_header(table)
    except (OSError, ValueError, struct.error):
        return found
    for index in range(1 << lsize_node):
        if len(found) == len(wanted):
            break
        node = node_ptr + index * 32
        key = _tvalue_or_none(lua, node + 16)
        if key is None or key.tag not in STRING_TAGS:
            continue
        try:
            name = lua.read_string(struct.unpack("<Q", key.raw_value)[0])
        except (OSError, ValueError, struct.error):
            continue
        if name not in wanted:
            continue
        value = _tvalue_or_none(lua, node)
        if value is None:
            continue
        if value.tag == TAG_INTEGER:
            found[name] = int(struct.unpack("<q", value.raw_value)[0])
        elif value.tag == 1:  # Lua 布尔
            found[name] = int(bool(struct.unpack("<i", value.raw_value[:4])[0]))
    return found
