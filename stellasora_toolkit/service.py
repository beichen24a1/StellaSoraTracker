from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .discovery import LuaTableDiscovery
from .exporter import export_all, sanitize_gacha_categories
from .lua53 import Lua53Reader
from .process import RemoteProcess, find_process_id
from .uid import read_game_uid_from_process


ProgressCallback = Callable[[str], None]
LEGACY_ARCHIVE_FILENAME = "stellasora_gacha_archive.json"


@dataclass(frozen=True)
class Snapshot:
    gacha: list[dict]
    emblems: list[dict] = field(default_factory=list)
    files: tuple[Path, ...] = ()
    gacha_categories: dict[int, list[dict]] = field(default_factory=dict)
    uid: str | None = None

    @property
    def pull_count(self) -> int:
        return sum(len(group.get("Ids", [])) for group in self.gacha)

    @property
    def character_count(self) -> int:
        return len({item.get("nCharId") for item in self.emblems if item.get("nCharId") is not None})


def extract_snapshot(
    output_dir: Path,
    process_name: str | None = None,
    progress: ProgressCallback | None = None,
    *,
    process_id: int | None = None,
) -> Snapshot:
    report = progress or (lambda _message: None)
    pid = find_process_id(process_name, pid=process_id)
    report(f"已连接游戏进程 PID {pid}，正在读取游戏 UID")
    with RemoteProcess(pid) as process:
        uid = read_game_uid_from_process(process)
        report("游戏 UID 读取完成，正在定位招募数据")
        lua = Lua53Reader(process)
        discovery = LuaTableDiscovery(process, lua)
        raw_gacha = discovery.read_target_field(
            "_mapGachaHistory",
            {"_mapGachaCount", "_mapGachaTotalTimes", "_mapTotalGachaTimes", "_openedPool"},
        )
    report("招募数据读取完成，正在生成 UID.json 和 CSV")
    current_categories = sanitize_gacha_categories(raw_gacha)
    categories = merge_gacha_categories(_load_archive(output_dir.resolve(), uid), current_categories)
    gacha = [group for groups in categories.values() for group in groups]
    files = tuple(export_all(output_dir.resolve(), gacha, None, categories))
    _write_archive(output_dir.resolve(), uid, categories)
    return Snapshot(gacha, [], (archive_path_for_uid(output_dir.resolve(), uid), *files), categories, uid)


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


def archive_path_for_uid(output_dir: Path, uid: str) -> Path:
    if not isinstance(uid, str) or re.fullmatch(r"[0-9]{5,15}", uid) is None:
        raise ValueError("无效的游戏 UID")
    return output_dir / f"{uid}.json"


def _load_archive(output_dir: Path, uid: str) -> dict[int, list[dict]]:
    archive = archive_path_for_uid(output_dir, uid)
    payload: dict = {}
    if archive.exists():
        # Do not silently replace a damaged UID archive with another account's history.
        payload = json.loads(archive.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("uid", uid) != uid:
            raise ValueError("归档内 UID 与文件名不一致，已停止合并")
    elif not any(re.fullmatch(r"[0-9]{5,15}", path.stem) for path in output_dir.glob("*.json")):
        # Legacy history can only be adopted during the first UID migration.
        legacy = output_dir / LEGACY_ARCHIVE_FILENAME
        if legacy.exists():
            payload = json.loads(legacy.read_text(encoding="utf-8-sig"))
        else:
            files = sorted(output_dir.glob("stellasora_gacha_*.json"), key=lambda path: path.stat().st_mtime)
            if files:
                payload = json.loads(files[-1].read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and payload.get("uid", uid) != uid:
            return {}
    categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    if not isinstance(categories, dict) or any(key not in {"1", "2", "3", "4"} or not isinstance(value, list) for key, value in categories.items()):
        raise ValueError("归档分类无效，已停止合并")
    return {int(key): value for key, value in categories.items() if isinstance(value, list)}


def _write_archive(output_dir: Path, uid: str, categories: dict[int, list[dict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_path_for_uid(output_dir, uid)
    temporary = output_dir / f".{uid}.json.tmp"
    payload = {
        "version": 1,
        "uid": uid,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "categories": {str(key): categories.get(key, []) for key in range(1, 5)},
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(archive)


def load_latest_snapshot(output_dir: Path) -> Snapshot | None:
    uid_files = sorted(
        (path for path in output_dir.glob("*.json") if re.fullmatch(r"[0-9]{5,15}", path.stem)),
        key=lambda path: path.stat().st_mtime,
    )
    for archive in reversed(uid_files):
        try:
            payload = json.loads(archive.read_text(encoding="utf-8-sig"))
            gacha = []
            categories = _load_archive(output_dir, archive.stem)
            for groups in categories.values():
                gacha.extend(groups)
            return Snapshot(gacha, [], (archive,), categories, archive.stem)
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    if uid_files:
        return None

    legacy = output_dir / LEGACY_ARCHIVE_FILENAME
    if legacy.is_file():
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8-sig"))
            gacha = []
            categories = {int(key): value for key, value in payload.get("categories", {}).items()}
            for groups in categories.values():
                gacha.extend(groups)
            return Snapshot(gacha, [], (legacy,), categories, None)
        except (OSError, ValueError, AttributeError, TypeError):
            pass

    gacha_files = sorted(
        (path for path in output_dir.glob("stellasora_gacha_*.json") if path.name != LEGACY_ARCHIVE_FILENAME),
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
    return Snapshot(gacha, [], (gacha_file,), categories, None)
