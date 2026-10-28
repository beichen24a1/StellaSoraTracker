"""Presentation data for the desktop application; no archive writes."""
from dataclasses import dataclass, field

from .catalog import gacha_item_name, is_five_star_item, same_item_name
from .gacha_stats import (
    CATEGORY_ANNIVERSARY, build_category_stat, build_banner_stats_with_shared_pity, display_category,
)
from .official_banners import official_pool_info
from .constants import GACHA_CATEGORY_ORDER, OFFICIAL_LIMITED_POOL_INFO
from .gacha_display import build_spark_rewards


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
    rewards: dict = field(default_factory=dict)


def categories(records):
    """按展示分类分组: 四张常规卡 + 独立的周年特选组。

    周年特选(#21)不再并进「秘纹限时」, 而是单独留在 CATEGORY_ANNIVERSARY 里:
    它只在「活动卡池」卡片和活动筛选里出现, 不参与四张常规卡的统计。
    判不出 Gid 的新池子仍由 display_category() 按掉落内容兜底, 不会从界面消失。
    """
    result = {key: [] for key in (*GACHA_CATEGORY_ORDER, CATEGORY_ANNIVERSARY)}
    for record in records:
        key = display_category([record])
        if key in result:
            result[key].append(record)
    return result


def activity_pools(records) -> list[dict]:
    """把"特殊活动卡池"(自选/联动/限定活动等)按 Gid 单独汇总出来。

    这些池子的记录在归档里仍然落在 1..4(周年特选是 6), 只是界面上要能单独看:
    Gid 不在 10xxx/20xxx 区间, 或 bannerType 命中活动关键词。
    周年特选也算活动池, 不再单独占一个分类。
    返回 [{gid, name, pulls, five_stars, start, end}]。
    """
    from .official_banners import is_activity_pool, pool_display_name
    from .catalog import is_five_star_item
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
    # 只有四张常规卡进统计; 周年特选单独成组(#21), 不能稀释限时卡的数字。
    stats = {
        key: build_category_stat(grouped[key], is_up=is_up if 'limited' in key else None)
        for key in GACHA_CATEGORY_ORDER
    }
    banner_info = dict(OFFICIAL_LIMITED_POOL_INFO)
    for group in grouped[GACHA_CATEGORY_ORDER[0]]:
        gid = int(group['Gid'])
        if (info := official_pool_info(gid)) and all(info[1:]):
            banner_info[gid] = info
    rewards = build_spark_rewards(grouped[GACHA_CATEGORY_ORDER[0]], banner_info)
    totals = {pool.gid: pool.total_pulls for pool in build_banner_stats_with_shared_pity(grouped[GACHA_CATEGORY_ORDER[0]])}
    wells = {gid: totals[gid] for gid in rewards}
    # 账号累计(含活动池)独立统计: 活动池不参与四张卡的统计口径, 但抽数和五星
    # 仍然是这个账号的真实总量(#21)。
    return Overview(stats, sum(len(r.get('Ids', [])) for r in records),
                    sum(1 for record in records for item in record.get('Ids', []) if is_five_star_item(item)),
                    wells, rewards)
