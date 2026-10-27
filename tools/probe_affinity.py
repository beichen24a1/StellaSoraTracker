# -*- coding: utf-8 -*-
"""诊断脚本: 直接从游戏内存列出角色好感度(只读)。

用法(游戏要开着并已登录, **建议用管理员身份运行**):
    python tools/probe_affinity.py            # 列出全部角色
    python tools/probe_affinity.py --pid 1234 # 多开时指定进程
    python tools/probe_affinity.py --json     # 机器可读输出

输出与程序里的「好感度」页用的是同一套读取逻辑: 等级、当前经验、升级所需经验。
不写任何文件、不改游戏内存。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stellasora_toolkit import affinity as affinity_reader  # noqa: E402
from stellasora_toolkit import server_config  # noqa: E402
from stellasora_toolkit.process import (  # noqa: E402
    RemoteProcess, find_process_id, running_processes,
)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="从游戏内存读取角色好感度")
    parser.add_argument("--pid", type=int, default=0, help="指定游戏进程 PID(多开时用)")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)
    try:
        return _probe(args)
    except ProcessLookupError as err:
        print(f"\n找不到游戏进程: {err}")
        print("请确认游戏已启动并登录，且客户端是国服 xtlr.exe / 国际服 StellaSora.exe。")
        return 2
    except OSError as err:
        print(f"\n打不开游戏进程: {err}")
        print("最常见的原因是没有管理员权限。请用【管理员身份】打开 PowerShell 再运行。")
        return 3
    except LookupError as err:
        print(f"\n读取失败: {err}")
        return 4


def _probe(args) -> int:
    running = [name for name, _pid in running_processes()]
    clients = sorted({name for name in running if name.casefold() in ("xtlr.exe", "stellasora.exe")})
    profile, _keys = server_config.resolve_running(running)
    names = (profile.client_names if profile else
             [n for prof in server_config.PROFILES.values() for n in prof.client_names])
    pid = find_process_id(names, pid=args.pid or None)
    if not args.json:
        print(f"运行中的客户端: {clients or '(没有)'} → 连接 PID {pid}")
    started = time.perf_counter()
    with RemoteProcess(pid) as process:
        rows = affinity_reader.read_affinity(process)
    elapsed = time.perf_counter() - started

    if args.json:
        print(json.dumps({
            "pid": pid,
            "elapsed": round(elapsed, 2),
            "entries": [row.as_dict() for row in rows],
        }, ensure_ascii=False, indent=2))
        return 0 if rows else 1

    if not rows:
        print("没有读到角色数据。请先在游戏里打开一次「角色」界面，再运行本脚本。")
        return 1
    print(f"\n共 {len(rows)} 位旅人（耗时 {elapsed:.2f}s）")
    print(f"{'角色':<12}{'好感等级':>8}{'当前经验':>10}{'升级所需':>10}{'进度':>8}")
    for row in rows:
        progress = f"{row.ratio * 100:.0f}%" if row.need else "—"
        print(f"{row.name:<12}{row.level:>8}{row.exp:>10}{row.need:>10}{progress:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
