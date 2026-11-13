# -*- coding: utf-8 -*-
"""新五星上线后，用一条命令补齐静态目录（catalog.py + 立绘 + 资源清单）。

背景: 每次游戏更新加了新角色/新秘纹，都要手改 ``stellasora_toolkit/catalog.py`` 的
三张表、下载立绘、再跑 ``tools/rebuild_resource_manifest.py``。漏一步，抽到新五星就
回显 ``旅人 #161``，卡池 UP 名对不上号还会被判成「歪」。

这个脚本把这条链路固定下来（顺序即发版前的检查顺序）::

    1. 拉 StellaBase 的 characters / discs（当前语言）
    2. 和 catalog.py 的三张表对比，算出缺哪些名字/五星标记
    3. 把缺的条目写回 catalog.py（追加在各自块末尾，保持原文件换行风格）
    4. 下载缺失的立绘到 assets/{travelers,discs}/<id>.png
    5. 重建 resource_manifest.json / _github.json / resources.zip
    6. 跑 tools/run_tests.py 做回归

用法::

    python tools/refresh_catalog.py              # 全流程
    python tools/refresh_catalog.py --check      # 只体检，不改文件（有差异时退出码 1）
    python tools/refresh_catalog.py --no-tests   # 跳过最后的回归测试
    python tools/refresh_catalog.py --lang en    # 按国际服抓名字（默认 cn）

注意: 4 星旅人也会补名字/头像（好感度页要显示全部已拥有角色）；秘纹只给 5 星打包立绘，
因为 ``tests/test_catalog_alignment.py`` 要求 assets/discs 里的每一张都必须是五星。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SITE = "https://stella.ennead.cc"
API_BASE = f"{SITE}/api/stella"
ASSET_BASE = f"{SITE}/api/asset"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
RETRIES = 4
TIMEOUT = 180.0

CATALOG_PATH = ROOT / "stellasora_toolkit" / "catalog.py"
ASSETS = ROOT / "assets"

BLOCK_TRAVELERS = "TRAVELER_NAMES"
BLOCK_FIVE_TRAVELERS = "FIVE_STAR_TRAVELERS"
BLOCK_FIVE_DISCS = "FIVE_STAR_DISCS"
BLOCK_DISCS = "DISC_NAMES"


# --------------------------------------------------------------------------- 网络

def _get(url: str, timeout: float = TIMEOUT, retries: int = RETRIES) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            print(f"  ! {url} 第 {attempt + 1}/{retries} 次失败: {type(error).__name__}", flush=True)
            if attempt + 1 < retries:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"请求失败: {url} ({last})")


def fetch_catalog(lang: str = "cn") -> list[dict]:
    """拉 characters + discs，返回 id/kind/name/rarity + 立绘路径。"""
    from stellasora_toolkit.catalog import is_gacha_item

    items: list[dict] = []
    for endpoint, kind, rarity_key in (
        (f"characters?lang={lang}", "traveler", "grade"),
        (f"discs?lang={lang}", "disc", "star"),
    ):
        rows = json.loads(_get(f"{API_BASE}/{endpoint}").decode("utf-8"))
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                item_id = int(row["id"])
                rarity = int(row.get(rarity_key) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            name = str(row.get("name") or "").strip()
            if not name or not is_gacha_item(item_id):
                continue
            items.append({
                "id": item_id,
                "kind": kind,
                "name": name,
                "rarity": rarity,
                "icon": str(row.get("icon") or ""),
                "portrait": str(row.get("portrait") or ""),
                "base": str(row.get("base") or ""),
            })
    return items


def download_asset(path: str, target: Path) -> bool:
    """下载一张立绘；已存在且非空就不重复下载。"""
    if target.is_file() and target.stat().st_size > 0:
        return False
    if not path:
        return False
    payload = _get(f"{ASSET_BASE}{path}", timeout=120.0, retries=3)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return True


# --------------------------------------------------------------------------- 差异

def plan(fetched: list[dict], tables: SimpleNamespace) -> dict[str, list[dict]]:
    """对比线上目录与静态表，返回 4 类待补条目。"""
    missing: dict[str, list[dict]] = {
        "travelers": [],        # 名称表里的新旅人（含四星）
        "five_travelers": [],   # 缺少五星标记的新旅人
        "discs": [],            # 名称表里的非五星秘纹
        "five_discs": [],       # 新五星秘纹（名字与五星标记一起补）
    }
    for item in fetched:
        item_id, rarity = item["id"], item["rarity"]
        if item["kind"] == "traveler":
            if item_id not in tables.TRAVELER_NAMES:
                missing["travelers"].append(item)
            if rarity >= 5 and item_id not in tables.FIVE_STAR_TRAVELERS:
                missing["five_travelers"].append(item)
        elif rarity >= 5:
            if item_id not in tables.FIVE_STAR_DISCS:
                missing["five_discs"].append(item)
        elif item_id not in tables.DISC_NAMES:
            missing["discs"].append(item)
    return missing


def asset_candidates(item: dict) -> list[str]:
    """按仓库现有资源的口径挑图：旅人用头像 icon，秘纹用大图 base。"""
    if item["kind"] == "traveler":
        return [path for path in (item.get("icon"), item.get("portrait")) if path]
    return [path for path in (item.get("base"), item.get("icon")) if path]


def asset_path(item: dict) -> Path:
    folder = "travelers" if item["kind"] == "traveler" else "discs"
    return ASSETS / folder / f"{item['id']}.png"


# --------------------------------------------------------------------------- 写回 catalog.py

def _block_span(lines: list[str], name: str) -> tuple[int, int]:
    """返回 (赋值那一行, 收尾大括号那一行) 的下标。"""
    pattern = re.compile(rf"^{re.escape(name)} = \{{$")
    for start, line in enumerate(lines):
        if pattern.match(line.rstrip("\r\n")):
            for close in range(start + 1, len(lines)):
                if lines[close].strip() == "}":
                    return start, close
            raise ValueError(f"{name} 的收尾大括号没找到")
    raise ValueError(f"{name} 的定义没找到")


def _ids_in_block(lines: list[str], start: int, close: int) -> set[int]:
    """块内已有的 id（DISC_NAMES 会把好几条写在同一行，必须逐条找）。"""
    ids: set[int] = set()
    for line in lines[start + 1:close]:
        for match in re.finditer(r"(\d+)\s*(?=[,:])", line):
            ids.add(int(match.group(1)))
    return ids


def insert_entries(source: str, block: str, entries: list[tuple[int, str]]) -> tuple[str, list[tuple[int, str]]]:
    """把 ``(id, 一行源码)`` 追加到指定字典/集合的末尾；已存在的 id 跳过。

    返回 (新源码, 真正插入的条目) —— 重复执行是幂等的。
    """
    if not entries:
        return source, []
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)
    start, close = _block_span([line.rstrip("\r\n") for line in lines], block)
    existing = _ids_in_block([line.rstrip("\r\n") for line in lines], start, close)
    fresh = [(item_id, text) for item_id, text in entries if item_id not in existing]
    if not fresh:
        return source, []
    insert_at = close
    new_lines = [text + newline for _item_id, text in sorted(fresh, key=lambda pair: pair[0])]
    lines[insert_at:insert_at] = new_lines
    return "".join(lines), fresh


def catalog_source_path(path: Path | None = None) -> Path:
    return Path(path) if path else CATALOG_PATH


def read_catalog_tables(path: Path | None = None) -> SimpleNamespace:
    """读 catalog.py 里的三张表（不 import，避免污染当前进程）。"""
    import importlib.util

    target = catalog_source_path(path)
    spec = importlib.util.spec_from_file_location("catalog_snapshot", target)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return SimpleNamespace(
        TRAVELER_NAMES=dict(module.TRAVELER_NAMES),
        DISC_NAMES=dict(module.DISC_NAMES),
        FIVE_STAR_TRAVELERS=set(module.FIVE_STAR_TRAVELERS),
        FIVE_STAR_DISCS=dict(module.FIVE_STAR_DISCS),
    )


def name_literal(name: str) -> str:
    """生成安全的 Python 字符串字面量（双引号，与 catalog.py 的写法一致）。

    名字来自公开接口，可能带双引号/反斜杠/换行；直接拼进 ``"..."`` 会写出语法错误
    甚至改变原名的源码。JSON 的字符串转义是 Python 字面量的子集（``\\"``、``\\\\``、
    ``\\n``、``\\uXXXX`` 都合法），所以这里用 ``json.dumps`` 来转义。
    """
    return json.dumps(str(name), ensure_ascii=False)


def rewrite_catalog(source: str, missing: dict[str, list[dict]]) -> tuple[str, dict[str, list[dict]]]:
    """把待补条目写进四块；返回 (新源码, 实际写入的条目)。"""
    applied: dict[str, list[dict]] = {"travelers": [], "five_travelers": [], "discs": [], "five_discs": []}

    def apply(block: str, key: str, render) -> None:
        nonlocal source
        entries = [(item["id"], render(item)) for item in missing[key]]
        source, fresh = insert_entries(source, block, entries)
        written = {item_id for item_id, _text in fresh}
        applied[key] = [item for item in missing[key] if item["id"] in written]

    def name_line(item: dict) -> str:
        return f'    {item["id"]}: {name_literal(item["name"])},'

    apply(BLOCK_TRAVELERS, "travelers", name_line)
    apply(BLOCK_FIVE_TRAVELERS, "five_travelers", lambda item: f'    {item["id"]},')
    apply(BLOCK_DISCS, "discs", name_line)
    apply(BLOCK_FIVE_DISCS, "five_discs", name_line)
    return source, applied


def verify_catalog(source_path: Path, wanted: list[dict]) -> list[str]:
    """重新读一遍写好的 catalog.py，确认这些 id 现在都能回显名字。

    名称一律校验；五星标记只对**本该是五星**的条目校验 —— ``plan()`` 会把新三星/四星
    秘纹的"名字"也收进来（它们只进 ``DISC_NAMES``），若无条件要求五星，整批更新都会
    被自检拦下。rarity 缺失时按五星处理（``fetch_catalog`` 总是带 rarity）。

    用显式的 ``SourceFileLoader``：写回前校验的是 ``catalog.py.tmp``，光凭扩展名
    ``spec_from_file_location`` 认不出它是 Python 源码。
    """
    import importlib.machinery
    import importlib.util

    module_name = f"catalog_verify_{abs(hash(str(source_path)))}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(source_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    problems = []
    for item in wanted:
        resolved = module.gacha_item_name(item["id"])
        if resolved != item["name"]:
            problems.append(f'{item["id"]} -> {resolved}')
            continue
        expected_five = int(item.get("rarity") or 5) >= 5
        if expected_five and not module.is_five_star_item(item["id"]):
            problems.append(f'{item["id"]} 没有登记成五星')
    return problems


def write_catalog_atomic(target: Path, source: str, expected: list[dict]) -> None:
    """先做语法与内容校验, 通过后才**原子替换** catalog.py。

    校验或自检失败时抛异常, 原文件一个字节都不动。做法: 写到同目录的 ``.tmp``,
    用真正的模块加载器 import 一遍确认名字能回显, 最后 ``os.replace`` 换过去。
    """
    ast.parse(source)                          # 语法错误在这里就抛出去, 不碰原文件
    target = Path(target)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(source, encoding="utf-8", newline="")
    try:
        problems = verify_catalog(temp, expected)
        if problems:
            raise RuntimeError("写入自检失败: " + "; ".join(problems))
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- 主流程

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="补齐新五星角色/秘纹的静态目录")
    parser.add_argument("--check", action="store_true", help="只报告差异，不改任何文件")
    parser.add_argument("--no-tests", action="store_true", help="跳过最后的回归测试")
    parser.add_argument("--lang", default="cn", help="StellaBase 语言参数（默认 cn）")
    args = parser.parse_args(argv)

    print(f"== 拉取目录 ({args.lang}) ...", flush=True)
    fetched = fetch_catalog(args.lang)
    travelers = sum(1 for item in fetched if item["kind"] == "traveler")
    print(f"   线上: {len(fetched)} 条（旅人 {travelers} / 秘纹 {len(fetched) - travelers}）")

    tables = read_catalog_tables()
    missing = plan(fetched, tables)
    stale_total = sum(len(value) for value in missing.values())

    for key, label in (("travelers", "缺名字的旅人"), ("five_travelers", "缺五星标记的旅人"),
                       ("discs", "缺名字的秘纹"), ("five_discs", "缺名字的五星秘纹")):
        if missing[key]:
            print(f"   {label}: " + ", ".join(f'{item["id"]} {item["name"]}' for item in missing[key]))

    missing_assets = []
    for item in fetched:
        if item["kind"] == "disc" and item["rarity"] < 5:
            continue                      # 秘纹只给五星打包立绘（对齐测试的口径）
        if not asset_path(item).is_file() and asset_candidates(item):
            missing_assets.append(item)

    if args.check:
        if not stale_total and not missing_assets:
            print("静态目录已是最新，立绘也齐了。")
            return 0
        print(f"体检结果: {stale_total} 条目录待补，{len(missing_assets)} 张立绘缺失。")
        return 1

    if not stale_total and not missing_assets:
        print("静态目录已是最新，立绘也齐了，不需要改动。")
        return 0

    # 先下载立绘: 名字写进表里之后，测试要求每个有名字的旅人都有图。
    downloaded, failed = [], []
    for item in missing_assets:
        if item["kind"] == "disc" and item["rarity"] < 5:
            continue
        for candidate in asset_candidates(item):
            try:
                if download_asset(candidate, asset_path(item)):
                    downloaded.append(item)
                break
            except RuntimeError as error:
                print(f"   ! {item['id']} 立绘下载失败: {error}")
        else:
            failed.append(item)

    # 名字与五星标记写回 catalog.py（先校验、再原子替换，失败时原文件不动）
    source_path = CATALOG_PATH
    source = source_path.read_text(encoding="utf-8")
    new_source, applied = rewrite_catalog(source, missing)
    written = sum(1 for value in applied.values() for _ in value)
    if written:
        expected = [item for value in applied.values() for item in value]
        try:
            write_catalog_atomic(source_path, new_source, expected)
        except (SyntaxError, RuntimeError, OSError) as error:
            print(f"   ! 写回 catalog.py 失败（原文件未改动）：{error}", file=sys.stderr)
            return 2
        print(f"   catalog.py: 写入 {written} 条")

    print(f"   立绘: 新增 {len(downloaded)}，失败 {len(failed)}")
    if failed:
        print("   ! 缺图会导致 tests/test_catalog_alignment.py 失败: "
              + ", ".join(f'{item["id"]} {item["name"]}' for item in failed), file=sys.stderr)

    print("== 重建资源清单 ...", flush=True)
    rebuild = subprocess.run([sys.executable, str(ROOT / "tools" / "rebuild_resource_manifest.py")],
                             cwd=ROOT)
    if rebuild.returncode != 0:
        print("资源清单重建失败", file=sys.stderr)
        return 2

    if not args.no_tests:
        print("== 回归测试 ...", flush=True)
        tests = subprocess.run([sys.executable, str(ROOT / "tools" / "run_tests.py")], cwd=ROOT)
        if tests.returncode != 0:
            print("测试未通过，先修好再发版", file=sys.stderr)
            return 2

    print("\n完成。下一步: 提交 catalog.py + assets/ + resource_manifest*.json + resources.zip，然后发版。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
