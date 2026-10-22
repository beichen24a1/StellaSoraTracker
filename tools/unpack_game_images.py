"""解包《星塔旅人》国服客户端的图片资源(Texture2D → PNG)。

用法:
    python tools/unpack_game_images.py            # 人物/CG/秘纹/封面这一档
    python tools/unpack_game_images.py --all      # 连 UI/场景/特效一起解
    python tools/unpack_game_images.py --groups char_l2d,cg
    python tools/unpack_game_images.py --list     # 只看有哪些分组

输出: E:/123/<分组>/<bundle 名>/<贴图名>.png + _manifest.csv（可断点续跑, 已存在的跳过）
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

GAME_DIR = Path(r"F:\YostarGames\StellaSora_CN")
STORE_DIRS = (
    "Persistent_Store/AssetBundles",
    "Patch_Store/AssetBundles",
    "xtlr_Data/StreamingAssets/InstallResource",   # 基础安装包(官方清单覆盖的那批)
)
DEFAULT_OUT = Path(r"E:\123")

# 第一档: 人/剧情图/秘纹 —— 玩家真正想看的"图片资源"
ART_GROUPS = (
    "char_avg_2d", "char_2d", "char_l2d", "char_sd",
    "actor_l2d_common", "actor_common",
    "disc", "disc_l2d", "disc_l2d_common", "cg",
    "ui_gachacover", "npc", "npc_l2d", "travelerduel",
)


def group_of(stem: str) -> str:
    """把 bundle 名归到一个可读的分组里(去掉末尾的序号/语言后缀)。"""
    name = stem
    for suffix in (".tw",):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    parts = name.split("_")
    if not parts:
        return "other"
    head = parts[0]
    if head in ("char", "disc", "actor", "npc", "fx", "ui", "cg", "mons", "env", "storyactivity"):
        # char_avg_2d_avg1_103 → char_avg_2d ; char_l2d_10704 → char_l2d
        if head == "char" and len(parts) > 1:
            return "_".join(parts[:3]) if parts[1] == "avg" else "_".join(parts[:2])
        if head == "ui" and len(parts) > 1:
            return "_".join(parts[:2])
        return head
    return head


def collect(groups: set[str] | None) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    for store in STORE_DIRS:
        root = GAME_DIR / store
        if not root.is_dir():
            continue
        for path in root.glob("*.unity3d"):
            if path.stem.endswith(".tw"):        # 繁体版内容与简体一致, 跳过省空间
                continue
            group = group_of(path.stem)
            if groups is not None and group not in groups:
                continue
            items.append((path, group))
    return items


def unpack(items: list[tuple[Path, str]], out_dir: Path) -> int:
    import UnityPy

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "_manifest.csv"
    new_file = not manifest_path.exists()
    saved = skipped = failed = 0
    started = time.time()
    with manifest_path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["group", "bundle", "texture", "width", "height", "format",
                             "bytes", "path"])
        for index, (bundle, group) in enumerate(items, 1):
            target_dir = out_dir / group / bundle.stem
            try:
                env = UnityPy.load(str(bundle))
            except Exception as error:                      # noqa: BLE001
                failed += 1
                print(f"[{index}/{len(items)}] 打不开 {bundle.name}: {error}", flush=True)
                continue
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    data = obj.read()
                    name = str(getattr(data, "m_Name", "") or f"pathid_{obj.path_id}")
                    safe = "".join(ch if ch.isalnum() or ch in "._-()" else "_" for ch in name)
                    target = target_dir / f"{safe}.png"
                    if target.is_file() and target.stat().st_size > 0:
                        skipped += 1
                        continue
                    image = data.image
                    target_dir.mkdir(parents=True, exist_ok=True)
                    image.save(target, format="PNG")
                    saved += 1
                    writer.writerow([group, bundle.stem, name, image.size[0], image.size[1],
                                     str(getattr(data, "m_TextureFormat", "")),
                                     target.stat().st_size, str(target.relative_to(out_dir))])
                except Exception as error:                  # noqa: BLE001
                    failed += 1
                    if failed < 30:
                        print(f"  跳过贴图 {bundle.name}: {type(error).__name__} {error}", flush=True)
            if index % 25 == 0 or index == len(items):
                elapsed = time.time() - started
                print(f"[{index}/{len(items)}] 新存 {saved} 张 / 跳过 {skipped} / 失败 {failed}"
                      f" · {elapsed:.0f}s", flush=True)
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="解包游戏图片资源")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--all", action="store_true", help="连 UI/场景/特效一起解")
    parser.add_argument("--groups", default="", help="只解这些分组, 逗号分隔")
    parser.add_argument("--list", action="store_true", help="只列出分组与数量")
    args = parser.parse_args(argv)

    if args.list:
        counts: Counter[str] = Counter()
        sizes: Counter[str] = Counter()
        for path, group in collect(None):
            counts[group] += 1
            sizes[group] += path.stat().st_size
        for group, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{group:26} {count:5} 个 bundle  {sizes[group]/1024/1024:8.1f} MB")
        return 0

    groups = None if args.all else set(ART_GROUPS)
    if args.groups:
        groups = {g.strip() for g in args.groups.split(",") if g.strip()}
    items = collect(groups)
    total_mb = sum(p.stat().st_size for p, _ in items) / 1024 / 1024
    print(f"待解 {len(items)} 个 bundle / {total_mb:.0f} MB → {args.out}", flush=True)
    saved = unpack(items, args.out.resolve())
    print(f"完成: 新存 {saved} 张 PNG 到 {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
