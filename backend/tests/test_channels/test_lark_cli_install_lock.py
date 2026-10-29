"""Behavior tests for the cross-process install lock in ``lark_cli``.

Windows' blocking lock mode (``msvcrt.LK_LOCK``) gives up after roughly ten
seconds and surfaces contention as ``Permission denied``. A real install
(download + setup of the lark/sandbox CLI) can hold the lock far longer, so
the fallback branch must retry the non-blocking acquisition until the region
frees, mirroring the extensions manager's lock.
"""

from __future__ import annotations

import errno
import threading
import time
from types import SimpleNamespace

import pytest

from deerflow.integrations import lark_cli


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


def test_install_lock_retries_until_contention_clears(tmp_path, monkeypatch) -> None:
    """Contention is retried on the Windows fallback instead of failing fast."""
    fake = _ContendedFakeMsvcrt(fail_times=3)
    monkeypatch.setattr(lark_cli, "fcntl", None)
    monkeypatch.setattr(lark_cli, "msvcrt", fake, raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(lark_cli, "time", SimpleNamespace(sleep=sleeps.append, monotonic=time.monotonic))

    lock_path = tmp_path / ".lark-cli.install.lock"
    entered = False
    with lark_cli._exclusive_install_lock(lock_path, threading.Lock()):
        entered = True

    assert entered
    assert fake.attempts == [fake.LK_NBLCK] * 4 + [fake.LK_UNLCK]
    assert fake.unlocked == 1
    assert sleeps == [0.2] * 3


def test_install_lock_posix_branch_still_flocks(tmp_path, monkeypatch) -> None:
    """The POSIX branch keeps using ``fcntl.flock`` unchanged."""

    class _FakeFcntl:
        LOCK_EX = 2
        LOCK_UN = 8

        def __init__(self) -> None:
            self.ops: list[int] = []

        def flock(self, fd: int, operation: int) -> None:
            self.ops.append(operation)

    fake_fcntl = _FakeFcntl()
    monkeypatch.setattr(lark_cli, "fcntl", fake_fcntl)

    lock_path = tmp_path / ".sandbox-cli.install.lock"
    entered = False
    with lark_cli._exclusive_install_lock(lock_path, threading.Lock()):
        entered = True

    assert entered
    assert fake_fcntl.ops == [_FakeFcntl.LOCK_EX, _FakeFcntl.LOCK_UN]


@pytest.mark.skipif(lark_cli.fcntl is not None, reason="exercises the real msvcrt fallback branch")
def test_install_lock_waits_for_real_windows_contention(tmp_path) -> None:
    """A real second contender acquires the lock once the holder releases.

    The holder keeps the region past ``LK_LOCK``'s ~10s give-up window: a
    blocking-mode contender dies with ``Permission denied`` there, while a
    retrying contender acquires as soon as the holder lets go.
    """
    import msvcrt

    lock_path = tmp_path / ".lark-cli.install.lock"
    lock_path.write_bytes(b"\0")

    holder = lock_path.open("a+b")
    holder.seek(0)
    msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)

    acquired = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def contender() -> None:
        try:
            with lark_cli._exclusive_install_lock(lock_path, threading.Lock()):
                acquired.set()
                release.wait(timeout=30)
        except BaseException as exc:  # surfaced via the assertion below
            errors.append(exc)

    thread = threading.Thread(target=contender, daemon=True)
    thread.start()
    try:
        # Keep the region locked past LK_LOCK's ~10s give-up window before
        # releasing it: a blocking-mode contender dies there, a retrying one
        # acquires as soon as the holder lets go.
        time.sleep(12)
        holder.seek(0)
        msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        holder.close()
        assert acquired.wait(timeout=5), f"contender failed to acquire the contended lock; errors={errors!r}"
    finally:
        release.set()
        thread.join(timeout=10)

    assert not errors


@pytest.mark.parametrize("error_number", [errno.EBADF, errno.EINVAL, errno.EIO, errno.EPERM])
def test_install_lock_propagates_non_contention_errors(tmp_path, monkeypatch, error_number):
    fake = _ContendedFakeMsvcrt(fail_times=1, error_number=error_number)
    monkeypatch.setattr(lark_cli, "fcntl", None)
    monkeypatch.setattr(lark_cli, "msvcrt", fake, raising=False)

    def unexpected_sleep(_delay):
        raise AssertionError("Permanent lock errors must not be retried")

    monkeypatch.setattr(lark_cli, "time", SimpleNamespace(sleep=unexpected_sleep, monotonic=lambda: 0.0))
    thread_lock = threading.Lock()
    with pytest.raises(OSError) as caught:
        with lark_cli._exclusive_install_lock(tmp_path / ".lock", thread_lock):
            pytest.fail("Must not enter after a failed acquisition")

    assert caught.value.errno == error_number
    assert fake.attempts == [fake.LK_NBLCK]
    assert fake.unlocked == 0
    assert not thread_lock.locked()


def test_install_lock_contention_has_a_deadline(tmp_path, monkeypatch):
    fake = _ContendedFakeMsvcrt(fail_times=100)
    monkeypatch.setattr(lark_cli, "fcntl", None)
    monkeypatch.setattr(lark_cli, "msvcrt", fake, raising=False)
    monkeypatch.setattr(lark_cli, "_INSTALL_LOCK_TIMEOUT_SECONDS", 0.5, raising=False)
    now = 0.0
    sleeps = []

    def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay
        assert now <= 1, "Lock acquisition must not retry forever"

    monkeypatch.setattr(lark_cli, "time", SimpleNamespace(sleep=sleep, monotonic=lambda: now))
    thread_lock = threading.Lock()
    with pytest.raises(TimeoutError, match="Lark install lock timed out"):
        with lark_cli._exclusive_install_lock(tmp_path / ".lock", thread_lock):
            pytest.fail("Must not enter while the lock is held")

    assert sleeps == pytest.approx([0.2, 0.2, 0.1])
    assert fake.attempts == [fake.LK_NBLCK] * 4
    assert fake.unlocked == 0
    assert not thread_lock.locked()
