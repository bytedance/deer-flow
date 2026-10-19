"""Behavior tests for the remaining blocking Windows advisory lock.

``msvcrt.LK_LOCK`` gives up after roughly ten seconds and surfaces contention
as ``Permission denied``. The config read-merge-write-reload cycle can
legitimately be held longer than that, so the Windows fallback branch retries
the non-blocking acquisition until the region frees, mirroring what
``fcntl.flock(LOCK_EX)`` does on POSIX.

The Windows test runs only on Windows because ``extensions_config`` selects
the branch off ``os.name`` (faking it breaks ``pathlib.Path``); the ``flock``
test runs on POSIX only. Both stay honest about the platform instead of
faking the branch guard.
"""

from __future__ import annotations

import errno
import os
import sys

import pytest

from deerflow.config import extensions_config
from deerflow.utils.file_lock import retry_until_locked


class _ContendedFakeMsvcrt:
    """Fake ``msvcrt`` whose lock region stays busy for the first N attempts.

    Records every ``locking`` call so tests can assert the retry cadence and
    the final unlock, independently of the real Windows semantics.
    """

    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self, fail_times: int, *, error_number: int = errno.EDEADLK) -> None:
        self.fail_times = fail_times
        self.error_number = error_number
        self.attempts: list[int] = []
        self.unlocked = 0

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.attempts.append(mode)
        if mode == self.LK_UNLCK:
            self.unlocked += 1
            return None
        blocking_attempts = len(self.attempts) - self.unlocked
        if blocking_attempts <= self.fail_times:
            raise OSError(self.error_number, "Lock unavailable")
        return None


class _RecordingFcntl:
    """Fake ``fcntl`` that records ``flock`` operations."""

    LOCK_EX = 2
    LOCK_UN = 8

    def __init__(self) -> None:
        self.ops: list[int] = []

    def flock(self, fd, operation: int) -> None:
        self.ops.append(operation)


def _timed_retry_factory(sleeps: list[float]):
    """Wrap the shared retry helper so the cadence stays observable."""

    def timed_retry(acquire, **kwargs):
        return retry_until_locked(acquire, sleep=sleeps.append, **kwargs)

    return timed_retry


@pytest.mark.skipif(os.name != "nt", reason="exercises the Windows msvcrt fallback branch")
def test_extensions_config_lock_retries_until_contention_clears(tmp_path, monkeypatch) -> None:
    """The config RMW lock retries the Windows fallback instead of failing."""
    fake = _ContendedFakeMsvcrt(fail_times=3)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    sleeps: list[float] = []
    monkeypatch.setattr(
        extensions_config,
        "retry_until_locked",
        _timed_retry_factory(sleeps),
        raising=False,
    )

    config_path = tmp_path / "extensions.json"
    entered = False
    with extensions_config.extensions_config_file_lock(config_path):
        entered = True

    assert entered
    assert fake.attempts == [fake.LK_NBLCK] * 4 + [fake.LK_UNLCK]
    assert fake.unlocked == 1
    assert sleeps == [0.2] * 3


@pytest.mark.skipif(os.name == "nt", reason="exercises the POSIX flock branch")
def test_extensions_config_lock_posix_branch_still_flocks(tmp_path, monkeypatch) -> None:
    """The POSIX branch keeps using ``fcntl.flock`` unchanged."""
    fake_fcntl = _RecordingFcntl()
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

    config_path = tmp_path / "extensions.json"
    entered = False
    with extensions_config.extensions_config_file_lock(config_path):
        entered = True

    assert entered
    assert fake_fcntl.ops == [_RecordingFcntl.LOCK_EX, _RecordingFcntl.LOCK_UN]
