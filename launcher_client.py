"""Non-administrator entry point for the packaged client (``启动器.exe``).

The packaged client no longer asks for an administrator token by itself, so a
plain double-click opens the normal mode: browsing, import/export and settings
work without UAC, and the client asks for elevation only when a feature has to
read the game process. ``启动器.exe --admin`` starts the client elevated straight
away for users who always want the memory-reading features.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from stellasora_toolkit.admin import request_elevation
from stellasora_toolkit.app_updater import APP_EXE_NAME

ADMIN_FLAG = '--admin'
# Electron turns into a plain Node process when this is inherited from an IDE or
# a terminal, and the client would exit without ever showing a window.
NODE_MODE_VARIABLES = ('ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS')


def strip_node_mode_environment() -> list[str]:
    """Remove variables that would stop Electron from starting the client."""
    removed = []
    for key in NODE_MODE_VARIABLES:
        if os.environ.pop(key, None) is not None:
            removed.append(key)
    return removed


def _root() -> Path:
    base = Path(sys.executable) if getattr(sys, 'frozen', False) else Path(__file__)
    return base.resolve().parent


def launch_target(root: Path | None = None) -> Path:
    return (root or _root()) / APP_EXE_NAME


def split_arguments(arguments) -> tuple[bool, list[str]]:
    """Return ``(admin, forwarded)`` for the launcher's own command line."""
    items = [str(item) for item in arguments]
    return ADMIN_FLAG in items, [item for item in items if item != ADMIN_FLAG]


def show_error(message: str) -> None:
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(None, message, '星塔旅人数据工具', 0x10)


def main(argv=None) -> int:
    strip_node_mode_environment()
    admin, forwarded = split_arguments(sys.argv[1:] if argv is None else argv)
    executable = launch_target()
    if not executable.is_file():
        show_error(
            f'找不到 {APP_EXE_NAME}。\n\n'
            f'请把启动器.exe 与 {APP_EXE_NAME} 放在同一个文件夹后重试。'
        )
        return 1
    try:
        if admin:
            request_elevation(executable, forwarded)
        else:
            subprocess.Popen([str(executable), *forwarded], cwd=str(executable.parent))
    except OSError as error:
        show_error(f'启动失败：{error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
