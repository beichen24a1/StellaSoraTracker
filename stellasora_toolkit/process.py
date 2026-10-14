from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator
from collections.abc import Iterable


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GAME_EXECUTABLES = ("xtlr.exe", "StellaSora.exe")
TH32CS_SNAPPROCESS = 0x00000002
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE_PAGE_FLAGS = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


@dataclass(frozen=True)
class GameProcess:
    name: str
    pid: int
    path: str = ""


@dataclass(frozen=True)
class MemoryRegion:
    base: int
    size: int
    protect: int

    @property
    def end(self) -> int:
        return self.base + self.size


def running_processes() -> list[tuple[str, int]]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        processes: list[tuple[str, int]] = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            processes.append((entry.szExeFile, int(entry.th32ProcessID)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error not in (0, 18):  # ERROR_NO_MORE_FILES is the normal end of enumeration.
            raise OSError(error, "Process enumeration failed")
        return processes
    finally:
        kernel32.CloseHandle(snapshot)


def _process_image_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _executable_names(executable: str | Iterable[str] | None) -> tuple[str, ...]:
    names = GAME_EXECUTABLES if executable is None else (executable,) if isinstance(executable, str) else tuple(executable)
    if not names or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("游戏进程名不能为空")
    return names


def find_game_processes(executable: str | Iterable[str] | None = None) -> list[GameProcess]:
    wanted = {name.casefold() for name in _executable_names(executable)}
    return sorted(
        (GameProcess(name, pid, _process_image_path(pid))
         for name, pid in running_processes() if name.casefold() in wanted),
        key=lambda process: (process.name.casefold(), process.pid),
    )


def find_process_id(executable: str | Iterable[str] | None = None, *, pid: int | None = None) -> int:
    names = _executable_names(executable)
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        raise ValueError("PID 必须是正整数")
    processes = find_game_processes(names)
    if pid is not None:
        if any(process.pid == pid for process in processes):
            return pid
        raise ProcessLookupError(f"所选游戏进程 PID {pid} 已退出或不再匹配，请重新刷新并选择客户端")
    if len(processes) == 1:
        return processes[0].pid
    if not processes:
        raise ProcessLookupError(f"未找到游戏进程 {' / '.join(names)}，请先登录游戏并进入主界面")
    choices = "、".join(f"{process.name} (PID {process.pid})" for process in processes)
    raise ProcessLookupError(f"检测到多个游戏客户端：{choices}。请在界面选择一个，或通过 --pid 指定，避免混入其他账号")


class RemoteProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f"无法只读打开进程 PID {pid}")
        self._regions: list[MemoryRegion] | None = None

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "RemoteProcess":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def regions(self) -> list[MemoryRegion]:
        if self._regions is not None:
            return self._regions
        result: list[MemoryRegion] = []
        address = 0
        maximum = (1 << 47) - 1
        mbi = MEMORY_BASIC_INFORMATION()
        while address < maximum:
            queried = kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if not queried:
                break
            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize)
            basic_protect = int(mbi.Protect) & 0xFF
            if (
                mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and basic_protect != PAGE_NOACCESS
                and basic_protect in READABLE_PAGE_FLAGS
            ):
                result.append(MemoryRegion(base, size, int(mbi.Protect)))
            next_address = base + max(size, 0x1000)
            if next_address <= address:
                break
            address = next_address
        self._regions = result
        return result

    def region_for(self, address: int) -> MemoryRegion | None:
        for region in self.regions():
            if region.base <= address < region.end:
                return region
        return None

    def is_readable(self, address: int, size: int = 1) -> bool:
        region = self.region_for(address)
        return region is not None and address + size <= region.end

    def read(self, address: int, size: int) -> bytes:
        if size < 0 or size > 128 * 1024 * 1024:
            raise ValueError(f"invalid read size: {size}")
        buffer = ctypes.create_string_buffer(size)
        read_count = ctypes.c_size_t()
        ok = kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read_count),
        )
        if not ok or read_count.value != size:
            raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:x}")
        return buffer.raw

    def try_read(self, address: int, size: int) -> bytes | None:
        try:
            return self.read(address, size)
        except (OSError, ValueError):
            return None

    def unpack(self, fmt: str, address: int):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def scan(self, pattern: bytes, regions: Iterator[MemoryRegion] | None = None) -> Iterator[int]:
        if not pattern:
            return
        chunk_size = 4 * 1024 * 1024
        overlap = len(pattern) - 1
        for region in regions or iter(self.regions()):
            offset = 0
            tail = b""
            while offset < region.size:
                take = min(chunk_size, region.size - offset)
                block = self.try_read(region.base + offset, take)
                if block is None:
                    offset += take
                    tail = b""
                    continue
                data = tail + block
                search_from = 0
                while True:
                    found = data.find(pattern, search_from)
                    if found < 0:
                        break
                    yield region.base + offset - len(tail) + found
                    search_from = found + 1
                tail = data[-overlap:] if overlap else b""
                offset += take
