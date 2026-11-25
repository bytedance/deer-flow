"""Advisory file locks and contention-only retries."""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_RETRY_INTERVAL_SECONDS = 0.2


def retry_until_locked(
    acquire: Callable[[], None],
    *,
    interval: float = LOCK_RETRY_INTERVAL_SECONDS,
    deadline: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    check: Callable[[], None] | None = None,
    timeout_message: str = "File lock acquisition timed out",
) -> None:
    """Retry only contention, optionally bounded by an absolute monotonic deadline.

    Windows' blocking ``msvcrt.LK_LOCK`` gives up after about ten seconds.
    Callers instead acquire with ``LK_NBLCK`` and choose their own deadline;
    omitting it preserves an indefinite wait. Sleep/clock injection keeps
    tests local rather than replacing functions on the shared time module.
    """
    while True:
        if check is not None:
            check()
        try:
            acquire()
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            delay = interval
            if deadline is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError(timeout_message) from None
                delay = min(delay, remaining)
            sleep(delay)


@contextmanager
def advisory_file_lock(lock_path: Path) -> Iterator[None]:
    """Lock a stable sidecar across threads and processes; never unlink it."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            # msvcrt can lock beyond EOF. Keep the sidecar empty so workers
            # do not race to initialize a byte before acquiring its lock.
            lock_file.seek(0)
            retry_until_locked(
                lambda: msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1),
            )
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
