from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .discovery import LuaTableDiscovery
from .exporter import export_all, sanitize_gacha_categories
from .lua53 import Lua53Reader
from .process import RemoteProcess, find_process_id


ProgressCallback = Callable[[str], None]
ARCHIVE_FILENAME = "stellasora_gacha_archive.json"


@dataclass(frozen=True)
class Snapshot:
    gacha: list[dict]
    emblems: list[dict] = field(default_factory=list)
    files: tuple[Path, ...] = ()
    gacha_categories: dict[int, list[dict]] = field(default_factory=dict)

    @property
    def pull_count(self) -> int:
        return sum(len(group.get("Ids", [])) for group in self.gacha)

    @property
    def character_count(self) -> int:
        return len({item.get("nCharId") for item in self.emblems if item.get("nCharId") is not None})


def extract_snapshot(
    output_dir: Path,
    process_name: str = "xtlr.exe",
    progress: ProgressCallback | None = None,
) -> Snapshot:
    report = progress or (lambda _message: None)
    pid = find_process_id(process_name)
    report(f"已连接游戏进程 PID {pid}，正在定位招募数据")
    with RemoteProcess(pid) as process:
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        raw_gacha = discovery.read_target_field(
            "_mapGachaHistory",
            {"_mapGachaCount", "_mapGachaTotalTimes", "_mapTotalGachaTimes", "_openedPool"},
        )
    report("招募数据读取完成，正在生成本地 JSON 和 CSV")
    current_categories = sanitize_gacha_categories(raw_gacha)
    categories = merge_gacha_categories(_load_archive(output_dir.resolve()), current_categories)
    gacha = [group for groups in categories.values() for group in groups]
    files = tuple(export_all(output_dir.resolve(), gacha, None, categories))
    _write_archive(output_dir.resolve(), categories)
    return Snapshot(gacha, [], files, categories)


def _group_key(group: dict) -> tuple:
    ids = group.get("Ids", [])
    if isinstance(ids, dict):
        ids = list(ids.values())
    return (
        group.get("Gid"),
        group.get("Time"),
        tuple(ids) if isinstance(ids, list) else str(ids),
    )


def merge_gacha_categories(
    archived: dict[int, list[dict]],
    current: dict[int, list[dict]],
) -> dict[int, list[dict]]:
    merged: dict[int, list[dict]] = {}
    for category in sorted(set(archived) | set(current)):
        by_key = {_group_key(group): group for group in archived.get(category, [])}
        by_key.update({_group_key(group): group for group in current.get(category, [])})
        merged[category] = sorted(
            by_key.values(),
            key=lambda group: (int(group.get("Time") or 0), int(group.get("Gid") or 0)),
        )
    return {category: groups for category, groups in merged.items() if groups}


def _load_archive(output_dir: Path) -> dict[int, list[dict]]:
    archive = output_dir / ARCHIVE_FILENAME
    payload: dict = {}
    try:
        payload = json.loads(archive.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Upgrade an existing timestamped export into the persistent archive.
        files = sorted(output_dir.glob("stellasora_gacha_*.json"), key=lambda path: path.stat().st_mtime)
        if files:
            try:
                payload = json.loads(files[-1].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
    categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    return {int(key): value for key, value in categories.items() if isinstance(value, list)}


def _write_archive(output_dir: Path, categories: dict[int, list[dict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / ARCHIVE_FILENAME
    temporary = output_dir / f".{ARCHIVE_FILENAME}.tmp"
    payload = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "categories": {str(key): value for key, value in categories.items()},
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(archive)


def load_latest_snapshot(output_dir: Path) -> Snapshot | None:
    gacha_files = sorted(
        (path for path in output_dir.glob("stellasora_gacha_*.json") if path.name != ARCHIVE_FILENAME),
        key=lambda path: path.stat().st_mtime,
    )
    if not gacha_files:
        return None
    gacha_file = gacha_files[-1]
    try:
        gacha_payload = json.loads(gacha_file.read_text(encoding="utf-8"))
        gacha = gacha_payload.get("groups", [])
        categories = {int(key): value for key, value in gacha_payload.get("categories", {"1": gacha}).items()}
    except (OSError, ValueError, AttributeError):
        return None
    return Snapshot(gacha, [], (gacha_file,), categories)
