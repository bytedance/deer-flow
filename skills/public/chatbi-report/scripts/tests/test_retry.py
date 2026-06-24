"""Unit tests for scripts/retry.py."""
import pytest

from retry import Backoff, exponential, retry


def test_retry_returns_value_when_no_failure():
    """First-attempt success: returns immediately, no extra calls."""

    calls = []

    @retry(max_attempts=3, backoff=exponential(base=2, max_delay=10),
           retry_on=(RuntimeError,))
    def fn() -> str:
        calls.append(1)
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 1


def test_retry_recovers_on_second_attempt(monkeypatch):
    """Fails once, succeeds on retry."""

    calls = []

    class FlakyError(RuntimeError):
        pass

    @retry(max_attempts=3, backoff=exponential(base=1, max_delay=1),
           retry_on=(FlakyError,))
    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise FlakyError("boom")
        return "ok"

    # Avoid actual sleeping: monkeypatch time.sleep to a no-op
    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    assert fn() == "ok"
    assert len(calls) == 2


def test_retry_raises_after_max_attempts(monkeypatch):
    """Always fails: re-raises the last exception after max_attempts."""

    calls = []

    class FlakyError(RuntimeError):
        pass

    @retry(max_attempts=3, backoff=exponential(base=1, max_delay=1),
           retry_on=(FlakyError,))
    def fn() -> str:
        calls.append(1)
        raise FlakyError(f"attempt {len(calls)}")

    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    with pytest.raises(FlakyError, match="attempt 3"):
        fn()
    assert len(calls) == 3


def test_retry_does_not_catch_unlisted_exception(monkeypatch):
    """Only `retry_on` exceptions are retried."""

    calls = []

    class ShouldRetry(RuntimeError):
        pass

    class ShouldNotRetry(ValueError):
        pass

    @retry(max_attempts=5, backoff=exponential(base=1, max_delay=1),
           retry_on=(ShouldRetry,))
    def fn() -> str:
        calls.append(1)
        raise ShouldNotRetry("nope")

    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    with pytest.raises(ShouldNotRetry, match="nope"):
        fn()
    assert len(calls) == 1


def test_exponential_backoff_grows_and_caps():
    """First three delays: base, base*2, min(base*4, max_delay)."""
    b = exponential(base=2, max_delay=10)
    assert b.delay(1) == 2     # 2 * 2^0 = 2
    assert b.delay(2) == 4     # 2 * 2^1 = 4
    assert b.delay(3) == 8     # 2 * 2^2 = 8
    assert b.delay(4) == 10    # 2 * 2^3 = 16 -> capped to 10
    assert b.delay(10) == 10   # already capped
