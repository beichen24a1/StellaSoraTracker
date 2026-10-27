# -*- coding: utf-8 -*-
"""
官方限时卡池信息的自动获取。

StellaBase 公开接口 /api/stella/banners 提供全部卡池的最新信息:
    id / name / bannerType / startTime / endTime / rateUp.fiveStar.entries[].name

工具旧版本把卡池信息写在 constants.py 的 OFFICIAL_LIMITED_POOL_INFO 静态表里,
每次游戏更新卡池都要手动编辑。本模块把它变成运行时自动拉取:

- fetch_banners()           拉取并解析为与静态表相同的 {gid: (名称, 开始, 结束, UP名)};
- save_banners/load_banners 落盘缓存到 output_dir/official_banners_<版本>.json, 离线也可用;
- official_pool_info(gid)  合成查询: 动态数据优先, 静态表兜底(网络完全不可用时仍有旧数据可用)。

语言: `lang` 参数取当前激活的游戏版本(server_config), 国服 cn / 国际服 en,
因此卡池名与 UP 名会与本机抽卡记录的名字语言一致。

软件运行时行为: 窗口启动后后台线程拉取一次并写缓存; 期间(以及离线时)查询均同步成功。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from . import server_config
from .constants import OFFICIAL_LIMITED_POOL_INFO

BANNERS_API_URL = "https://stella.ennead.cc/api/stella/banners"


def cache_filename() -> str:
    """按当前版本区分缓存文件, 切换服务器时不会读到另一版本的卡池数据。"""
    return f"official_banners_{server_config.active().key}.json"

# 进程内动态表: gid -> (名称, 开始日期, 结束日期, UP名); None 表示尚未加载
_active: dict[int, tuple[str, str, str, str]] | None = None
# gid -> bannerType(如「角色限时规则」「角色自选规则」), 用于把活动/自选池归到一类
_types: dict[int, str] = {}
# 所有卡池的 UP 名单: [{"id": 162, "name": "...", "rarity": 5}], 名称兜底用
_rate_up: list[dict] = []

# 这些字样说明是"活动/自选/联动"这类特殊池 —— 与普通限时池分组展示, 但数据仍写 1..4
ACTIVITY_KEYWORDS = ("自选", "活动", "特殊", "联动", "纪念", "合作", "collab", "anniversary")


def set_active_banners(banners: dict[int, tuple[str, str, str, str]],
                       types: dict[int, str] | None = None) -> None:
    global _active, _types
    _active = banners
    _types = dict(types or {})


def _date_part(value: str) -> str:
    """'2026-09-08T12:00:00+08:00' -> '2026-09-08'(与静态表日期格式一致)。"""
    return str(value)[:10]


def _up_names(banner: dict[str, Any]) -> str:
    """rateUp.fiveStar.entries 里的第一个五星名字(UP 判定只需名字, 且旧版格式只有一个)。"""
    try:
        entries = banner.get("rateUp", {}).get("fiveStar", {}).get("entries") or []
        return str(entries[0].get("name", ""))
    except (AttributeError, IndexError, TypeError):
        return ""


def parse_banners(payload: list[dict]) -> dict[int, tuple[str, str, str, str]]:
    """API JSON -> {gid: (名称, 开始, 结束, UP名)}。

    常驻池(bannerType 含"常驻"/"Permanent")也收进来 —— 名字/时间对界面有用,
    只是 UP 名留空(常驻池没有 UP 判定)。类型另存到 _types, 供"活动池"分组使用。
    """
    result: dict[int, tuple[str, str, str, str]] = {}
    types: dict[int, str] = {}
    collected: list[dict] = []
    for banner in payload:
        if not isinstance(banner, dict):
            continue
        try:
            gid = int(banner["id"])
        except (KeyError, TypeError, ValueError):
            continue
        btype = str(banner.get("bannerType") or "")
        permanent = bool(btype) and ("常驻" in btype or "permanent" in btype.casefold())
        name = str(banner.get("name") or f"卡池 {gid}")
        start = _date_part(str(banner.get("startTime") or ""))
        end = _date_part(str(banner.get("endTime") or ""))
        types[gid] = btype
        result[gid] = (name, start, end, "" if permanent else _up_names(banner))
        for slot, rarity in (("fiveStar", 5), ("fourStar", 4)):
            entries = (banner.get("rateUp") or {}).get(slot) or {}
            for entry in (entries.get("entries") or []):
                if not isinstance(entry, dict):
                    continue
                try:
                    item_id = int(entry["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                label = str(entry.get("name") or "").strip()
                if item_id and label:
                    collected.append({"id": item_id, "name": label, "rarity": rarity,
                                      "kind": 'disc' if item_id >= 200000 else 'traveler'})
    _types.clear()
    _types.update(types)
    _rate_up.clear()
    _rate_up.extend(collected)
    return result


def fetch_banners(timeout: float = 20.0, lang: str | None = None) -> dict[int, tuple[str, str, str, str]]:
    """联网拉取; 失败(超时/解析错误/网络不可用)抛 OSError, 调用方自行兜底。

    lang 默认取当前激活版本(server_config.api_lang()): 国服 cn / 国际服 en, 名称语言一致。
    """
    lang = lang or server_config.api_lang()
    request = Request(f"{BANNERS_API_URL}?lang={lang}", headers={"User-Agent": "StellaSoraToolkit/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or "current" not in payload:
        raise ValueError("banners API response is not a list")
    rows: list[dict] = []
    for key in ("current", "permanent", "upcoming", "ended"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return parse_banners(rows)


def save_banners(banners: dict[int, tuple[str, str, str, str]], cache_path: Path) -> None:
    """把动态表写盘, 下次启动离线可用。"""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "banners": [
            {"gid": gid, "name": name, "start": start, "end": end, "up": up,
             "type": _types.get(gid, "")}
            for gid, (name, start, end, up) in sorted(banners.items())
        ],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_banners(cache_path: Path) -> dict[int, tuple[str, str, str, str]]:
    """读缓存; 文件缺失/损坏返回空 dict(此时由静态表兜底)。"""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        loaded: dict[int, tuple[str, str, str, str]] = {}
        types: dict[int, str] = {}
        for row in payload.get("banners", []):
            gid = int(row["gid"])
            loaded[gid] = (str(row["name"]), str(row["start"]), str(row["end"]), str(row["up"]))
            if row.get("type"):
                types[gid] = str(row["type"])
        if types:
            _types.clear()
            _types.update(types)
        return loaded
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def official_pool_info(gid: int) -> tuple[str, str, str, str] | None:
    """视图层统一查询: 动态数据(本次拉取/缓存)优先, 静态表兜底。"""
    if _active is not None and gid in _active:
        return _active[gid]
    return OFFICIAL_LIMITED_POOL_INFO.get(gid)


def banner_type(gid: int) -> str:
    """这个卡池的 bannerType(没拉到就返回空串)。"""
    try:
        return _types.get(int(gid), "")
    except (TypeError, ValueError):
        return ""


def is_activity_pool(gid: int) -> bool:
    """是不是"活动/自选/联动"这类特殊池 —— 界面可以把它们归到同一组展示。

    判定: bannerType 命中关键词; 或者 Gid 不在常规的 10xxx(旅人限时)/20xxx(秘纹限时)
    /1(旅人常驻)/2(秘纹常驻) 区间里。数据格式不受影响(归档里仍然是 1..4, 周年特选是 6)。

    周年特选(Gid 1001)属于活动卡池, 界面统一放在「活动卡池」里展示。
    """
    try:
        value = int(gid)
    except (TypeError, ValueError):
        return False
    btype = _types.get(value, "")
    if btype and any(word.casefold() in btype.casefold() for word in ACTIVITY_KEYWORDS):
        return True
    if value < 100:                      # 1/2 常驻, 以及 5 号这类小序号池
        return False
    return not (10_000 <= value < 30_000)


def pool_display_name(gid: int) -> str:
    """卡池显示名: 官方名 > 静态表 > 「活动卡池 <gid>」/「卡池 <gid>」。

    活动/自选/联动池会加「（活动）」后缀, 这样即使它们和普通限时池归在同一类里,
    界面上一眼也能看出是特殊活动池。数据/JSON 格式不受影响。
    """
    info = official_pool_info(gid)
    activity = is_activity_pool(gid)
    if info is not None and info[0]:
        return f"{info[0]}（活动）" if activity and "活动" not in info[0] else info[0]
    prefix = "活动卡池" if activity else "卡池"
    return f"{prefix} {gid}"


def rate_up_entries() -> list[dict]:
    """最近一次拉取里各卡池的 UP 名单([{id, name, rarity}])。

    角色接口超时的时候, 这些名字可以当"第二名称来源"用 —— 新角色只要能进卡池,
    名字就一定能补上。
    """
    return [dict(entry) for entry in _rate_up]


def active_banners() -> dict[int, tuple[str, str, str, str]]:
    """当前生效的卡池表(动态优先; 未加载动态表时为内置静态表)。

    供**反向查询**使用 —— 例如截图 OCR 只拿到卡池名, 需要由名字反推 Gid。
    """
    return dict(_active) if _active else dict(OFFICIAL_LIMITED_POOL_INFO)


def refresh_from_network(cache_path: Path, attempts: int = 2, *, lang: str | None = None) -> bool:
    """后台线程用: 拉取 -> 写缓存 -> 更新进程内表。失败返回 False(静态表/缓存兜底)。

    重试一次: 站点偶发超时会让卡池名一直停在旧缓存(表现为"新卡池没有名字"),
    而调用方看不到任何提示。返回值让界面能说明"这次没更新成功"。
    """
    lang = lang or server_config.api_lang()
    for attempt in range(max(1, attempts)):
        try:
            banners = fetch_banners(lang=lang)
        except (OSError, ValueError):
            if attempt + 1 < attempts:
                time.sleep(1.0)
                continue
            return False
        save_banners(banners, cache_path)
        if lang != server_config.api_lang():
            return False
        set_active_banners(banners)
        return True
    return False
