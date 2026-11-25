"""The lock every writer and reader of a custom-skill history file holds."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt


@contextmanager
def locked_history_file(fd: int, *, shared: bool = False) -> Iterator[None]:
    """Hold a lock on the open history file ``fd``: exclusive, or ``shared``.

    ``O_APPEND`` makes one write atomic, but finishing a short write takes a
    second one, and no other record may land between the two. Writers hold the
    lock exclusively across all of a record's writes. Readers hold it shared, so
    they never see a record that is still being written. The lock belongs to the
    open file, so it also serializes two threads of one process, which open the
    file separately. Take it last: a holder acquires no other lock meanwhile.

    ``msvcrt.locking`` has no shared mode, so on Windows readers lock
    exclusively as well.
    """
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
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
