# -*- coding: utf-8 -*-
"""从游戏运行时的配置表里读物品名 —— 不联网也能补名字。

为什么需要: 新五星上线后 ``catalog.py`` 的静态表还没补时, 抽到新角色会回显
``旅人 #161``, 卡池 UP 名对不上号还会被判成「歪」; 现在的兜底只有联网查询,
接口慢/断网就一直停在占位符。

游戏客户端本来就把全部物品名放在内存里的配置表里(ConfigData 的 ``Item`` 表):

    Item.<物品ID>.1 = 名字      (角色 110 -> 翡冷翠, 秘纹 214068 -> 帐幕下的酣梦)
    Item.<物品ID>.2 / .3 = 描述

``roster.py`` 已经在用同一套读取逻辑查天赋/词条文本, 这里只是把 ``Item.*.1`` 抽出来
按 id 建索引。取到名字后用 ``catalog.register_gacha_resource()`` 注册, 界面立刻就能
显示正确名字 —— 语言跟随客户端, 零网络请求。

限制: 需要游戏在运行且已登录(抓抽卡时本来就在跑), 并且工具要有管理员权限。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import roster
from .catalog import is_five_star_item, register_gacha_resource
from .lua53 import Lua53Reader

# 配置表名与"名字"那一条的后缀: Item.<id>.1 是名字, .2/.3 是描述
ITEM_TABLE = "Item"
NAME_SUFFIX = "1"
ITEM_NAME_PATTERN = re.compile(rf"^Item\.(\d+)\.{NAME_SUFFIX}$")

# 名字里可能带富文本残留(例如「<color=#fff>…</color>」), 与 roster 的处理保持一致
_TAG_RE = re.compile(r"<[^>]+>")
_PARAM_RE = re.compile(r"&Param\d+&")


def clean_name(text: str | None) -> str:
    if not text:
        return ""
    return _PARAM_RE.sub("…", _TAG_RE.sub("", str(text))).strip()


def item_names_from_texts(texts: dict[str, str]) -> dict[int, str]:
    """``{"Item.161.1": "优叶", ...}`` -> ``{161: "优叶", ...}``（纯函数, 便于测试）。"""
    names: dict[int, str] = {}
    for key, value in texts.items():
        match = ITEM_NAME_PATTERN.match(str(key))
        if not match:
            continue
        name = clean_name(value)
        if name:
            names[int(match.group(1))] = name
    return names


def read_item_names(process, *, lua: Lua53Reader | None = None,
                    only: set[int] | None = None) -> dict[int, str]:
    """读游戏内存里 ``Item`` 配置表的名字表。

    ``only`` 给定时只保留这些 id(省内存、日志也干净)。定位不到配置表时返回空字典,
    调用方按"这次没补到"处理即可。
    """
    reader = lua or Lua53Reader(process)
    registry = roster.find_config_registry(process, reader)
    if registry is None:
        return {}
    texts = roster.config_table_texts(reader, registry, ITEM_TABLE)
    names = item_names_from_texts(texts)
    if only is not None:
        wanted = {int(item) for item in only}
        names = {item_id: name for item_id, name in names.items() if item_id in wanted}
    return names


def register_names(names: dict[int, str]) -> list[tuple[int, str, str]]:
    """把内存里读到的名字注册进目录, 返回 ``[(id, kind, name)]``。

    只注册"抽卡目录里的前向兼容区间"(新旅人 161..199 / 新秘纹 214000..214999),
    其它 id(天赋节点、任务物品等)一律不碰 —— 那些名字不是抽卡产出物。
    """
    registered: list[tuple[int, str, str]] = []
    for item_id, name in sorted(names.items()):
        if 161 <= item_id < 200:
            kind = "traveler"
        elif 214000 <= item_id < 215000:
            kind = "disc"
        else:
            continue
        register_gacha_resource(item_id, kind, name, rarity=5 if is_five_star_item(item_id) else 4)
        registered.append((item_id, kind, name))
    return registered


def missing_item_ids(record_ids, name_of) -> set[int]:
    """从抽卡记录里挑出还没有名字的序号（``name_of`` 一般是 ``catalog.gacha_item_name``）。"""
    unknown: set[int] = set()
    for value in record_ids:
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if "#" in name_of(item_id):
            unknown.add(item_id)
    return unknown
