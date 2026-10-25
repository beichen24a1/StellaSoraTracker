"""Reentrant transactions for one exports directory, including across processes."""
from __future__ import annotations

import errno
import inspect
import os
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

LOCK_FILENAME = '.storage.lock'
_states = {}
_states_guard = threading.Lock()


class _LockState:
    def __init__(self):
        self.gate = threading.RLock()
        self.depth = 0


def storage_root(directory: Path) -> Path:
    path = Path(directory).resolve()
    return path.parent.parent if path.parent.name == 'accounts' else path


@contextmanager
def storage_transaction(directory: Path, *, timeout: float = 10.0):
    root = storage_root(directory)
    key = os.path.normcase(str(root))
    with _states_guard:
        state = _states.setdefault(key, _LockState())
    message = '另一个窗口正在保存此目录的数据，请稍后重试；本次操作未覆盖归档'
    if not state.gate.acquire(timeout=timeout):
        raise OSError(errno.EBUSY, message)
    handle = None
    acquired = False
    try:
        if state.depth == 0:
            root.mkdir(parents=True, exist_ok=True)
            handle = (root / LOCK_FILENAME).open('a+b')
            # Reading byte zero before owning its Windows range lock fails with
            # EACCES while another process holds it. Inspect the size instead.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'\0')
                handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise OSError(errno.EBUSY, message)
                    time.sleep(0.025)
        state.depth += 1
        try:
            yield
        finally:
            state.depth -= 1
    finally:
        try:
            if handle is not None:
                try:
                    if acquired:
                        handle.seek(0)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
        finally:
            state.gate.release()


def serialized_storage(function):
    parameter = next(iter(inspect.signature(function).parameters))
    @wraps(function)
    def call(*args, **kwargs):
        if not args and parameter not in kwargs:
            return function(*args, **kwargs)
        directory = args[0] if args else kwargs[parameter]
        with storage_transaction(directory):
            return function(*args, **kwargs)
    return call
