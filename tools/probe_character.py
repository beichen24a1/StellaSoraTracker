# -*- coding: utf-8 -*-
"""只读探针: 枚举玩家数据表里与「角色 / 纹章 / 天赋」相关的字段结构。

用途
----
好感度读取已经证明 ``_mapChar`` 能定位到; 但要新增「等级 / 技能等级 / 纹章 /
天赋」, 必须先知道游戏当前版本把这些数据放在哪张表、字段叫什么。这个脚本只读
内存, 把玩家数据根表的字段名、角色子表的字段名、以及疑似纹章/天赋子表的结构
打成 JSON, 供适配时对照。

用法(游戏已登录, 并且打开过角色页和纹章页):
    python tools/probe_character.py              # 没有管理员权限时自动请求提权
    python tools/probe_character.py --pid 1234   # 多开时指定进程
    python tools/probe_character.py --no-elevate # 已在管理员终端里直接跑

输出 build/character_probe.json; 不写游戏内存、不改 exports、不联网。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import re
import struct
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stellasora_toolkit import server_config  # noqa: E402
from stellasora_toolkit.discovery import LuaTableDiscovery  # noqa: E402
from stellasora_toolkit.lua53 import Lua53Reader, TValue  # noqa: E402
from stellasora_toolkit.process import (  # noqa: E402
    RemoteProcess, find_process_id, running_processes,
)

TAG_NIL = 0
TAG_BOOLEAN = 1
TAG_FLOAT = 3
TAG_INTEGER = 0x13
TAG_SHORT_STRING = 0x44
TAG_LONG_STRING = 0x54
TAG_TABLE = 0x45
STRING_TAGS = {TAG_SHORT_STRING, TAG_LONG_STRING}

# 根表里值得展开的字段名(正则): 纹章/天赋/技能/词条
SUSPECT_FIELD = re.compile(r"(?i)talent|skill|gem|emblem|crest|affix|potential|char")
# 内存里出现的字段名候选(用于兜底: 根表里没有时看看还有哪些名字)
NAME_NEEDLES = [b"Talent", b"Gem", b"Emblem", b"Crest", b"Skill", b"Affix", b"Equip", b"Potential"]


def _u64(raw: bytes) -> int:
    return struct.unpack("<Q", raw)[0]


def _i64(raw: bytes) -> int:
    return struct.unpack("<q", raw)[0]


class Summarizer:
    """把 Lua 值转成可读的 JSON 片段, 带全局预算, 避免大表把探针拖死。"""

    def __init__(self, lua: Lua53Reader, budget: int = 30000):
        self.lua = lua
        self.budget = budget

    def entries(self, address: int) -> list[tuple[str, object]]:
        lsize_node, size_array, array_ptr, node_ptr = self.lua.table_header(address)
        result: list[tuple[str, object]] = []
        for index in range(min(size_array, 5000)):
            value = self.lua.read_tvalue(array_ptr + index * 16)
            if value.tag == TAG_NIL:
                continue
            result.append((str(index + 1), value))
        for index in range(1 << lsize_node):
            node = node_ptr + index * 32
            key = self.lua.read_tvalue(node + 16)
            if key.tag == TAG_NIL:
                continue
            value = self.lua.read_tvalue(node)
            if value.tag == TAG_NIL:
                continue
            result.append((self.key_text(key), value))
        return result

    def key_text(self, key) -> str:
        if key.tag == TAG_INTEGER:
            return str(_i64(key.raw_value))
        if key.tag in STRING_TAGS:
            try:
                return self.lua.read_string(_u64(key.raw_value))
            except (OSError, ValueError, struct.error):
                return f"<string? 0x{_u64(key.raw_value):x}>"
        return f"<key tag {key.tag:#x}>"

    def entry_value(self, address: int, key_text: str):
        """按"键的文本形式"取表值: 角色表用整数键, get_table_field_tvalue 取不到。"""
        for key, value in self.entries(address):
            if key == key_text:
                return value
        return None

    def summarize(self, value, depth: int, limit: int = 40) -> dict | None:
        """depth 表示还能往下展开几层表; limit 是每层最多列多少条。"""
        if self.budget <= 0:
            return {"type": "truncated"}
        self.budget -= 1
        tag = value.tag
        if tag == TAG_NIL:
            return None
        if tag == TAG_BOOLEAN:
            return {"type": "bool", "value": bool(struct.unpack("<i", value.raw_value[:4])[0])}
        if tag == TAG_FLOAT:
            return {"type": "float", "value": struct.unpack("<d", value.raw_value)[0]}
        if tag == TAG_INTEGER:
            return {"type": "int", "value": _i64(value.raw_value)}
        if tag in STRING_TAGS:
            try:
                text = self.lua.read_string(_u64(value.raw_value))
            except (OSError, ValueError, struct.error):
                return {"type": "string", "error": True}
            return {"type": "string", "value": text if len(text) <= 160 else text[:160] + "…"}
        if tag == TAG_TABLE:
            address = _u64(value.raw_value)
            info: dict = {"type": "table", "address": f"0x{address:x}"}
            try:
                fields = self.entries(address)
            except (OSError, ValueError, struct.error) as err:
                info["error"] = f"{type(err).__name__}: {err}"
                return info
            info["entries"] = len(fields)
            if depth > 0:
                children = []
                for key, child in fields[:limit]:
                    summary = self.summarize(child, depth - 1, limit)
                    if summary is not None:
                        children.append({"key": key, "value": summary})
                if len(fields) > limit:
                    children.append({"key": "…", "value": {"type": f"还有 {len(fields) - limit} 条"}})
                info["fields"] = children
            return info
        return {"type": f"tag 0x{tag:x}", "raw": value.raw_value.hex()}

    def table_summary(self, address: int, depth: int = 2, limit: int = 40) -> dict | None:
        """按表地址直接展开一张表(兜底路径用)。"""
        return self.summarize(TValue(struct.pack("<Q", address), TAG_TABLE), depth, limit)


def find_root(process, lua: Lua53Reader, discovery: LuaTableDiscovery) -> int:
    """定位角色数据模块表: 它有一个值是表的 ``_mapChar`` 字段。"""
    strings = discovery._find_tstrings("_mapChar")
    nodes = discovery._find_key_nodes(strings)
    headers = discovery._scan_table_headers()
    companions = ("_mapGachaHistory", "_uid", "_mapGachaCount", "_mapTalent", "_mapGem", "_mapCharGem")
    best: int | None = None
    best_score = -1
    for node in nodes:
        for table in discovery._tables_containing_node(node, headers):
            try:
                value = lua.get_table_field_tvalue(table, "_mapChar")
            except (OSError, ValueError, struct.error):
                continue
            if value is None or value.tag != TAG_TABLE:
                continue
            score = 0
            for name in companions:
                try:
                    if lua.get_table_field_tvalue(table, name) is not None:
                        score += 1
                except (OSError, ValueError, struct.error):
                    continue
            if score > best_score:
                best, best_score = table, score
    if best is None:
        raise LookupError(
            "没有找到带 _mapChar 的玩家数据根表。请确认游戏已登录、已打开过角色页, "
            "且本进程有管理员权限。"
        )
    return best


def scan_field_names(process, discovery: LuaTableDiscovery, limit: int = 600) -> list[dict]:
    """扫一遍堆, 把名字里含 Talent/Gem/Skill 等词的 Lua 短字符串收出来。

    这不是"能定位表"的证明, 只是候选名字清单: 根表里若没有天赋/纹章字段,
    可以拿这些名字继续找。
    """
    found: dict[str, int] = {}
    regions = discovery._scannable_regions()
    for hit, needle in process.scan_any(NAME_NEEDLES, regions):
        word = needle.decode("ascii")
        for back in range(0, 10):
            object_address = hit - 24 - back
            header = process.try_read(object_address, 24)
            if header is None or header[8] != 4:      # 4 = 短字符串
                continue
            length = header[11]
            if not 2 <= length <= 64 or back + len(needle) > length:
                continue
            raw = process.try_read(object_address + 24, length + 1)
            if raw is None or raw[length:length + 1] != b"\0":
                continue
            try:
                name = raw[:length].decode("ascii")
            except UnicodeDecodeError:
                continue
            if word not in name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            found[name] = found.get(name, 0) + 1
            break
    ordered = sorted(found.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "hits": hits} for name, hits in ordered[:limit]]


def find_instance_tables(process, lua: Lua53Reader, discovery: LuaTableDiscovery,
                         field: str, limit: int = 2) -> list[int]:
    """兜底: 找出"以 field 为键"的 Lua 表(不依赖根表)。"""
    from stellasora_toolkit.affinity import _key_nodes

    headers = discovery._scan_table_headers()
    found: list[int] = []
    seen: set[int] = set()
    for key_slot in _key_nodes(process, field):
        # _key_nodes 给的是键槽(节点 + 16), 表头匹配要的是节点地址
        node = key_slot - 16
        for table in discovery._tables_containing_node(node, headers):
            if table in seen:
                continue
            seen.add(table)
            try:
                if lua.get_table_field_tvalue(table, field) is None:
                    continue
            except (OSError, ValueError, struct.error):
                continue
            found.append(table)
            if len(found) >= limit:
                return found
    return found


def _array_parent(process, lua: Lua53Reader, headers, reference: int,
                  cache: dict[int, tuple[int, int, int]]) -> tuple[int, str] | None:
    """数组槽里的值: 命中地址落在某个表的 array 段, 返回 (父表, 索引键)。"""
    for table, _lsize, _node_ptr, _node_count in headers:
        if table not in cache:
            raw = process.try_read(table, 48)
            if raw is None or raw[8] != 5:
                cache[table] = (0, 0, 0)
                continue
            cache[table] = (struct.unpack_from("<I", raw, 12)[0],
                            struct.unpack_from("<Q", raw, 16)[0],
                            struct.unpack_from("<Q", raw, 24)[0])
        size_array, array_ptr, _ = cache[table]
        if size_array and array_ptr <= reference < array_ptr + size_array * 16:
            offset = reference - array_ptr
            if offset % 16 == 0:
                return table, str(offset // 16 + 1)
    return None


def find_parent(process, lua: Lua53Reader, discovery: LuaTableDiscovery, headers,
                table_address: int, array_cache: dict[int, tuple[int, int, int]],
                summarizer: Summarizer) -> tuple[int, str] | None:
    """找"哪个表以哪个键引用了这张表": 哈希节点与数组槽都支持。"""
    for reference in process.scan(struct.pack("<Q", table_address)):
        if reference % 8:
            continue
        tag_raw = process.try_read(reference + 8, 4)
        if tag_raw is None or struct.unpack("<i", tag_raw)[0] != TAG_TABLE:
            continue
        parents = discovery._tables_containing_node(reference, headers)
        if parents:
            try:
                key = summarizer.key_text(lua.read_tvalue(reference + 16))
            except (OSError, ValueError, struct.error):
                key = "?"
            if key.startswith("<key"):
                continue
            for parent in parents:
                try:
                    lua.table_header(parent)      # 过滤掉"地址碰巧像表头"的假命中
                except (OSError, ValueError, struct.error):
                    continue
                return parent, key
        found = _array_parent(process, lua, headers, reference, array_cache)
        if found is not None:
            return found
    return None


def climb_parents(process, lua: Lua53Reader, discovery: LuaTableDiscovery,
                  table_address: int, summarizer: Summarizer, levels: int = 4) -> list[dict]:
    """从一张表往上找"谁引用了它", 返回 [{key, table, fields}]。

    纹章的实例表本身字段够用, 但要知道它挂在哪个模块字段下(例如 ``_mapCharGem``),
    就得顺着引用往上一层一层爬; 每一层顺便展开父表的字段名, 方便认结构。
    实例常放在数组槽里, 所以哈希节点和数组段都要认。
    """
    headers = discovery._scan_table_headers()
    array_cache: dict[int, tuple[int, int, int]] = {}
    path: list[dict] = []
    current = table_address
    for _ in range(levels):
        parent = find_parent(process, lua, discovery, headers, current, array_cache, summarizer)
        if parent is None:
            break
        parent_address, key = parent
        path.append({
            "key": key,
            "table": f"0x{parent_address:x}",
            "fields": summarizer.table_summary(parent_address, 1, 15),
        })
        current = parent_address
    return path


def find_string_objects(process, discovery: LuaTableDiscovery, names: list[str]) -> dict[str, int]:
    """一次遍历内存, 找出这些名字的 Lua 短字符串对象地址。"""
    wanted_bytes = [name.encode("ascii") for name in names]
    wanted_names = set(names)
    found: dict[str, int] = {}
    for hit, _needle in process.scan_any(wanted_bytes, discovery._scannable_regions()):
        for back in range(0, 10):
            object_address = hit - 24 - back
            header = process.try_read(object_address, 24)
            if header is None or header[8] != 4:
                continue
            length = header[11]
            if not 2 <= length <= 64:
                continue
            raw = process.try_read(object_address + 24, length + 1)
            if raw is None or raw[length:length + 1] != b"\0":
                continue
            try:
                text = raw[:length].decode("ascii")
            except UnicodeDecodeError:
                continue
            if text in wanted_names:
                found.setdefault(text, object_address)
            break
    return found


def tables_with_field(process, lua: Lua53Reader, discovery: LuaTableDiscovery, headers,
                      name: str, object_address: int, limit: int = 3) -> list[int]:
    """给定字段名字符串对象, 返回"以它为键"的 Lua 表。"""
    tables: list[int] = []
    seen: set[int] = set()
    for reference in process.scan(struct.pack("<Q", object_address)):
        if reference % 8:
            continue
        tag_raw = process.try_read(reference + 8, 4)
        if tag_raw is None or struct.unpack("<i", tag_raw)[0] not in STRING_TAGS:
            continue
        node = reference - 16
        for table in discovery._tables_containing_node(node, headers):
            if table in seen:
                continue
            seen.add(table)
            try:
                if lua.get_table_field_tvalue(table, name) is None:
                    continue
            except (OSError, ValueError, struct.error):
                continue
            tables.append(table)
            if len(tables) >= limit:
                return tables
    return tables


def class_catalog(process, lua: Lua53Reader, discovery: LuaTableDiscovery, headers) -> list[dict]:
    """列出内存里所有"类定义表": 以 __cname 为键、值是类名的那些表。"""
    objects = find_string_objects(process, discovery, ["__cname"])
    object_address = objects.get("__cname")
    if object_address is None:
        return []
    catalog = []
    for table in tables_with_field(process, lua, discovery, headers, "__cname", object_address, 500):
        try:
            name_value = lua.get_table_field_tvalue(table, "__cname")
            if name_value is None:
                continue
            name = lua.read_string(_u64(name_value.raw_value))
        except (OSError, ValueError, struct.error):
            continue
        catalog.append({"name": name, "table": table})
    return catalog


def instances_of_class(process, lua: Lua53Reader, discovery: LuaTableDiscovery, headers,
                       class_table: int, limit: int = 2) -> list[int]:
    """找"class 字段指向该类定义"的实例表。"""
    instances: list[int] = []
    for reference in process.scan(struct.pack("<Q", class_table)):
        if reference % 8:
            continue
        tag_raw = process.try_read(reference + 8, 4)
        if tag_raw is None or struct.unpack("<i", tag_raw)[0] != TAG_TABLE:
            continue
        try:
            key = lua.read_tvalue(reference + 16)
            if key.tag not in STRING_TAGS or lua.read_string(_u64(key.raw_value)) != "class":
                continue
        except (OSError, ValueError, struct.error):
            continue
        for table in discovery._tables_containing_node(reference, headers):
            if table not in instances:
                instances.append(table)
                if len(instances) >= limit:
                    return instances
    return instances


def probe(pid: int, characters: int, skip_names: bool) -> dict:
    started = time.perf_counter()
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        summarizer = Summarizer(lua)
        notes: list[str] = []

        root_fields: list[dict] = []
        suspects: dict[str, object] = {}
        try:
            root = find_root(process, lua, discovery)
        except LookupError as err:
            root = None
            notes.append(f"根表定位失败: {err}")

        characters_report: list[dict] = []
        deep: dict[str, object] = {}
        if root is not None:
            for key, value in summarizer.entries(root):
                summary = summarizer.summarize(value, 0, limit=8)
                root_fields.append({"key": key, "value": summary})

            char_map = lua.get_table_field_tvalue(root, "_mapChar")
            char_address = _u64(char_map.raw_value)
            chars = summarizer.entries(char_address)
            for key, value in chars[:max(1, characters)]:
                if value.tag != TAG_TABLE:
                    continue
                characters_report.append({"id": key, "value": summarizer.summarize(value, 4, limit=60)})

            # 优先按角色 130 取深度样本; 没有就取第一个角色
            sample_id = "130" if any(key == "130" for key, _ in chars) else (chars[0][0] if chars else "")
            for field in ("_tbCharPotential", "_CharSkillUpgrade", "tbTempSaveCharSkill", "_AdvanceLevelConfig"):
                container = lua.get_table_field_tvalue(root, field)
                if container is None or container.tag != TAG_TABLE:
                    continue
                container_address = _u64(container.raw_value)
                if field == "_AdvanceLevelConfig":
                    deep[field] = summarizer.table_summary(container_address, 3, 12)
                else:
                    value = summarizer.entry_value(container_address, sample_id)
                    deep[field] = (summarizer.summarize(value, 4, 30) if value is not None
                                   else summarizer.table_summary(container_address, 2, 6))

            # 潜力/天赋节点: 130 -> master[1][1] / assist[1][1] 的完整字段
            potential = lua.get_table_field_tvalue(root, "_tbCharPotential")
            if potential is not None and potential.tag == TAG_TABLE:
                def _potential_node(char_id: str, branch: str):
                    char_value = summarizer.entry_value(_u64(potential.raw_value), char_id)
                    if char_value is None or char_value.tag != TAG_TABLE:
                        return None
                    branch_value = summarizer.entry_value(_u64(char_value.raw_value), branch)
                    if branch_value is None or branch_value.tag != TAG_TABLE:
                        return None
                    group_value = summarizer.entry_value(_u64(branch_value.raw_value), "1")
                    if group_value is None or group_value.tag != TAG_TABLE:
                        return None
                    return summarizer.entry_value(_u64(group_value.raw_value), "1")

                sample_value = summarizer.entry_value(_u64(potential.raw_value), sample_id)
                if sample_value is not None:
                    deep[f"_tbCharPotential.{sample_id}.full"] = summarizer.summarize(
                        sample_value, 5, 30
                    )
                for branch in ("assist", "master"):
                    node_value = _potential_node(sample_id, branch)
                    if node_value is not None:
                        deep[f"_tbCharPotential.{sample_id}.{branch}.1.1"] = summarizer.summarize(
                            node_value, 3, 25
                        )
                # 用另一个角色做对照: 节点 id 相同 -> 静态配置, 不同 -> 玩家状态
                other_id = next((key for key, _value in chars if key != sample_id), None)
                if other_id:
                    for branch in ("assist", "master"):
                        node_value = _potential_node(other_id, branch)
                        if node_value is not None:
                            deep[f"_tbCharPotential.{other_id}.{branch}.1.1"] = summarizer.summarize(
                                node_value, 3, 25
                            )

            for key, value in summarizer.entries(root):
                if value.tag != TAG_TABLE or not SUSPECT_FIELD.search(str(key)):
                    continue
                if str(key) in ("_mapChar", "_tbCharPotential", "_CharSkillUpgrade"):
                    continue
                suspects[str(key)] = summarizer.summarize(value, 2, limit=12)

        gem: dict[str, object] = {}
        candidates = find_instance_tables(process, lua, discovery, "nGemId", limit=300)
        instances: list[int] = []
        for table in candidates:
            try:
                keys = {key for key, _value in summarizer.entries(table)}
            except (OSError, ValueError, struct.error):
                continue
            if {"sName", "nType", "nGenerateId"} <= keys:
                instances.append(table)
        notes.append(f"nGemId 命中 {len(candidates)} 张表, 其中纹章实例 {len(instances)} 张")
        gem["instances"] = [summarizer.table_summary(table, 2, 40) for table in instances[:3]]
        if instances:
            random_attr = lua.get_table_field_tvalue(instances[0], "tbRandomAttr")
            if random_attr is not None and random_attr.tag == TAG_TABLE:
                first = summarizer.entry_value(_u64(random_attr.raw_value), "1")
                if first is not None:
                    gem["attrSample"] = summarizer.summarize(first, 3, 20)
            # 纹章实例都带 nCharId, 直接按实例枚举即可; 容器链在部分客户端上不可靠
        headers = discovery._scan_table_headers()
        # 类定义目录: 用 __cname 认出 PlayerTalentData / EquipmentData 这类类表,
        # 再按"class 字段指向该类"找实例, 天赋/装备的玩家状态就在这些实例里。
        catalog = class_catalog(process, lua, discovery, headers)
        notes.append(f"发现类定义 {len(catalog)} 个")
        classes: dict[str, object] = {}
        classes["catalog"] = sorted({item["name"] for item in catalog})
        by_name = {item["name"]: item for item in catalog}
        priority = ["PlayerTalentData", "CharTalentCtrl", "PlayerEquipmentData",
                    "PlayerEquipmentInstanceData", "CharPotentialCtrl", "PlayerPotentialPreselectionData"]
        for name in priority:
            item = by_name.get(name)
            if item is None:
                classes[name] = {"missing": True}
                continue
            found = instances_of_class(process, lua, discovery, headers, item["table"], 2)
            classes[name] = {
                "classTable": f"0x{item['table']:x}",
                "instances": [summarizer.table_summary(table, 2, 60) for table in found],
            }

        modules: dict[str, object] = {}
        try:
            gacha_table = discovery.find_instance_table(
                "_mapGachaHistory", {"_mapGachaCount", "_mapTotalGachaTimes", "_openedPool"}
            )
            modules["_mapGachaHistory"] = {
                "table": f"0x{gacha_table:x}",
                "fields": summarizer.table_summary(gacha_table, 1, 60),
            }
        except (LookupError, OSError, ValueError) as err:
            notes.append(f"抽卡模块定位失败: {err}")

        names = [] if skip_names else scan_field_names(process, discovery)
        elapsed = time.perf_counter() - started

    return {
        "version": 5,
        "pid": pid,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed": round(elapsed, 2),
        "root": root_fields,
        "characters": characters_report,
        "deep": deep,
        "suspects": suspects,
        "gem": gem,
        "classes": classes,
        "modules": modules,
        "nameCandidates": names,
        "notes": notes,
    }


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _elevate_and_wait(out: Path, args: argparse.Namespace) -> int:
    from stellasora_toolkit.admin import request_elevation

    try:
        out.unlink()
    except OSError:
        pass
    child_args = [str(Path(__file__).resolve()), "--elevated", "--out", str(out)]
    if args.pid:
        child_args += ["--pid", str(args.pid)]
    if args.characters:
        child_args += ["--characters", str(args.characters)]
    if args.skip_names:
        child_args.append("--skip-names")
    try:
        request_elevation(Path(sys.executable), child_args, working_directory=ROOT)
    except OSError as err:
        print(f"提权被取消或失败: {err}", file=sys.stderr)
        return 2
    print("已请求管理员权限, 正在等待探针结果 ...")
    deadline = time.time() + 600
    while time.time() < deadline:
        if out.is_file():
            try:
                payload = json.loads(out.read_text("utf-8-sig"))
            except (OSError, ValueError):
                payload = None
            if payload and payload.get("completed"):
                print(f"探针完成: {out}")
                return 0 if payload.get("ok") else 1
        time.sleep(1)
    print("等待超时: 未看到提权后的探针结果。", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="只读枚举角色/纹章/天赋相关的 Lua 数据字段")
    parser.add_argument("--pid", type=int, default=0, help="指定游戏进程 PID(多开时用)")
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "character_probe.json")
    parser.add_argument("--characters", type=int, default=2, help="展开几个角色子表, 默认 2")
    parser.add_argument("--skip-names", action="store_true", help="跳过全堆字段名扫描(更快)")
    parser.add_argument("--no-elevate", action="store_true", help="不再请求提权, 直接运行")
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if not args.elevated and not args.no_elevate and not _is_admin():
        return _elevate_and_wait(Path(args.out), args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        running = [name for name, _pid in running_processes()]
        profile, _ = server_config.resolve_running(running)
        names = (profile.client_names if profile else
                 [n for prof in server_config.PROFILES.values() for n in prof.client_names])
        pid = find_process_id(names, pid=args.pid or None)
        report = probe(pid, args.characters, args.skip_names)
        report["completed"] = True
        report["ok"] = True
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"根表字段 {len(report['root'])} 个, 角色 {len(report['characters'])} 个, "
              f"纹章实例 {len(report['gem'].get('instances', []))} 张 -> {out}")
        return 0
    except Exception as err:  # 提权子进程没有控制台, 现场必须落盘
        payload = {
            "version": 2,
            "completed": True,
            "ok": False,
            "error": f"{type(err).__name__}: {err}",
            "traceback": traceback.format_exc(),
            "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"探针失败: {err} -> {out}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
