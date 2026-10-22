"""Presentation data shared by the three UI betas; no archive writes."""
from dataclasses import dataclass
from datetime import datetime

from ..catalog import gacha_item_name, same_item_name
from ..gacha_stats import (build_category_stat, build_banner_stats_with_shared_pity,
                         classify_history_category, display_category)
from ..service import Snapshot
from ..official_banners import official_pool_info
from .constants import GACHA_CATEGORY_ORDER, OFFICIAL_LIMITED_POOL_INFO


def is_up(gid: int, item_id: int) -> bool:
    info = official_pool_info(gid)
    # Unknown future banners retain normal five-star resets until metadata exists.
    return info is None or same_item_name(gacha_item_name(item_id), info[3])


@dataclass
class Overview:
    category_stats: dict
    total_pulls: int
    total_five: int
    well_banners: dict


def categories(records):
    result = {key: [] for key in GACHA_CATEGORY_ORDER}
    for record in records:
        # 显示用: 活动池(未知 Gid)按掉落内容归到限时类, 否则它们会从界面消失
        key = display_category([record])
        if key in result:
            result[key].append(record)
    return result


def activity_pools(records) -> list[dict]:
    """把"特殊活动卡池"(自选/联动/限定活动等)按 Gid 单独汇总出来。

    这些池子的记录在归档里仍然落在 1..4(格式不变), 只是界面上要能单独看:
    Gid 不在 10xxx/20xxx 区间, 或 bannerType 命中活动关键词。
    返回 [{gid, name, pulls, five_stars, start, end}]。
    """
    from ..official_banners import is_activity_pool, pool_display_name
    from ..catalog import is_five_star_item
    buckets: dict[int, dict] = {}
    for group in records:
        try:
            gid = int(group.get('Gid') or 0)
        except (TypeError, ValueError):
            continue
        if not is_activity_pool(gid):
            continue
        entry = buckets.setdefault(gid, {'gid': gid, 'pulls': 0, 'five_stars': 0,
                                         'times': []})
        ids = group.get('Ids') or []
        entry['pulls'] += len(ids)
        entry['five_stars'] += sum(1 for value in ids if is_five_star_item(value))
        try:
            entry['times'].append(int(group.get('Time') or 0))
        except (TypeError, ValueError):
            pass
    result = []
    for gid, entry in buckets.items():
        times = [t for t in entry['times'] if t]
        result.append({'gid': gid, 'name': pool_display_name(gid), 'pulls': entry['pulls'],
                       'five_stars': entry['five_stars'],
                       'start': min(times) if times else 0, 'end': max(times) if times else 0})
    result.sort(key=lambda row: (-row['pulls'], row['gid']))
    return result


def overview(records) -> Overview:
    grouped = categories(records)
    stats = {
        key: build_category_stat(groups, is_up=is_up if 'limited' in key else None)
        for key, groups in grouped.items()
    }
    wells = {
        pool.gid: pool.total_pulls
        for pool in build_banner_stats_with_shared_pity(grouped[GACHA_CATEGORY_ORDER[0]])
        if pool.total_pulls >= 120
    }
    return Overview(stats, sum(len(r.get('Ids', [])) for r in records),
                    sum(len(s.five_stars) for s in stats.values() if s), wells)


def demo_snapshot() -> Snapshot:
    """Deterministic illustrative records kept entirely in memory."""
    specs = [
        (10160, '2026-07-28', [(42, 160), (27, 110), (64, 160)], 18),
        (11133, '2026-08-08', [(36, 133)], 0),
        (10157, '2026-08-20', [(53, 157), (24, 157)], 23),
        (20160, '2026-07-29', [(38, 214055)], 0),
        (20157, '2026-08-22', [(46, 214057), (31, 214057)], 14),
        (1, '2026-06-10', [(59, 125), (32, 134), (46, 145)], 41),
        (2, '2026-06-11', [(34, 214015), (52, 214004)], 9),
    ]
    data = {}
    for gid, date, hits, trailing in specs:
        cat = 1 if 10000 <= gid < 20000 else 3 if gid >= 20000 else 2 if gid == 1 else 4
        filler = 103 if cat in (1,2) else 211001
        base = int(datetime.fromisoformat(date).timestamp())
        groups = data.setdefault(cat, [])
        for offset, (interval, item) in enumerate(hits):
            groups.append({'Gid': gid, 'Time': base + offset * 3600,
                           'Ids': [filler] * (interval - 1) + [item]})
        if trailing:
            groups.append({'Gid': gid, 'Time': base + len(hits) * 3600,
                           'Ids': [filler] * trailing})
    return Snapshot([g for groups in data.values() for g in groups], gacha_categories=data)
