"""Portable contention/error/deadline semantics for advisory lock retries."""

import asyncio
import errno

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
