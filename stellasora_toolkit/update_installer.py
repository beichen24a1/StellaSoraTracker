"""Apply a downloaded update: replace the program files, then restart the app.

The updater normally runs with an administrator token, because the client
manifest asks for one. Anything it *moves* keeps the security descriptor it had
inside the updater's temporary work directory, so a program file could end up
readable only by Administrators. A later double-click then fails with access
denied before UAC can even prompt, which looks exactly like a dead launcher.
Installed entries are therefore *copied* into the program folder so they inherit
its permissions, and the result is verified before the previous files are
discarded.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath


APP_EXE_NAME = "StellaSoraGachaTool.exe"
UPDATER_EXE_NAME = "StellaSoraUpdater.exe"
WAIT_TIMEOUT_SECONDS = 180
PRESERVED_TOP_LEVELS = {"exports", "updates", "backups", ".desktop"}
# Leftovers younger than this may still belong to an update that is running.
STALE_UPDATER_SECONDS = 60 * 60
STALE_WORK_SECONDS = 7 * 24 * 60 * 60

# Access bits used by the post-install check: the parts of FILE_GENERIC_READ /
# FILE_GENERIC_EXECUTE that any normal program folder grants.
_FILE_READ_DATA = 0x0001
_FILE_EXECUTE = 0x0020
_FILE_READ_ATTRIBUTES = 0x0080
_SYNCHRONIZE = 0x00100000
_READ_RIGHTS = _FILE_READ_DATA | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
_EXECUTE_RIGHTS = _READ_RIGHTS | _FILE_EXECUTE
_ACCESS_ALLOWED_ACE_TYPE = 0
_ACCESS_DENIED_ACE_TYPE = 1
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_OWNER_RIGHTS_SID = "S-1-3-4"
# A launch from Explorer keeps these. Administrators is deny-only once UAC
# filters the token, so membership there does not mean the user can open a file.
_LAUNCH_GROUP_SIDS = ("S-1-5-32-545", "S-1-1-0", "S-1-5-11")


def _log_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "StellaSoraGachaTool" / "logs"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.gettempdir()) / 'StellaSoraUpdater.log'
    return root / "updater.log"


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _log_path().open("a", encoding="utf-8") as output:
            output.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass  # A diagnostic failure must not stop update/rollback handling.


def wait_for_process_exit(pid: int, timeout: float = WAIT_TIMEOUT_SECONDS) -> None:
    if pid <= 0 or os.name != "nt":
        return
    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == wait_timeout:
            raise TimeoutError("等待主程序退出超时")
        if result != wait_object_0:
            raise OSError(f"等待主程序退出失败：{result}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _temp_roots() -> list[Path]:
    """Every directory our leftovers may live in: the temp dir plus TEMP/TMP."""
    roots: list[Path] = []
    seen: set[str] = set()
    for value in (tempfile.gettempdir(), os.environ.get("TEMP"), os.environ.get("TMP")):
        if not value:
            continue
        try:
            path = Path(value).resolve()
            if not path.is_dir() or str(path).casefold() in seen:
                continue
        except OSError:
            continue
        seen.add(str(path).casefold())
        roots.append(path)
    return roots


def _delete_leftover(path: Path) -> bool:
    """Delete one stale directory, returning whether it is gone.

    Files written by an elevated update carry an ACL whose ``OWNER RIGHTS`` entry
    matches the elevated token, so even the folder owner is refused a plain
    delete. Resetting the tree to the temp folder's permissions makes the
    leftovers removable again.
    """
    shutil.rmtree(path, ignore_errors=True)
    if not path.exists():
        return True
    try:
        subprocess.run(
            ["icacls", str(path), "/reset", "/T", "/C", "/Q"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def prune_stale_directories(keep: Path | None = None, *, roots: list[Path] | None = None) -> list[Path]:
    """Remove helper/work directories that earlier updates left in the temp folder.

    A finished update cleans its own helper directory, but that cleanup can lose a
    race with the still-exiting updater, so empty shells accumulate over time.
    Recent directories are left alone: they may belong to a running update.
    """
    if os.name != "nt":
        return []
    keep_path = keep.resolve() if keep else None
    candidates: list[Path] = []
    seen: set[str] = set()
    for temp in (roots if roots is not None else _temp_roots()):
        for prefix, max_age in (("stellasora-updater-", STALE_UPDATER_SECONDS),
                                ("stellasora-update-work-", STALE_WORK_SECONDS)):
            try:
                found = list(Path(temp).glob(prefix + "*"))
            except OSError:
                continue
            for path in found:
                try:
                    if not path.is_dir():
                        continue
                    if keep_path is not None and path.resolve() == keep_path:
                        continue
                    if time.time() - path.stat().st_mtime < max_age:
                        continue
                    key = str(path.resolve()).casefold()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(path)

    return [path for path in candidates if _delete_leftover(path)]


def _safe_member_path(name: str) -> PurePosixPath:
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute() or not member.parts:
        raise ValueError(f"更新包包含非法路径：{name}")
    if any(part in {"", ".", ".."} for part in member.parts):
        raise ValueError(f"更新包包含非法路径：{name}")
    if ":" in member.parts[0]:
        raise ValueError(f"更新包包含非法路径：{name}")
    return member


def extract_update_package(package: Path, destination: Path) -> Path:
    with zipfile.ZipFile(package, "r") as archive:
        members = [(info, _safe_member_path(info.filename)) for info in archive.infolist()]
        for info, member in members:
            target = destination.joinpath(*member.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    candidates = [destination]
    top_levels = {member.parts[0] for _, member in members}
    if len(top_levels) == 1:
        candidates.insert(0, destination / next(iter(top_levels)))
    for candidate in candidates:
        if (candidate / APP_EXE_NAME).is_file():
            forbidden = PRESERVED_TOP_LEVELS.intersection(path.name.casefold() for path in candidate.iterdir())
            if forbidden:
                names = "、".join(sorted(forbidden))
                raise ValueError(f"更新包不应包含用户数据目录：{names}")
            return candidate
    raise ValueError(f"更新包中未找到 {APP_EXE_NAME}")


def _install_entry(source: Path, target: Path) -> None:
    """Copy one payload entry into the program folder.

    ``shutil.move`` would only rename the entry and keep the security descriptor
    it got in the updater's temporary work directory (created with the elevated
    token). Copying creates new objects, so they inherit the program folder's
    permissions and the interactive user can still start the application.
    """
    if source.is_dir():
        shutil.copytree(source, target, symlinks=False)
    else:
        shutil.copy2(source, target)


class _AceHeader(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]


class _MaskedAce(ctypes.Structure):
    _fields_ = [("Header", _AceHeader), ("Mask", ctypes.c_uint32)]


def _sid_string(address) -> str | None:
    if not address:
        return None
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    text = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(address), ctypes.byref(text)):
        return None
    try:
        return text.value
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _current_user_sid() -> str | None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = ctypes.c_uint32()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(ctypes.c_void_p)))
        if not advapi32.GetTokenInformation(token, _TOKEN_USER, buffer, len(buffer), ctypes.byref(size)):
            return None
        return _sid_string(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])
    finally:
        kernel32.CloseHandle(token)


def _file_security(path: Path) -> tuple[str | None, list[tuple[int, str, int]]] | None:
    """Return ``(owner_sid, [(ace_type, sid, mask), ...])`` for a file.

    ``None`` means the object has no DACL, which grants everyone full access.
    Raises ``OSError`` when the descriptor itself cannot be read.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.GetAce.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    code = advapi32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), ctypes.byref(sacl), ctypes.byref(descriptor),
    )
    if code:
        raise ctypes.WinError(code)
    try:
        if not dacl.value:
            return None  # No DACL at all, so everyone is allowed.
        owner_sid = _sid_string(owner.value)
        aces: list[tuple[int, str, int]] = []
        index = 0
        while True:
            pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                break
            index += 1
            header = ctypes.cast(pointer, ctypes.POINTER(_AceHeader)).contents
            if header.AceType not in (_ACCESS_ALLOWED_ACE_TYPE, _ACCESS_DENIED_ACE_TYPE):
                continue
            if header.AceSize < ctypes.sizeof(_MaskedAce):
                continue
            mask = ctypes.cast(pointer, ctypes.POINTER(_MaskedAce)).contents.Mask
            sid = _sid_string(pointer.value + ctypes.sizeof(_MaskedAce))
            if sid:
                aces.append((header.AceType, sid, mask))
        return owner_sid, aces
    finally:
        kernel32.LocalFree(descriptor)


def acl_grants(candidates: set[str], needed: int, aces, *, owner: str | None = None) -> bool:
    """Whether the ACE list grants every bit of ``needed`` to one candidate SID."""
    allowed = False
    for ace_type, sid, mask in aces:
        if sid == _OWNER_RIGHTS_SID:
            sid = owner
        if sid not in candidates:
            continue
        if ace_type == _ACCESS_DENIED_ACE_TYPE and mask & needed:
            return False
        if ace_type == _ACCESS_ALLOWED_ACE_TYPE and (mask & needed) == needed:
            allowed = True
    return allowed


def plain_user_can_use(path: Path, *, execute: bool = False) -> bool | None:
    """Whether a normal (UAC-filtered) launch can read — and optionally run — this file.

    ``None`` means the question cannot be answered here, so callers must not
    treat it as a failure.
    """
    if os.name != "nt":
        return None
    try:
        security = _file_security(path)
        user = _current_user_sid()
    except OSError:
        return None
    if security is None:
        return True
    if user is None:
        return None
    owner, aces = security
    if not aces:
        return None
    needed = _EXECUTE_RIGHTS if execute else _READ_RIGHTS
    return acl_grants({user, *_LAUNCH_GROUP_SIDS}, needed, aces, owner=owner)


def verify_installation(target_dir: Path, installed: list[Path]) -> None:
    """Reject an installation an ordinary double-click could not use."""
    executable = target_dir / APP_EXE_NAME
    if not executable.is_file():
        raise RuntimeError("更新后主程序不存在")
    for entry in installed:
        files = [entry] if entry.is_file() else [path for path in entry.rglob("*") if path.is_file()]
        for path in files:
            try:
                with path.open("rb") as handle:
                    handle.read(1)
            except OSError as error:
                raise RuntimeError(f"更新后的文件无法读取：{path}（{error}）") from error
    shipped = [executable, *(entry for entry in installed if entry.is_file() and entry != executable
                             and entry.suffix.casefold() == ".exe")]
    for path in shipped:
        launchable = plain_user_can_use(path, execute=True)
        if launchable is False:
            raise RuntimeError(
                f"{path.name} 的权限只授予了管理员，普通双击会在提权前被拒绝；"
                "已回滚，请把程序放在自己能读写的目录后重试"
            )
        if launchable is None and path == executable:
            log("无法校验主程序对普通用户的权限，已跳过该检查")


def replace_program_files(payload_root: Path, target_dir: Path, backup_dir: Path) -> None:
    entries = list(payload_root.iterdir())
    if not entries:
        raise ValueError("更新包内容为空")

    moved_old: list[tuple[Path, Path]] = []
    installed_new: list[Path] = []
    try:
        for source in entries:
            target = target_dir / source.name
            if target.exists():
                backup = backup_dir / source.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
                moved_old.append((target, backup))

        for source in entries:
            target = target_dir / source.name
            # Register first so a half-copied entry is removed on rollback too.
            installed_new.append(target)
            _install_entry(source, target)

        verify_installation(target_dir, installed_new)
    except Exception:
        for target in reversed(installed_new):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        for target, backup in reversed(moved_old):
            if backup.exists():
                shutil.move(str(backup), str(target))
        raise


def apply_update(package: Path, target_dir: Path) -> Path:
    """替换程序文件, 成功后返回 work_dir(含旧程序备份)。

    备份由调用方在「重启成功」后再删除; 替换失败时 replace_program_files 内部会回滚。
    """
    package = package.resolve(strict=True)
    target_dir = target_dir.resolve(strict=True)
    work_dir = Path(tempfile.mkdtemp(prefix="stellasora-update-work-"))
    extract_dir = work_dir / "new"
    backup_dir = work_dir / "backup"
    extract_dir.mkdir()
    backup_dir.mkdir()
    log(f"开始解压更新包：{package}")
    payload_root = extract_update_package(package, extract_dir)
    log(f"开始替换程序文件：{target_dir}")
    replace_program_files(payload_root, target_dir, backup_dir)
    if not (target_dir / APP_EXE_NAME).is_file():
        raise RuntimeError("更新后主程序不存在")
    log("程序文件替换完成并通过权限校验")
    return work_dir


def restart_application(target_dir: Path, executable_name: str) -> None:
    executable = target_dir / executable_name
    if not executable.is_file():
        raise FileNotFoundError(f"无法重新启动，文件不存在：{executable}")
    subprocess.Popen([str(executable)], cwd=str(target_dir))


def schedule_self_cleanup(helper_dir: Path | None) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False) or helper_dir is None:
        return
    helper_dir = helper_dir.resolve()
    if not helper_dir.name.startswith("stellasora-updater-"):
        log(f"跳过不安全的更新器清理路径：{helper_dir}")
        return
    quoted_helper_dir = str(helper_dir).replace("'", "''")
    command = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
        f"Remove-Item -LiteralPath '{quoted_helper_dir}' -Recurse -Force -ErrorAction SilentlyContinue"
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, "星塔旅人数据工具更新失败", 0x10)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="星塔旅人数据工具更新程序")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument('--wait-pid', type=int, action='append', default=[])
    parser.add_argument("--executable", default=APP_EXE_NAME)
    parser.add_argument("--cleanup-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for stale in prune_stale_directories(keep=args.cleanup_dir):
            log(f"清理上次更新残留的临时目录：{stale}")
        log(f"更新程序启动，等待主程序 PID {args.parent_pid} 退出")
        wait_for_process_exit(args.parent_pid)
        for pid in sorted(set(args.wait_pid) - {args.parent_pid}):
            wait_for_process_exit(pid)
        work_dir = apply_update(args.package, args.target_dir)
        args.package.unlink(missing_ok=True)
        restart_application(args.target_dir.resolve(), args.executable)
        log("更新成功，已重新启动主程序")
        # 重启成功后再删除备份目录(失败时保留以便回滚)
        shutil.rmtree(work_dir, ignore_errors=True)
        schedule_self_cleanup(args.cleanup_dir)
        return 0
    except Exception as error:
        log(f"更新失败：{type(error).__name__}: {error}")
        show_error(f"自动更新未完成，原程序文件已尽量恢复。\n\n{error}\n\n日志：{_log_path()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
