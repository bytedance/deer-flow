"""Contention-only retries for non-blocking advisory file locks."""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Callable
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


_REPLACE_RETRY_SECONDS = 5.0
_REPLACE_RETRY_INTERVAL_SECONDS = 0.05
_WINDOWS_SHARING_ERRORS = {5, 32}  # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION


def replace_with_retry(
    source: str | Path,
    target: str | Path,
    *,
    deadline_seconds: float = _REPLACE_RETRY_SECONDS,
    interval: float = _REPLACE_RETRY_INTERVAL_SECONDS,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> None:
    """Atomically replace *target* with *source*, retrying Windows sharing errors.

    On Windows, ``os.replace`` fails with ``ERROR_ACCESS_DENIED`` or
    ``ERROR_SHARING_VIOLATION`` while another process holds the target open.
    Those are transient sharing conflicts, not permission changes, so retry
    only them for a short bounded period. Every other error (including POSIX
    ``EACCES``) is raised immediately.
    """
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + deadline_seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error, "winerror", None) not in _WINDOWS_SHARING_ERRORS:
                raise
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            sleep(min(interval, remaining))
