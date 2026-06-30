"""Unit tests for ai-report retry decorator (新写, 借鉴 chatbi-report retry.py 行为契约)."""

from __future__ import annotations

import pytest

from retry import Backoff, exponential, retry


def test_retry_succeeds_on_first_attempt():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        return 42

    assert fn() == 42
    assert len(calls) == 1


def test_retry_succeeds_on_third_attempt():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 3


def test_retry_raises_after_max_attempts():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        raise ValueError("always fail")

    with pytest.raises(ValueError, match="always fail"):
        fn()
    assert len(calls) == 3


def test_retry_does_not_catch_other_exceptions():
    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        raise TypeError("not retried")

    with pytest.raises(TypeError, match="not retried"):
        fn()


def test_exponential_backoff_caps_at_max_delay():
    backoff = exponential(base=1.0, max_delay=4.0)
    assert backoff.delay(1) == 1.0
    assert backoff.delay(2) == 2.0
    assert backoff.delay(3) == 4.0
    assert backoff.delay(10) == 4.0