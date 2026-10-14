"""Behavior tests for the cross-process file lock in the runtime config store.

Windows' blocking lock mode (``msvcrt.LK_LOCK``) gives up after roughly ten
seconds and surfaces contention as ``Permission denied``, while the whole
point of the sidecar lock is to serialize concurrent Gateway workers'
read-modify-write cycles of one store file. The Windows fallback must retry
the non-blocking acquisition until the region frees, mirroring the extensions
manager's lock.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from app.channels import runtime_config_store
from app.channels.runtime_config_store import ChannelRuntimeConfigStore, _runtime_config_file_lock

TELEGRAM = {"enabled": True, "bot_token": "tg-token"}


class _ContendedFakeMsvcrt:
    """Fake ``msvcrt`` whose lock region stays busy for the first N attempts.

    Records every ``locking`` call so tests can assert the retry cadence and
    the final unlock, independently of the real Windows semantics.
    """

    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts: list[int] = []
        self.unlocked = 0

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.attempts.append(mode)
        if mode == self.LK_UNLCK:
            self.unlocked += 1
            return None
        blocking_attempts = len(self.attempts) - self.unlocked
        if blocking_attempts <= self.fail_times:
            raise OSError(36, "Resource deadlock avoided")
        return None


class _BlockingModeFakeMsvcrt:
    """Fake ``msvcrt`` that fails only the blocking ``LK_LOCK`` mode.

    Models a region contended past the blocking mode's patience: the
    unpatched module calls ``LK_LOCK`` once and fails, while a retry loop
    succeeds on its first non-blocking attempt.
    """

    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self) -> None:
        self.attempts: list[int] = []
        self.unlocked = 0

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.attempts.append(mode)
        if mode == self.LK_UNLCK:
            self.unlocked += 1
            return None
        if mode == self.LK_LOCK:
            raise OSError(36, "Resource deadlock avoided")
        return None


def test_file_lock_retries_until_contention_clears(tmp_path, monkeypatch) -> None:
    """Contention is retried on the Windows fallback instead of failing."""
    fake = _ContendedFakeMsvcrt(fail_times=3)
    monkeypatch.setattr(runtime_config_store, "fcntl", None, raising=False)
    monkeypatch.setattr(runtime_config_store, "msvcrt", fake, raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    entered = False
    with _runtime_config_file_lock(tmp_path / "runtime-config.json"):
        entered = True

    assert entered
    assert fake.attempts == [fake.LK_NBLCK] * 4 + [fake.LK_UNLCK]
    assert fake.unlocked == 1
    assert sleeps == [0.2] * 3


def test_file_lock_creates_the_sidecar_byte_on_the_windows_fallback(tmp_path, monkeypatch) -> None:
    """The empty sidecar file still gets its lockable byte before locking."""
    fake = _ContendedFakeMsvcrt(fail_times=0)
    monkeypatch.setattr(runtime_config_store, "fcntl", None, raising=False)
    monkeypatch.setattr(runtime_config_store, "msvcrt", fake, raising=False)

    with _runtime_config_file_lock(tmp_path / "runtime-config.json"):
        pass

    assert (tmp_path / ".runtime-config.json.lock").read_bytes() == b"\0"


def test_file_lock_posix_branch_still_flocks(tmp_path, monkeypatch) -> None:
    """The POSIX branch keeps using ``fcntl.flock`` unchanged."""

    class _FakeFcntl:
        LOCK_EX = 2
        LOCK_UN = 8

        def __init__(self) -> None:
            self.ops: list[tuple[int, int]] = []

        def flock(self, fd: int, operation: int) -> None:
            self.ops.append((fd, operation))

    fake_fcntl = _FakeFcntl()
    monkeypatch.setattr(runtime_config_store, "fcntl", fake_fcntl, raising=False)

    entered = False
    with _runtime_config_file_lock(tmp_path / "runtime-config.json"):
        entered = True

    assert entered
    assert [operation for _, operation in fake_fcntl.ops] == [_FakeFcntl.LOCK_EX, _FakeFcntl.LOCK_UN]


@pytest.mark.skipif(os.name != "nt", reason="exercises the Windows import path directly")
def test_windows_fallback_survives_contention_the_blocking_mode_cannot(tmp_path, monkeypatch) -> None:
    """Direct regression: the fallback retries contention instead of failing.

    ``sys.modules`` catches the function-local ``import msvcrt`` the unpatched
    module performs; the module attribute covers the fixed module's global
    binding, so this test demonstrates the base failure mode (one ``LK_LOCK``
    call raising ``OSError``) and the fixed retry behavior on either structure.
    """
    fake = _BlockingModeFakeMsvcrt()
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(runtime_config_store, "msvcrt", fake, raising=False)

    with _runtime_config_file_lock(tmp_path / "runtime-config.json"):
        pass

    assert fake.attempts == [fake.LK_NBLCK, fake.LK_UNLCK]
    assert fake.unlocked == 1


def test_save_serializes_with_a_peer_holding_the_real_lock(tmp_path) -> None:
    """A real peer holding the sidecar lock delays the save instead of failing it.

    The advisory file lock is per open file, so two lock contexts on one path
    exclude each other inside this process, as the peer tests for #6844 note.
    """
    store_path = tmp_path / "channels" / "runtime-config.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    holder_ready = threading.Event()

    def hold():
        with _runtime_config_file_lock(store_path):
            holder_ready.set()
            time.sleep(0.6)

    holder = threading.Thread(target=hold)
    holder.start()
    assert holder_ready.wait(timeout=5)

    ChannelRuntimeConfigStore(store_path).set_provider_config("telegram", TELEGRAM)

    holder.join(timeout=5)
    assert ChannelRuntimeConfigStore(store_path).get_provider_config("telegram") == TELEGRAM
