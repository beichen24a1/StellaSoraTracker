from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from collections.abc import Sequence


def ensure_administrator(arguments: Sequence[str], *, relaunch_attempted: bool = False) -> bool:
    """Return False after handing startup to an elevated packaged process."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return True
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes = []
    shell32.IsUserAnAdmin.restype = wintypes.BOOL
    if shell32.IsUserAnAdmin():
        return True
    if relaunch_attempted:
        raise PermissionError("Administrator permissions were not granted after relaunch.")
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    parameters = subprocess.list2cmdline([*arguments, "--elevated"])
    result = shell32.ShellExecuteW(
        None, "runas", str(Path(sys.executable).resolve()), parameters, str(Path.cwd()), 1,
    )
    if (result or 0) <= 32:
        raise OSError(ctypes.get_last_error() or result or 0, "Administrator startup was cancelled or failed.")
    return False
