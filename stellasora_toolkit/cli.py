from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .service import extract_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读导出《星塔旅人》招募记录")
    parser.add_argument("--process", default="xtlr.exe", help="游戏进程名（默认：xtlr.exe）")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd() / "exports",
        help="导出目录（默认：当前目录下 exports）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot = extract_snapshot(args.output, args.process, progress=print)
        print(
            f"完成：{len(snapshot.gacha)} 组招募记录，共 {snapshot.pull_count} 个结果。"
        )
        for path in snapshot.files:
            print(path)
        return 0
    except (OSError, ValueError, LookupError, ProcessLookupError) as error:
        print(f"导出失败：{error}", file=sys.stderr)
        return 1
