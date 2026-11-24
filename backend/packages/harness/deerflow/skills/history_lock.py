"""The exclusive lock every writer of a custom-skill history file holds."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt


@contextmanager
def locked_history_file(fd: int) -> Iterator[None]:
    """Hold an exclusive lock on the open history file ``fd``.

    ``O_APPEND`` makes one write atomic, but finishing a short write takes a
    second one, and no other record may land between the two. The lock belongs
    to the open file, so it also serializes two threads of one process, which
    open the file separately. Take it last: a history writer acquires no other
    lock while holding it.
    """
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
    else:  # pragma: no cover - Windows
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    try:
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:  # pragma: no cover - Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
