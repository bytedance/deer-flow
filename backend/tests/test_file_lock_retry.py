"""Portable contention/error/deadline semantics for advisory lock retries."""

import asyncio
import errno
from types import SimpleNamespace

import pytest

from deerflow.utils.file_lock import retry_until_locked


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EAGAIN, errno.EDEADLK])
def test_contention_retries_until_acquisition_succeeds(error_number):
    attempts = 0
    sleeps = []

    def acquire():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError(error_number, "Contended")

    retry_until_locked(acquire, sleep=sleeps.append)

    assert attempts == 3
    assert sleeps == [0.2, 0.2]


@pytest.mark.parametrize("error_number", [errno.EBADF, errno.EINVAL, errno.EIO, errno.EPERM, None])
def test_permanent_error_is_propagated_without_retry(error_number):
    error = OSError(error_number, "Permanent error")
    sleeps = []

    def acquire():
        raise error

    with pytest.raises(OSError) as caught:
        retry_until_locked(acquire, sleep=sleeps.append)

    assert caught.value is error
    assert sleeps == []


def test_deadline_caps_the_final_sleep_and_reports_timeout():
    now = 10.0
    sleeps = []

    def acquire():
        raise OSError(errno.EAGAIN, "Contended")

    def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    with pytest.raises(TimeoutError, match="test deadline"):
        retry_until_locked(acquire, deadline=10.45, sleep=sleep, monotonic=lambda: now, timeout_message="test deadline")

    assert sleeps == pytest.approx([0.2, 0.2, 0.05])
    assert now == pytest.approx(10.45)


def test_check_can_cancel_between_contended_attempts():
    attempts = 0
    checks = 0
    sleeps = []

    def check():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise asyncio.CancelledError

    def acquire():
        nonlocal attempts
        attempts += 1
        raise OSError(errno.EAGAIN, "Contended")

    with pytest.raises(asyncio.CancelledError):
        retry_until_locked(acquire, check=check, sleep=sleeps.append)

    assert attempts == 1
    assert sleeps == [0.2]


def test_check_errors_are_not_treated_as_lock_contention():
    error = OSError(errno.EACCES, "Denied by check")
    attempts = []
    sleeps = []

    def check():
        raise error

    with pytest.raises(OSError) as caught:
        retry_until_locked(lambda: attempts.append(True), check=check, sleep=sleeps.append)

    assert caught.value is error
    assert attempts == sleeps == []


@pytest.mark.parametrize("winerror", [5, 32])
def test_replace_with_retry_retries_windows_sharing_errors(monkeypatch, winerror):
    from deerflow.utils import file_lock

    attempts = []
    sleeps = []

    def replace(_source, _target):
        attempts.append(True)
        if len(attempts) < 3:
            error = PermissionError(13, "busy")
            error.winerror = winerror
            raise error

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="nt", replace=replace))
    file_lock.replace_with_retry("source", "target", sleep=sleeps.append)

    assert len(attempts) == 3
    assert sleeps == [0.05, 0.05]


def test_replace_with_retry_does_not_treat_fake_winerror_as_sharing_error_on_posix(monkeypatch):
    from deerflow.utils import file_lock

    error = PermissionError(13, "posix permission denied")
    error.winerror = 5
    calls = []

    def replace(_source, _target):
        calls.append(True)
        raise error

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="posix", replace=replace))

    with pytest.raises(PermissionError) as caught:
        file_lock.replace_with_retry("source", "target")

    assert caught.value is error
    assert calls == [True]


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_replace_with_retry_does_not_retry_after_deadline(monkeypatch, platform):
    from deerflow.utils import file_lock

    error = PermissionError(13, "access denied")
    error.winerror = 5
    calls = []

    def replace(_source, _target):
        calls.append(True)
        raise error

    sleeps = []
    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name=platform, replace=replace))

    with pytest.raises(PermissionError) as caught:
        file_lock.replace_with_retry("source", "target", deadline_seconds=0, sleep=sleeps.append)

    assert caught.value is error
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("winerror", [None, 2, 3, 87])
def test_replace_with_retry_does_not_retry_other_windows_errors(monkeypatch, winerror):
    from deerflow.utils import file_lock

    error = PermissionError(errno.EACCES, "permanent")
    if winerror is not None:
        error.winerror = winerror
    calls = []
    sleeps = []

    def replace(source, target):
        calls.append((source, target))
        raise error

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="nt", replace=replace))

    with pytest.raises(PermissionError) as caught:
        file_lock.replace_with_retry("source", "target", sleep=sleeps.append)

    assert caught.value is error
    assert calls == [("source", "target")]
    assert sleeps == []


@pytest.mark.parametrize("winerror", [5, 32])
def test_replace_with_retry_caps_deadline_and_preserves_original_error(monkeypatch, winerror):
    from deerflow.utils import file_lock

    now = 0.0
    sleeps = []
    calls = []
    error = PermissionError(errno.EACCES, "still held")
    error.winerror = winerror

    def replace(source, target):
        calls.append((source, target))
        raise error

    def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr(file_lock, "os", SimpleNamespace(name="nt", replace=replace))

    with pytest.raises(PermissionError) as caught:
        file_lock.replace_with_retry("source", "target", deadline_seconds=0.12, sleep=sleep, monotonic=lambda: now)

    assert caught.value is error
    assert sleeps == pytest.approx([0.05, 0.05, 0.02])
    assert calls == [("source", "target")] * 4
    assert now == pytest.approx(0.12)
