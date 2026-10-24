from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Mapping, Sequence

from .catalog import FIVE_STAR_TRAVELERS, TRAVELER_NAMES
from .gacha_stats import FiveStarPull


SPARK_PULLS = 120
CN_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class SparkReward:
    """A display-only reward, never a pull or an archive entry."""

    gid: int
    item_id: int
    name: str
    period_start: int
    period_end: int
    last_pull_time: int
    kind: str = "traveler"


def _normalize_name(name: str) -> str:
    return "".join(name.translate(str.maketrans({"（": "(", "）": ")"})).split()).casefold()


def build_spark_rewards(
    groups: Sequence[dict],
    banner_info: Mapping[int, tuple[str, str, str, str]],
) -> dict[int, SparkReward]:
    names = {_normalize_name(name): item_id for item_id, name in TRAVELER_NAMES.items() if item_id in FIVE_STAR_TRAVELERS}
    periods: dict[int, tuple[int, int, int, str]] = {}
    for gid, (_title, start, end, name) in banner_info.items():
        item_id = names.get(_normalize_name(name))
        if not 10000 <= gid < 20000 or item_id is None:
            continue
        # The bundled calendar is day-precision; always interpret it in CN time.
        start_time = int(datetime.combine(date.fromisoformat(start), time.min, CN_TIMEZONE).timestamp())
        end_time = int(datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, CN_TIMEZONE).timestamp())
        periods[gid] = (start_time, end_time, item_id, name)

    totals: dict[int, int] = {}
    last_times: dict[int, int] = {}
    for group in groups:
        try:
            gid, timestamp = int(group.get("Gid")), int(group.get("Time"))
        except (ValueError, TypeError):
            continue
        period = periods.get(gid)
        ids = group.get("Ids")
        if period is None or not period[0] <= timestamp < period[1] or not isinstance(ids, list):
            continue
        totals[gid] = totals.get(gid, 0) + len(ids)
        last_times[gid] = max(last_times.get(gid, 0), timestamp)

    return {
        gid: SparkReward(gid, periods[gid][2], periods[gid][3], periods[gid][0], periods[gid][1], last_times[gid])
        for gid, total in totals.items()
        if total >= SPARK_PULLS
    }


def insert_spark_rewards(
    pulls: Sequence[FiveStarPull], rewards: Mapping[int, SparkReward],
) -> tuple[FiveStarPull | SparkReward, ...]:
    """Prepend each reward to its period without reordering real pulls."""
    entries: list[FiveStarPull | SparkReward] = list(pulls)
    for reward in sorted(rewards.values(), key=lambda entry: (entry.last_pull_time, entry.gid), reverse=True):
        index = next(
            (index for index, entry in enumerate(entries)
             if isinstance(entry, FiveStarPull) and entry.gid == reward.gid
             and reward.period_start <= entry.timestamp < reward.period_end),
            None,
        )
        if index is None:
            # A 120-pull period can have no real five-star in the local history.
            index = next(
                (index for index, entry in enumerate(entries)
                 if (entry.last_pull_time if isinstance(entry, SparkReward) else entry.timestamp) < reward.last_pull_time),
                len(entries),
            )
        entries.insert(index, reward)
    return tuple(entries)
