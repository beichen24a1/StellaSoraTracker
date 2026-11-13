# -*- coding: utf-8 -*-
"""诊断工具: 从游戏内存的配置表里找"角色/秘纹名字"的 key 规则。

背景: 新五星上线后, 静态表(catalog.py)还没补时只能联网补名字; 但游戏运行中内存里
本来就有一整张本地化文本表(ConfigData 的 UIText / Talent / Item, ``meta.lang`` 是
解码好的 key -> 文本), roster.py 已经在用它查天赋/词条文本。如果角色名也在里面,
就能在抓抽卡时**离线、按客户端语言**把未知 id 的名字解出来, 不再受联网失败影响。

这个脚本只读内存, 不改任何东西, 但**必须以管理员身份运行**(游戏进程是受保护的)。

用法::

    # 普通终端会报 Errno 5; 请用管理员 PowerShell 跑, 或:
    右键「以管理员身份运行」-> python tools/probe_texts.py
    python tools/probe_texts.py --dump 40      # 额外打印每个表的前 N 条 key

输出:
    1. 三张表各有多少条文本、key 样例
    2. 用已知名字(翡冷翠/优叶/猫神降歌...)反查 key -> 看出命名规则
    3. 用未知 id(161/214068/214069)试几个候选 key, 看哪个能命中
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stellasora_toolkit import roster  # noqa: E402
from stellasora_toolkit.lua53 import Lua53Reader  # noqa: E402
from stellasora_toolkit.process import RemoteProcess, find_game_processes  # noqa: E402

# (名字, 期望的 id) —— 用来反查 key 规则; 前几个是长期不变的老条目
KNOWN = {
    "翡冷翠": 110,
    "花原": 119,
    "埃莉诺": 137,
    "优叶": 161,
    "尘沙（源初）": 162,
    "猫神降歌": 214001,
    "帐幕下的酣梦": 214068,
    "紧急救援": 214069,
}

# 试给未知 id 拼 key 的候选模板(命中即说明规则)
CANDIDATES = (
    "Traveler.{id}.1",
    "Traveler.{id}",
    "Char.{id}.1",
    "Char.{id}.Name",
    "TravelerName.{id}",
    "Name.{id}",
    "Item.{id}.1",
)

TABLES = ("UIText", "Talent", "Item")


def _load_per_table(lua: Lua53Reader, registry: int) -> dict[str, dict[str, str]]:
    return {name: roster._config_lang(lua, registry, name) for name in TABLES}


def _pattern_of(key: str, item_id: int) -> str:
    """把 key 里的 id 换成 {id}，方便一眼看出规则。"""
    return re.sub(re.escape(str(item_id)), "{id}", key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="诊断配置表里的名字 key 规则")
    parser.add_argument("--dump", type=int, default=0, help="每张表多打印前 N 条 key")
    args = parser.parse_args(argv)

    processes = find_game_processes()
    if not processes:
        print("没有找到游戏进程（xtlr.exe / StellaSora.exe）。请先启动并登录游戏。")
        return 1
    target = processes[0]
    print(f"进程: {target.name} pid={target.pid}")
    try:
        process = RemoteProcess(target.pid)
    except OSError as error:
        print(f"打不开进程: {error}\n请用管理员权限运行本脚本。")
        return 2
    with process:
        lua = Lua53Reader(process)
        registry = roster._find_config_registry(process, lua)
        print("ConfigData registry:", hex(registry) if registry else None)
        if registry is None:
            print("定位不到配置表注册表: 先打开一次「角色」或「招募记录」界面再试。")
            return 2
        tables = _load_per_table(lua, registry)
        for name, texts in tables.items():
            keys = list(texts)
            print(f"== {name}: {len(keys)} 条, key 例: {keys[:5]}")
            if args.dump:
                for key in keys[: args.dump]:
                    print(f"   {key} = {texts[key]!r}")
            hits = [key for key, value in texts.items() if value in KNOWN]
            for key in hits[:12]:
                value = texts[key]
                print(f"   名字命中: {KNOWN[value]} {value!r} <- {key}  (规则 {_pattern_of(key, KNOWN[value])})")
        merged = {}
        for texts in tables.values():
            merged.update(texts)
        print(f"== 合并后 {len(merged)} 条")
        for item_id in (161, 214068, 214069):
            print(f"-- id {item_id}")
            found = [key for key in merged if re.search(rf"(?<!\d){item_id}(?!\d)", key)]
            print(f"   含 id 的 key: {found[:10]}")
            for template in CANDIDATES:
                key = template.format(id=item_id)
                if key in merged:
                    print(f"   命中候选 {key} = {merged[key]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
