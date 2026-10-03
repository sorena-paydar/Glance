"""Keep a single Glance desktop app running at a time."""

from __future__ import annotations

import sys
import time

from glance.config import cache_dir

_lock_file = None  # held open for the life of the process


def already_running(wait: float = 5.0) -> bool:
    """Take the app lock; True if another Glance holds it.

    Waits up to ``wait`` seconds, so a Glance that is restarting itself can exit
    before the new instance gives up.
    """
    global _lock_file
    path = cache_dir() / "app.lock"
    handle = open(path, "a+")  # noqa: SIM115 - must stay open to hold the lock
    deadline = time.monotonic() + wait
    while True:
        if _try_lock(handle):
            _lock_file = handle
            return False
        if time.monotonic() >= deadline:
            handle.close()
            return True
        time.sleep(0.2)


def _try_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True
