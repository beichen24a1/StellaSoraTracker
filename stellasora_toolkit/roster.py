# -*- coding: utf-8 -*-
"""只读读取角色的等级、突破、技能等级、天赋与纹章(游戏内叫 Equipment)。

数据位置(用真实客户端内存核对过, 2026-10 版本):

    _mapChar[<角色ID>] = {
        nId, nLevel, nAdvance, bIsFavorite,
        tbSkillLvs = {1: 1, 2: 1, 3: 10, 4: 8, 5: 1},
        ...
    }

    PlayerTalentData._tbCharTalentNode[<角色ID>] = {
        nMaxNormalCount = 50,   -- 天赋点上限
        nAllNormalCount = 11,   -- 已激活节点数
        tbActiveTalent  = {[节点ID] = true},
        nFirstGroup     = 13001,
    }
    PlayerTalentData._tbCharFateTalent[<角色ID>] = {1: 节点ID, ...}

    PlayerEquipmentData.tbCharEquipment[<角色ID>][<槽位1..3>][<方案1..3>] = {
        sName, sDesc, sIcon, nType, nGemId, nGenerateId, nRefreshId, bLock,
        tbUpgradeCount, tbAlterUpgradeCount,
        tbAffix, tbAlterAffix, tbSkillAffix, tbPotentialAffix,
        tbRandomAttr = {{AttrId, Value, CfgValue}, ...},
    }
    PlayerEquipmentData.tbSlotControl[<槽位>] = {Id, UnlockLevel}
    PlayerEquipmentData.tbCharSelectPreset[<角色ID>] = 当前方案

读取方式与好感度一致: 只读 ``ReadProcessMemory``, 先在 Lua 堆里按字段名找到
模块表的值, 再按角色 ID 逐层取字段; 不写游戏内存、不抓包。结果按 UID 单独存成
``exports/<UID>_roster.json``, 与抽卡归档、好感度文件互不影响。
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .catalog import traveler_name
from .lua53 import (
    TAG_BOOLEAN, TAG_FLOAT, TAG_INTEGER, TAG_TABLE, STRING_TAGS, Lua53Reader,
)

# 玩家数据里的模块字段
CHAR_FIELD = "_mapChar"
TALENT_FIELD = "_tbCharTalentNode"
FATE_FIELD = "_tbCharFateTalent"
EQUIP_FIELD = "tbCharEquipment"
SLOT_FIELD = "tbSlotControl"
PRESET_FIELD = "tbCharPreset"
SELECT_FIELD = "tbCharSelectPreset"
POTENTIAL_FIELD = "_tbCharPotential"

# 配置表注册表(ConfigData): 里面有 UIText / Talent 等所有静态配置
REGISTRY_FIELD = "DataTable"

ROSTER_SUFFIX = "_roster.json"
UNVERIFIED_NAME = "unverified"

# 纹章槽位名: 槽位 1/2/3 分别在角色 70/80/90 级解锁, 物品名后缀也按这个顺序。
# 注意 nType 在实例里是 1..3 的倒序标记(槽位 1 -> 3), 不能拿来当类型名。
SLOT_NAMES = {1: "尖章", 2: "方菱章", 3: "星闪章"}


@dataclass(frozen=True)
class Emblem:
    """一件纹章。类型 nType 1..3 对应尖章/方苞章/星闪章。"""

    slot: int
    preset: int
    active: bool
    name: str
    type: int
    gem_id: int
    generate_id: int
    refresh_id: int
    icon: str
    desc: str
    locked: bool
    upgrades: tuple[int, ...] = ()
    alter_upgrades: tuple[int, ...] = ()
    affixes: tuple[int, ...] = ()
    alter_affixes: tuple[int, ...] = ()
    skill_affixes: tuple[dict, ...] = ()
    potential_affixes: tuple[dict, ...] = ()
    affix_names: tuple[str, ...] = ()
    attrs: tuple[dict, ...] = ()
    index: int = 0

    @property
    def type_name(self) -> str:
        """类型名按槽位显示(物品名后缀与槽位一致, nType 是倒序的内部标记)。"""
        return self.slot_name

    @property
    def slot_name(self) -> str:
        return SLOT_NAMES.get(self.slot, f"槽位 {self.slot}")

    def as_dict(self) -> dict:
        return {
            "slot": self.slot,
            "slotName": self.slot_name,
            "index": self.index,
            "preset": self.preset,
            "active": self.active,
            "name": self.name,
            "type": self.type,
            "typeName": self.type_name,
            "gemId": self.gem_id,
            "generateId": self.generate_id,
            "refreshId": self.refresh_id,
            "icon": self.icon,
            "desc": self.desc,
            "locked": self.locked,
            "upgrades": list(self.upgrades),
            "alterUpgrades": list(self.alter_upgrades),
            "affixes": list(self.affixes),
            "alterAffixes": list(self.alter_affixes),
            "skillAffixes": [dict(item) for item in self.skill_affixes],
            "potentialAffixes": [dict(item) for item in self.potential_affixes],
            "affixNames": list(self.affix_names),
            "attrs": [dict(attr) for attr in self.attrs],
        }


@dataclass(frozen=True)
class Character:
    """单个旅人的养成数据。"""

    id: int
    name: str
    level: int
    advance: int
    favorite: bool
    skills: tuple[int, ...] = ()
    talent_active: int = 0
    talent_max: int = 0
    talent_nodes: tuple[int, ...] = ()
    talent_names: tuple[str, ...] = ()
    talent_descs: tuple[str, ...] = ()
    fate_nodes: tuple[int, ...] = ()
    emblems: tuple[Emblem, ...] = ()
    slots: tuple[dict, ...] = ()
    potentials: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "level": self.level,
            "advance": self.advance,
            "favorite": self.favorite,
            "skills": list(self.skills),
            "talent": {
                "active": self.talent_active,
                "max": self.talent_max,
                "nodes": list(self.talent_nodes),
                "names": list(self.talent_names),
                "descs": list(self.talent_descs),
                "fate": list(self.fate_nodes),
            },
            "emblems": [emblem.as_dict() for emblem in self.emblems],
            "slots": [dict(slot) for slot in self.slots],
            "potentials": {key: list(value) for key, value in self.potentials.items()},
        }


def cache_path(root: Path, uid: str) -> Path:
    """``exports/<UID>_roster.json``, 与抽卡归档、好感度文件分开。"""
    name = str(uid or "") if re.fullmatch(r"[0-9]{5,15}", str(uid or "")) else UNVERIFIED_NAME
    return Path(root) / f"{name}{ROSTER_SUFFIX}"


def save_cache(root: Path, uid: str, characters: list[Character]) -> dict:
    from .archive_layout import write_atomic

    owner = str(uid or "")
    payload = {
        "version": 1,
        "uid": owner,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "characters": [character.as_dict() for character in characters],
    }
    write_atomic(cache_path(root, owner), payload)
    return payload


def _cache_list(value) -> list:
    return value[:2000] if isinstance(value, list) else []


def _cache_ints(value) -> list[int]:
    return [int(item) for item in _cache_list(value)]


def _cache_text(value) -> str:
    return value[:10000] if isinstance(value, str) else ''


def _cache_number(value) -> float:
    number = float(value or 0)
    if not math.isfinite(number):
        raise ValueError('non-finite roster attribute')
    return number


def _cache_emblem(item: dict) -> dict:
    """Normalize every nested field consumed by the renderer, including old caches."""
    defaults = Emblem(1, 0, False, '', 0, 0, 0, 0, '', '', False).as_dict()
    result = {}
    for key, default in defaults.items():
        value = item.get(key, default)
        if type(default) is bool:
            result[key] = value is True
        elif type(default) is int:
            result[key] = int(value or 0)
        elif isinstance(default, str):
            result[key] = _cache_text(value)
    if not 1 <= result['slot'] <= 3:
        raise ValueError('invalid emblem slot')
    for key in ('upgrades', 'alterUpgrades', 'affixes', 'alterAffixes'):
        result[key] = _cache_ints(item.get(key))
    result['affixNames'] = [_cache_text(value) for value in _cache_list(item.get('affixNames'))]
    result['attrs'] = [
        {'attrId': int(attr.get('attrId') or 0), 'value': _cache_number(attr.get('value')),
         'cfgValue': _cache_number(attr.get('cfgValue')), 'name': _cache_text(attr.get('name'))}
        for attr in _cache_list(item.get('attrs')) if isinstance(attr, dict)
    ]
    for key in ('skillAffixes', 'potentialAffixes'):
        result[key] = [
            {'typeId': int(affix.get('typeId') or 0), 'id': int(affix.get('id') or 0),
             'level': int(affix.get('level') or 0), 'name': _cache_text(affix.get('name'))}
            for affix in _cache_list(item.get(key)) if isinstance(affix, dict)
        ]
    return result


def load_cache(path: Path) -> dict | None:
    try:
        if Path(path).stat().st_size > 8 * 1024 * 1024:
            return None
        payload = json.loads(Path(path).read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version", 1) != 1:
        return None
    characters = payload.get("characters")
    if not isinstance(characters, list):
        return None
    uid = payload.get('uid', '')
    if not isinstance(uid, str) or (uid and not re.fullmatch(r'[0-9]{5,15}', uid)):
        return None
    rows = []
    for entry in characters[:2000]:
        if not isinstance(entry, dict):
            continue
        try:
            talent = entry.get("talent") if isinstance(entry.get("talent"), dict) else {}
            potentials = entry.get('potentials') if isinstance(entry.get('potentials'), dict) else {}
            row = {
                "id": int(entry["id"]),
                "name": str(entry.get("name") or traveler_name(entry["id"])),
                "level": int(entry.get("level") or 0),
                "advance": int(entry.get("advance") or 0),
                "favorite": bool(entry.get("favorite")),
                "skills": _cache_ints(entry.get('skills')),
                "talent": {
                    "active": int(talent.get("active") or 0),
                    "max": int(talent.get("max") or 0),
                    "nodes": _cache_ints(talent.get('nodes')),
                    "names": [_cache_text(value) for value in _cache_list(talent.get('names'))],
                    "descs": [_cache_text(value) for value in _cache_list(talent.get('descs'))],
                    "fate": _cache_ints(talent.get('fate')),
                },
                "emblems": [_cache_emblem(item) for item in _cache_list(entry.get('emblems')) if isinstance(item, dict)],
                "slots": [{'slot': int(item.get('slot') or 0), 'name': _cache_text(item.get('name')),
                           'unlockLevel': int(item.get('unlockLevel') or 0)}
                          for item in _cache_list(entry.get('slots')) if isinstance(item, dict)],
                "potentials": {
                    str(group): [_cache_text(name) for name in _cache_list(names)]
                    for group, names in potentials.items()
                    if isinstance(names, list)
                },
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        rows.append(row)
    return {
        "uid": uid,
        "updatedAt": str(payload.get("updatedAt") or ""),
        "characters": rows,
    }


def latest_cache(root: Path) -> tuple[Path, dict] | None:
    folder = Path(root)
    try:
        files = sorted(
            (path for path in folder.glob(f"*{ROSTER_SUFFIX}") if path.is_file()),
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


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def read_roster(process, *, lua: Lua53Reader | None = None, progress=None) -> list[Character]:
    """读取全部旅人的等级/技能/天赋/纹章, 按等级从高到低排序。

    ``process`` 与好感度读取一致, 只需要 read/try_read/scan/scan_any/regions。
    纹章、天赋表缺失(没打开过对应界面)时, 对应字段留空, 不影响等级和技能。
    """
    report = progress or (lambda _message: None)
    lua = lua or Lua53Reader(process)
    report("正在定位角色、天赋与纹章数据表（需要几秒）")
    tables = _find_field_tables(process, lua)
    char_map = tables.get(CHAR_FIELD)
    if char_map is None:
        raise LookupError(
            "没有在游戏内存里找到角色数据表 _mapChar。\n\n"
            "请确认：1) 游戏已登录并进入主界面；2) 工具以管理员身份运行；"
            "3) 打开过一次「角色」界面让客户端把角色数据加载进内存。"
        )
    report(f"已定位 {len(tables)} 张数据表，正在解析角色与纹章")
    report("正在加载属性与天赋文本")
    registry = _find_config_registry(process, lua)
    texts = _load_texts(lua, registry)
    attr_config = _load_attr_config(lua, registry)
    attr_index = {attr_id: int(row.get("index") or 0)
                  for attr_id, row in attr_config.items() if row.get("index")}

    talent_map = tables.get(TALENT_FIELD)
    fate_map = tables.get(FATE_FIELD)
    equip_map = tables.get(EQUIP_FIELD)
    slot_control = tables.get(SLOT_FIELD)
    preset_map = tables.get(PRESET_FIELD)
    select_map = tables.get(SELECT_FIELD)
    potential_map = tables.get(POTENTIAL_FIELD)

    slots = _read_slots(lua, slot_control)
    active_presets = _read_active_presets(lua, select_map)

    rows: list[Character] = []
    for key, value in _entries(lua, char_map):
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        fields = _read_int_fields(lua, address, ("nId", "nLevel", "nAdvance", "bIsFavorite"))
        character_id = fields.get("nId")
        if character_id is None:
            character_id = key if isinstance(key, int) else None
        if character_id is None:
            continue
        character_id = int(character_id)
        skills = _read_int_array(lua, address, "tbSkillLvs")

        talent_active = talent_max = 0
        talent_nodes: tuple[int, ...] = ()
        talent_entry = _entry_value(lua, talent_map, character_id)
        if talent_entry is not None and talent_entry.tag == TAG_TABLE:
            talent_address = _u64(talent_entry.raw_value)
            counts = _read_int_fields(lua, talent_address, ("nAllNormalCount", "nMaxNormalCount"))
            talent_active = counts.get("nAllNormalCount", 0)
            talent_max = counts.get("nMaxNormalCount", 0)
            active_value = _field_value(lua, talent_address, "tbActiveTalent")
            if active_value is not None and active_value.tag == TAG_TABLE:
                nodes = []
                for node, enabled in _entries(lua, _u64(active_value.raw_value)):
                    if enabled.tag != TAG_BOOLEAN:
                        continue
                    try:
                        nodes.append(int(node))
                    except (TypeError, ValueError):
                        continue
                talent_nodes = tuple(sorted(nodes))

        fate_nodes: tuple[int, ...] = ()
        fate_entry = _entry_value(lua, fate_map, character_id)
        if fate_entry is not None and fate_entry.tag == TAG_TABLE:
            fate_nodes = tuple(_int_array(lua, _u64(fate_entry.raw_value)))

        talent_names = tuple(
            _clean_text(texts.get(f"Talent.{node}.1")) for node in talent_nodes
        )
        talent_descs = tuple(
            _clean_text(texts.get(f"Talent.{node}.2")) for node in talent_nodes
        )

        preset = active_presets.get(character_id, 1)
        potentials = _read_potential_lists(lua, potential_map, character_id)
        potential_names = {
            group: tuple(_clean_text(texts.get(f"Item.{node}.1")) for node in nodes)
            for group, nodes in potentials.items()
        }
        emblems = _read_emblems(lua, equip_map, preset_map, character_id, preset, texts,
                                attr_index, attr_config, potentials)

        rows.append(
            Character(
                id=character_id,
                name=traveler_name(character_id),
                level=fields.get("nLevel", 0),
                advance=fields.get("nAdvance", 0),
                favorite=bool(fields.get("bIsFavorite", 0)),
                skills=tuple(skills),
                talent_active=talent_active,
                talent_max=talent_max,
                talent_nodes=talent_nodes,
                talent_names=talent_names,
                talent_descs=talent_descs,
                fate_nodes=fate_nodes,
                emblems=tuple(emblems),
                slots=slots,
                potentials=potential_names,
            )
        )
    rows.sort(key=lambda item: (-item.level, -item.advance, item.id))
    report(f"解析完成：{len(rows)} 位旅人，{sum(len(row.emblems) for row in rows)} 件纹章")
    return rows


# ---------------------------------------------------------------------------
# 内部实现: 定位模块表
# ---------------------------------------------------------------------------

def _heap_regions(process):
    regions = process.regions()
    heap = [region for region in regions if not region.is_image]
    return heap or regions


_TAG_RE = re.compile(r"<[^>]+>")
_PARAM_RE = re.compile(r"&Param\d+&")


def _clean_text(text: str | None) -> str:
    """去掉富文本标签, 参数占位符换成省略号。"""
    if not text:
        return ""
    return _PARAM_RE.sub("…", _TAG_RE.sub("", text)).strip()


def _find_config_registry(process, lua: Lua53Reader) -> int | None:
    """定位 ConfigData 注册表: 值是含 ``UIText`` / ``Item`` 字段的表。"""
    objects = _string_objects(process, [REGISTRY_FIELD])
    addresses = objects.get(REGISTRY_FIELD) or []
    if not addresses:
        return None
    object_address = addresses[0]
    for reference in process.scan(struct.pack("<Q", object_address), _heap_regions(process)):
        if reference % 8:
            continue
        try:
            key = lua.read_tvalue(reference)
            value = lua.read_tvalue(reference - 16)
        except (OSError, ValueError, struct.error):
            continue
        if key.tag not in STRING_TAGS or _u64(key.raw_value) != object_address:
            continue
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        try:
            keys = {entry for entry, _item in _entries(lua, address)}
        except (OSError, ValueError, struct.error):
            continue
        if {"UIText", "Item"} <= keys:
            return address
    return None


def _config_lang(lua: Lua53Reader, registry: int, name: str) -> dict[str, str]:
    """``<表>.meta.lang`` 是解码好的文本; ``raw`` 是 protobuf 字节。"""
    value = _field_value(lua, registry, name)
    if value is None or value.tag != TAG_TABLE:
        return {}
    config = _u64(value.raw_value)
    meta = _field_value(lua, config, "meta")
    if meta is None or meta.tag != TAG_TABLE:
        return {}
    lang = _field_value(lua, _u64(meta.raw_value), "lang")
    if lang is None or lang.tag != TAG_TABLE:
        return {}
    try:
        entries = _entries(lua, _u64(lang.raw_value))
    except (OSError, ValueError, struct.error):
        return {}
    texts: dict[str, str] = {}
    for key, item in entries:
        if not isinstance(key, str) or item.tag not in STRING_TAGS:
            continue
        try:
            texts[key] = lua.read_string(_u64(item.raw_value))
        except (OSError, ValueError, struct.error):
            continue
    return texts


def _load_texts(lua: Lua53Reader, registry: int | None) -> dict[str, str]:
    if registry is None:
        return {}
    return {
        **_config_lang(lua, registry, "UIText"),
        **_config_lang(lua, registry, "Talent"),
        **_config_lang(lua, registry, "Item"),
    }


def _lua_bytes(lua: Lua53Reader, address: int) -> bytes:
    """按 Lua 字符串对象头取原始字节(protobuf 不能被 UTF-8 解码后再还原)。"""
    memory = lua.memory
    header = memory.read(address, 24)
    gc_tag = header[8]
    if gc_tag == 4:
        length = header[11]
    elif gc_tag == 20:
        length = struct.unpack_from("<Q", header, 16)[0]
    else:
        raise ValueError("not a Lua string")
    if length < 0 or length > 4 * 1024 * 1024:
        raise ValueError("invalid Lua string length")
    return memory.read(address + 24, length)


def _decode_varint(data: bytes, index: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7


def _decode_proto(data: bytes) -> dict[int, object]:
    """极简 protobuf 解码: 只取标量字段与字符串字段。"""
    fields: dict[int, object] = {}
    index = 0
    while index < len(data):
        key, index = _decode_varint(data, index)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, index = _decode_varint(data, index)
            fields[number] = value
        elif wire == 2:
            length, index = _decode_varint(data, index)
            chunk = data[index:index + length]
            index += length
            fields[number] = chunk
        elif wire == 1:
            index += 8
        elif wire == 5:
            index += 4
        else:
            break
    return fields


def _load_attr_config(lua: Lua53Reader, registry: int | None) -> dict[int, dict]:
    """``CharGemAttrValue.raw``: 属性 ID -> {index, typeId, value}。"""
    if registry is None:
        return {}
    value = _field_value(lua, registry, "CharGemAttrValue")
    if value is None or value.tag != TAG_TABLE:
        return {}
    config = _u64(value.raw_value)
    raw = _field_value(lua, config, "raw")
    if raw is None or raw.tag != TAG_TABLE:
        return {}
    result: dict[int, dict] = {}
    try:
        entries = _entries(lua, _u64(raw.raw_value))
    except (OSError, ValueError, struct.error):
        return {}
    for key, item in entries:
        if item.tag not in STRING_TAGS:
            continue
        try:
            attr_id = int(key)
        except (TypeError, ValueError):
            continue
        try:
            fields = _decode_proto(_lua_bytes(lua, _u64(item.raw_value)))
        except (OSError, ValueError, IndexError, struct.error):
            continue
        raw_value = fields.get(6)
        text = ""
        if isinstance(raw_value, bytes):
            text = raw_value.decode("utf-8", "replace")
        elif isinstance(raw_value, str):
            text = raw_value
        try:
            number = float(text) if text else 0.0
        except ValueError:
            number = 0.0
        result[attr_id] = {
            "index": fields.get(4) if isinstance(fields.get(4), int) else 0,
            "typeId": fields.get(2) if isinstance(fields.get(2), int) else 0,
            "value": number,
        }
    return result


def _load_attr_index(lua: Lua53Reader, registry: int | None) -> dict[int, int]:
    """``CharGemAttrValue.raw``: 属性 ID -> 实际枚举值(字段 4)。

    纹章属性 ID 的前两位只是"档位分组", 真正决定属性名的是行里的 index
    (例如 202 -> 1 攻击、804 -> 6 暴击率、10804 -> 57 技能伤害)。
    """
    return {
        attr_id: int(row.get("index") or 0)
        for attr_id, row in _load_attr_config(lua, registry).items()
        if row.get("index")
    }


def _attr_name(texts: dict[str, str], attr_index: dict[int, int], attr_id: int,
               slot: int = 0) -> str:
    """属性名: 优先用配置行里的枚举值, 没有行时退回 ``AttrId // 100``。"""
    try:
        attr_id = int(attr_id)
    except (TypeError, ValueError):
        return ""
    # 能量获取效率在尖章是"援护", 方菱/星闪是"主控"
    if 8600 <= attr_id < 8800:
        key = "UIText.Enums_Effect_86.1" if slot == 1 else "UIText.Enums_Effect_87.1"
        name = texts.get(key)
        if name:
            return _clean_text(name)
    if 6300 <= attr_id < 6400:
        name = texts.get("UIText.Attr_Hp.1")
        if name:
            return _clean_text(name)
    index = attr_index.get(attr_id)
    if index is not None:
        name = texts.get(f"UIText.Enums_Effect_{index}.1")
        if name:
            return _clean_text(name)
    return _clean_text(texts.get(f"UIText.Enums_Effect_{attr_id // 100}.1"))


def _string_objects(process, names: list[str]) -> dict[str, list[int]]:
    """一次扫描, 找出这些字段名的 Lua 短字符串对象。"""
    encoded = {name.encode("ascii"): name for name in names}
    found: dict[str, list[int]] = {name: [] for name in names}
    for hit, needle in process.scan_any(list(encoded), _heap_regions(process)):
        name = encoded[needle]
        for back in range(0, 10):
            object_address = hit - 24 - back
            header = process.try_read(object_address, 24)
            if header is None or header[8] != 4:      # 4 = 短字符串
                continue
            length = header[11]
            raw = process.try_read(object_address + 24, length + 1)
            if raw is None or raw[length:length + 1] != b"\0":
                continue
            if raw[:length] != needle:
                continue
            if object_address not in found[name]:
                found[name].append(object_address)
            break
    return found


def _find_field_tables(process, lua: Lua53Reader) -> dict[str, int]:
    """按字段名找模块里的"值表"。

    只做两次内存遍历(一次找字段名字符串、一次找引用它的键槽), 不做全堆表头扫描,
    所以刷新速度与好感度读取是同一档。命中后用结构校验排除同名的类定义/配置。
    """
    names = [CHAR_FIELD, TALENT_FIELD, FATE_FIELD, EQUIP_FIELD, SLOT_FIELD, PRESET_FIELD,
             SELECT_FIELD, POTENTIAL_FIELD]
    objects = _string_objects(process, names)
    pointers: dict[bytes, str] = {}
    for name, addresses in objects.items():
        # Lua 5.3 的短字符串是驻留(intern)的, 同名字段在内存里只有一个对象;
        # 只取一个能把第二轮扫描的 pattern 数压到最少。
        for address in addresses[:1]:
            pointers[struct.pack("<Q", address)] = name
    candidates: dict[str, list[int]] = {name: [] for name in names}
    if not pointers:
        return {}
    for reference, pattern in process.scan_any(list(pointers), _heap_regions(process)):
        name = pointers[pattern]
        if reference % 8:
            continue
        try:
            key = lua.read_tvalue(reference)
        except (OSError, ValueError, struct.error):
            continue
        if key.tag not in STRING_TAGS:
            continue
        if _u64(key.raw_value) != _u64(pattern):
            continue
        try:
            value = lua.read_tvalue(reference - 16)      # 键槽 - 16 = 值槽
        except (OSError, ValueError, struct.error):
            continue
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        if address not in candidates[name]:
            candidates[name].append(address)

    validators = {
        CHAR_FIELD: _looks_like_char_map,
        TALENT_FIELD: _looks_like_talent_map,
        FATE_FIELD: _looks_like_int_array_map,
        EQUIP_FIELD: _looks_like_equip_map,
        SLOT_FIELD: _looks_like_slot_control,
        PRESET_FIELD: _looks_like_preset_map,
        SELECT_FIELD: _looks_like_int_map,
        POTENTIAL_FIELD: _looks_like_potential_map,
    }
    result: dict[str, int] = {}
    for name, addresses in candidates.items():
        for address in addresses:
            try:
                if validators[name](lua, address):
                    result[name] = address
                    break
            except (OSError, ValueError, struct.error):
                continue
    return result


def _top_entries(lua: Lua53Reader, table: int, limit: int = 3) -> list[tuple[object, object]]:
    """取表的前几条, 用来做结构校验(不展开嵌套)。"""
    return _entries(lua, table)[:limit]


def _looks_like_char_map(lua: Lua53Reader, table: int) -> bool:
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        if _field_value(lua, address, "nLevel") is not None:
            return True
    return False


def _looks_like_talent_map(lua: Lua53Reader, table: int) -> bool:
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        if _field_value(lua, address, "tbActiveTalent") is not None:
            return True
        if _field_value(lua, address, "nMaxNormalCount") is not None:
            return True
    return False


def _looks_like_equip_map(lua: Lua53Reader, table: int) -> bool:
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        for _slot, slot_value in _top_entries(lua, _u64(value.raw_value)):
            if slot_value.tag == TAG_TABLE:
                return True
    return False


def _looks_like_slot_control(lua: Lua53Reader, table: int) -> bool:
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        if _field_value(lua, _u64(value.raw_value), "UnlockLevel") is not None:
            return True
    return False


def _looks_like_preset_map(lua: Lua53Reader, table: int) -> bool:
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        for _preset, preset_value in _top_entries(lua, address):
            if preset_value.tag != TAG_TABLE:
                continue
            if _field_value(lua, _u64(preset_value.raw_value), "tbSlot") is not None:
                return True
    return False


def _looks_like_int_map(lua: Lua53Reader, table: int) -> bool:
    entries = _top_entries(lua, table)
    return bool(entries) and all(value.tag == TAG_INTEGER for _key, value in entries)


def _looks_like_int_array_map(lua: Lua53Reader, table: int) -> bool:
    """{角色ID: {1: 节点, 2: 节点, ...}} 形状(命运天赋)。"""
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        inner = _top_entries(lua, _u64(value.raw_value))
        if inner and all(item.tag == TAG_INTEGER for _inner_key, item in inner):
            return True
    return False


def _looks_like_potential_map(lua: Lua53Reader, table: int) -> bool:
    """{角色ID: {assist = {...}, master = {...}}} 形状(角色潜能)。"""
    for _key, value in _top_entries(lua, table):
        if value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        if (_field_value(lua, address, "assist") is not None
                or _field_value(lua, address, "master") is not None):
            return True
    return False


# ---------------------------------------------------------------------------
# 内部实现: 取字段
# ---------------------------------------------------------------------------

def _u64(raw: bytes) -> int:
    return struct.unpack("<Q", raw)[0]


def _i64(raw: bytes) -> int:
    return struct.unpack("<q", raw)[0]


def _decode_key(lua: Lua53Reader, key):
    if key.tag == TAG_INTEGER:
        return _i64(key.raw_value)
    if key.tag in STRING_TAGS:
        try:
            return lua.read_string(_u64(key.raw_value))
        except (OSError, ValueError, struct.error):
            return None
    return None


def _entries(lua: Lua53Reader, table: int) -> list[tuple[object, object]]:
    lsize_node, size_array, array_ptr, node_ptr = lua.table_header(table)
    result: list[tuple[object, object]] = []
    for index in range(size_array):
        value = lua.read_tvalue(array_ptr + index * 16)
        if value.tag == 0:
            continue
        result.append((index + 1, value))
    for index in range(1 << lsize_node):
        node = node_ptr + index * 32
        key = lua.read_tvalue(node + 16)
        if key.tag == 0:
            continue
        value = lua.read_tvalue(node)
        if value.tag == 0:
            continue
        result.append((_decode_key(lua, key), value))
    return result


def _field_value(lua: Lua53Reader, table: int, field: str):
    try:
        return lua.get_table_field_tvalue(table, field)
    except (OSError, ValueError, struct.error):
        return None


def _read_int_fields(lua: Lua53Reader, table: int, names: tuple[str, ...]) -> dict[str, int]:
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
        key = lua.read_tvalue(node + 16)
        if key.tag not in STRING_TAGS:
            continue
        try:
            name = lua.read_string(_u64(key.raw_value))
        except (OSError, ValueError, struct.error):
            continue
        if name not in wanted:
            continue
        value = lua.read_tvalue(node)
        if value.tag == TAG_INTEGER:
            found[name] = _i64(value.raw_value)
        elif value.tag == TAG_BOOLEAN:
            found[name] = int(bool(struct.unpack("<i", value.raw_value[:4])[0]))
    return found


def _int_array(lua: Lua53Reader, table: int) -> list[int]:
    values: list[int] = []
    for _key, value in _entries(lua, table):
        if value.tag == TAG_INTEGER:
            values.append(_i64(value.raw_value))
    return values


def _read_int_array(lua: Lua53Reader, table: int, field: str) -> list[int]:
    value = _field_value(lua, table, field)
    if value is None or value.tag != TAG_TABLE:
        return []
    return _int_array(lua, _u64(value.raw_value))


def _entry_value(lua: Lua53Reader, table: int | None, key: int):
    if table is None:
        return None
    for entry_key, value in _entries(lua, table):
        if entry_key == key:
            return value
    return None


def _read_slots(lua: Lua53Reader, table: int | None) -> tuple[dict, ...]:
    if table is None:
        return ()
    slots: dict[int, int] = {}
    for key, value in _entries(lua, table):
        if not isinstance(key, int) or value.tag != TAG_TABLE:
            continue
        address = _u64(value.raw_value)
        unlock = _read_int_fields(lua, address, ("UnlockLevel",))
        slots[key] = unlock.get("UnlockLevel", 0)
    return tuple({"slot": slot, "name": SLOT_NAMES.get(slot, f"槽位 {slot}"),
                  "unlockLevel": level} for slot, level in sorted(slots.items()))


def _read_active_presets(lua: Lua53Reader, table: int | None) -> dict[int, int]:
    if table is None:
        return {}
    result: dict[int, int] = {}
    for key, value in _entries(lua, table):
        if isinstance(key, int) and value.tag == TAG_INTEGER:
            result[key] = _i64(value.raw_value)
    return result


def _read_potential_lists(lua: Lua53Reader, potential_map: int | None,
                          character_id: int) -> dict[str, tuple[int, ...]]:
    """角色的潜能列表(来自玩家数据 ``_tbCharPotential``)。

    每组按潜能 ID 升序; 前 4 个是"专有潜能", 后面是"通用潜能"; 主控/支援都有的
    是"通用潜能"(CommonPotentialIds)。
    """
    empty = {"master_all": (), "assist_all": (), "master_specific": (), "master_normal": (),
             "assist_specific": (), "assist_normal": (), "common": ()}
    entry = _entry_value(lua, potential_map, character_id)
    if entry is None or entry.tag != TAG_TABLE:
        return empty
    master: list[int] = []
    assist: list[int] = []
    for branch_key, branch_value in _entries(lua, _u64(entry.raw_value)):
        if branch_value.tag != TAG_TABLE:
            continue
        target = master if branch_key == "master" else assist if branch_key == "assist" else None
        if target is None:
            continue
        for _group_key, group_value in _entries(lua, _u64(branch_value.raw_value)):
            if group_value.tag != TAG_TABLE:
                continue
            for _node_key, node_value in _entries(lua, _u64(group_value.raw_value)):
                if node_value.tag != TAG_TABLE:
                    continue
                fields = _read_int_fields(lua, _u64(node_value.raw_value), ("nId",))
                node_id = fields.get("nId")
                if isinstance(node_id, int) and node_id not in target:
                    target.append(node_id)
    master.sort()
    assist.sort()
    common = set(master) & set(assist)
    master_only = [node for node in master if node not in common]
    assist_only = [node for node in assist if node not in common]
    return {
        "master_all": tuple(master),
        "assist_all": tuple(assist),
        "master_specific": tuple(master_only[:4]),
        "master_normal": tuple(master_only[4:]),
        "assist_specific": tuple(assist_only[:4]),
        "assist_normal": tuple(assist_only[4:]),
        "common": tuple(sorted(common)),
    }


def _preset_slots(lua: Lua53Reader, preset_map: int | None, character_id: int,
                  active_preset: int) -> dict[int, int]:
    """方案 -> {槽位: 纹章实例序号}; 实例存在 tbCharEquipment[角色][槽位][序号]。"""
    entry = _entry_value(lua, preset_map, character_id)
    if entry is None or entry.tag != TAG_TABLE:
        return {}
    preset_entry = _entry_value(lua, _u64(entry.raw_value), active_preset)
    if preset_entry is None or preset_entry.tag != TAG_TABLE:
        return {}
    slot_value = _field_value(lua, _u64(preset_entry.raw_value), "tbSlot")
    if slot_value is None or slot_value.tag != TAG_TABLE:
        return {}
    result: dict[int, int] = {}
    for slot_key, value in _entries(lua, _u64(slot_value.raw_value)):
        if isinstance(slot_key, int) and value.tag == TAG_INTEGER:
            result[slot_key] = _u64(value.raw_value)
    return result


def _read_emblems(lua: Lua53Reader, equip_map: int | None, preset_map: int | None,
                  character_id: int, active_preset: int, texts: dict[str, str],
                  attr_index: dict[int, int], attr_config: dict[int, dict],
                  potentials: dict[str, tuple[int, ...]]) -> list[Emblem]:
    char_slots = _entry_value(lua, equip_map, character_id)
    if char_slots is None or char_slots.tag != TAG_TABLE:
        return []
    slot_indices = _preset_slots(lua, preset_map, character_id, active_preset)
    emblems: list[Emblem] = []
    for slot_key, slot_value in _entries(lua, _u64(char_slots.raw_value)):
        if not isinstance(slot_key, int) or slot_value.tag != TAG_TABLE:
            continue
        # 该槽位所有刷出的实例都读出来; 方案 tbSlot 指向的那件标记为装备中
        equipped_index = slot_indices.get(slot_key, 1)
        for index_key, emblem_value in _entries(lua, _u64(slot_value.raw_value)):
            if not isinstance(index_key, int) or emblem_value.tag != TAG_TABLE:
                continue
            emblem = _read_emblem(lua, _u64(emblem_value.raw_value),
                                  slot_key, active_preset, index_key,
                                  index_key == equipped_index, texts, attr_index,
                                  attr_config, potentials)
            if emblem is not None:
                emblems.append(emblem)
    emblems.sort(key=lambda item: (item.slot, not item.active, item.index))
    return emblems


def _read_emblem(lua: Lua53Reader, address: int, slot: int, preset: int, index: int,
                 active: bool, texts: dict[str, str],
                 attr_index: dict[int, int], attr_config: dict[int, dict],
                 potentials: dict[str, tuple[int, ...]]) -> Emblem | None:
    fields = _read_int_fields(
        lua, address,
        ("nType", "nGemId", "nGenerateId", "nRefreshId", "bLock"),
    )
    name = _read_string_field(lua, address, "sName")
    if not name:
        return None
    random_attrs = []
    random_attr = _field_value(lua, address, "tbRandomAttr")
    if random_attr is not None and random_attr.tag == TAG_TABLE:
        for _key, value in _entries(lua, _u64(random_attr.raw_value)):
            if value.tag != TAG_TABLE:
                continue
            random_attrs.append(_read_attr(lua, _u64(value.raw_value), texts, attr_index, slot))
    affixes = tuple(_read_int_array(lua, address, "tbAffix"))
    skill_rows = _read_affix_rows(lua, address, "tbSkillAffix")
    potential_rows = _read_affix_rows(lua, address, "tbPotentialAffix")
    skill_families = {int(row.get("TypeId", 0)) for row in skill_rows}
    potential_ids = {int(row.get("Id", 0)) for row in potential_rows}

    # 属性 = tbAffix 的 2/3/4 号位(技能/潜力词条位除外), 随机到的用 tbRandomAttr 的数值,
    # 没随机到的(如固定的生命)用配置表里的值。
    by_family: dict[int, dict] = {}
    for attr in random_attrs:
        by_family.setdefault(int(attr.get("attrId", 0)) // 10, attr)
    attrs: list[dict] = []
    used: set[int] = set()
    for affix_id in affixes:
        if not affix_id or affix_id // 100 in skill_families or affix_id in potential_ids:
            continue
        match = by_family.get(affix_id // 10)
        if match is not None and match["attrId"] not in used:
            attrs.append(match)
            used.add(match["attrId"])
        elif affix_id in attr_config:
            config = attr_config[affix_id]
            attrs.append({
                "attrId": affix_id,
                "value": float(config.get("value") or 0),
                "cfgValue": float(config.get("value") or 0),
                "name": _attr_name(texts, attr_index, affix_id, slot),
            })
    for attr in random_attrs:
        if attr["attrId"] not in used:
            attrs.append(attr)
            used.add(attr["attrId"])

    skill_affixes = tuple(
        _skill_affix_detail(row, texts) for row in skill_rows
    )
    potential_affixes = tuple(
        _potential_affix_detail(row, texts, potentials)
        for row in potential_rows
    )
    return Emblem(
        slot=slot,
        preset=preset,
        active=active,
        name=name,
        type=int(fields.get("nType", 0)),
        gem_id=int(fields.get("nGemId", 0)),
        generate_id=int(fields.get("nGenerateId", 0)),
        refresh_id=int(fields.get("nRefreshId", 0)),
        icon=_read_string_field(lua, address, "sIcon"),
        desc=_read_string_field(lua, address, "sDesc"),
        locked=bool(fields.get("bLock", 0)),
        upgrades=tuple(_read_int_array(lua, address, "tbUpgradeCount")),
        alter_upgrades=tuple(_read_int_array(lua, address, "tbAlterUpgradeCount")),
        affixes=affixes,
        alter_affixes=tuple(_read_int_array(lua, address, "tbAlterAffix")),
        skill_affixes=skill_affixes,
        potential_affixes=potential_affixes,
        affix_names=tuple(attr.get("name") or "" for attr in attrs),
        attrs=tuple(attrs),
        index=index,
    )


def _read_affix_rows(lua: Lua53Reader, address: int, field: str) -> list[dict]:
    """技能/潜力词条: 每项是一行 {TypeId, Id, Rarity, AttrType…, OverlockCount}。"""
    value = _field_value(lua, address, field)
    if value is None or value.tag != TAG_TABLE:
        return []
    rows: list[dict] = []
    for _key, item in _entries(lua, _u64(value.raw_value)):
        if item.tag != TAG_TABLE:
            continue
        rows.append(_read_int_fields(
            lua, _u64(item.raw_value),
            ("TypeId", "Id", "Rarity", "AttrTypeFirstSubtype", "AttrTypeSecondSubtype",
             "OverlockCount", "Tag", "Level"),
        ))
    return rows


def _skill_affix_detail(row: dict, texts: dict[str, str]) -> dict:
    """技能词条: AttrTypeFirstSubtype 1..4 = 普攻/主控/援护/绝招, Id 后两位是等级。"""
    subtype = int(row.get("AttrTypeFirstSubtype", 0))
    level = int(row.get("Id", 0)) % 100
    kind = _clean_text(texts.get(f"UIText.Char_Skill_Type_{subtype}.1"))
    name = f"{kind}等级提升 +{level}级" if kind else f"技能等级提升 +{level}级"
    return {
        "typeId": int(row.get("TypeId", 0)),
        "id": int(row.get("Id", 0)),
        "level": level,
        "name": name,
    }


def _potential_affix_detail(row: dict, texts: dict[str, str],
                            potentials: dict[str, tuple[int, ...]]) -> dict:
    """潜力词条: Tag 3/4/5 = 主控/支援/通用潜能, Level 是提升级数。

    Id 的编码是 ``分组 * 100 + 节点序号``: 40 = 主控潜能列表, 54 = 主控/支援共有的
    通用潜能列表; 序号按潜能 ID 升序(1 起)。
    """
    tag = int(row.get("Tag", 0))
    level = int(row.get("Level", 0)) or int(row.get("Id", 0)) % 100
    kind = _clean_text(texts.get(f"UIText.Equipment_AttrTag_{tag}.1")) or "潜能"
    identifier = int(row.get("Id", 0))
    subtype = int(row.get("AttrTypeFirstSubtype", 0))
    # AttrTypeFirstSubtype 是"潜能编号"(EffectDesc 里的 PotentialN / Word 70NN),
    # 对应角色潜能 ID 的末两位: 13 -> 514413, 42 -> 514442 ...
    all_ids = list(dict.fromkeys(
        tuple(potentials.get("master_all", ())) + tuple(potentials.get("assist_all", ()))))
    target = next((node for node in all_ids if node % 100 == subtype), None)
    if target is None and subtype:
        target = next((node for node in all_ids if node % 1000 == subtype), None)
    if target is None:
        group, index = identifier // 100, identifier % 100 - 1
        group_lists = {
            40: "master_all",
            41: "master_specific",
            46: "master_normal",
            47: "assist_specific",
            48: "assist_normal",
            54: "common",
        }
        list_name = group_lists.get(group)
        items = potentials.get(list_name, ()) if list_name else ()
        target = items[index] if 0 <= index < len(items) else None
    potential_name = _clean_text(texts.get(f"Item.{target}.1")) if target else ""
    # 界面上只显示词条的主要内容(潜能名 + 等级), 分类放在 category 里备用
    name = (f"{potential_name}等级 +{level}" if potential_name
            else f"{kind}等级 +{level}")
    return {
        "typeId": int(row.get("TypeId", 0)),
        "id": identifier,
        "level": level,
        "tag": tag,
        "category": kind,
        "potentialId": target,
        "potentialName": potential_name,
        "name": name,
    }


def _read_string_field(lua: Lua53Reader, table: int, field: str) -> str:
    value = _field_value(lua, table, field)
    if value is None or value.tag not in STRING_TAGS:
        return ""
    try:
        return lua.read_string(_u64(value.raw_value))
    except (OSError, ValueError, struct.error):
        return ""


def _read_attr(lua: Lua53Reader, table: int, texts: dict[str, str] | None = None,
               attr_index: dict[int, int] | None = None, slot: int = 0) -> dict:
    values = _read_int_fields(lua, table, ("AttrId",))
    attr = {"attrId": values.get("AttrId", 0), "value": 0, "cfgValue": 0,
            "name": _attr_name(texts or {}, attr_index or {}, values.get("AttrId", 0), slot)}
    for field in ("Value", "CfgValue"):
        value = _field_value(lua, table, field)
        if value is None:
            continue
        if value.tag == TAG_INTEGER:
            attr["value" if field == "Value" else "cfgValue"] = _i64(value.raw_value)
        elif value.tag == TAG_FLOAT:
            attr["value" if field == "Value" else "cfgValue"] = struct.unpack("<d", value.raw_value)[0]
    return attr
