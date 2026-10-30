"""Contention-only retries for non-blocking advisory file locks."""

from __future__ import annotations

import errno
import time
from collections.abc import Callable

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
