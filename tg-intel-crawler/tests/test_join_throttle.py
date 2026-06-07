"""Tests for JoinThrottle — rate-limit & dedup join_group calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_intel_crawler.collector.join_throttle import (
    DailyLimitExceeded,
    JoinThrottle,
    JoinThrottleResult,
)


@pytest.fixture
def now():
    """Mutable clock — bump it manually to fast-forward."""
    return SimpleNamespace(t=1_700_000_000.0)


@pytest.fixture
def throttle(now):
    sleeps: list[float] = []

    async def fake_sleep(s: float):
        sleeps.append(s)
        now.t += s

    t = JoinThrottle(
        min_interval=30,
        max_interval=90,
        daily_limit=5,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )
    t._sleeps = sleeps  # expose for assertions
    return t


@pytest.mark.asyncio
async def test_first_acquire_passes_immediately(throttle, now):
    start = now.t
    result = await throttle.acquire("groupa")
    assert result is JoinThrottleResult.OK
    # No sleep on the very first call (no prior call to space from).
    assert throttle._sleeps == []
    assert now.t == start


@pytest.mark.asyncio
async def test_second_acquire_sleeps_at_least_min_interval(throttle, now):
    await throttle.acquire("a")
    await throttle.acquire("b")
    # Must have slept somewhere in [min_interval, max_interval].
    assert any(30 <= s <= 90 for s in throttle._sleeps)


@pytest.mark.asyncio
async def test_already_joined_returns_skip_without_sleep(throttle, now):
    throttle.mark_joined("alreadyin")
    result = await throttle.acquire("alreadyin")
    assert result is JoinThrottleResult.ALREADY_JOINED
    assert throttle._sleeps == []


@pytest.mark.asyncio
async def test_daily_limit_blocks_after_n_acquires(throttle, now):
    # daily_limit = 5
    for i in range(5):
        await throttle.acquire(f"g{i}")
    with pytest.raises(DailyLimitExceeded):
        await throttle.acquire("g_overflow")


@pytest.mark.asyncio
async def test_already_joined_does_not_count_against_daily_limit(throttle, now):
    throttle.mark_joined("known")
    for _ in range(10):
        await throttle.acquire("known")  # never increments counter
    # Still able to do 5 real joins.
    for i in range(5):
        await throttle.acquire(f"new{i}")
    with pytest.raises(DailyLimitExceeded):
        await throttle.acquire("one_more")


@pytest.mark.asyncio
async def test_mark_joined_persists_across_acquires(throttle, now):
    await throttle.acquire("fresh")
    throttle.mark_joined("fresh")
    # Second call to the same username should short-circuit.
    result = await throttle.acquire("fresh")
    assert result is JoinThrottleResult.ALREADY_JOINED


@pytest.mark.asyncio
async def test_warmup_from_dialogs_marks_all_joined(throttle, now):
    # Simulate iter_dialogs cache being passed in.
    throttle.warmup(usernames={"warm1", "warm2"}, chat_ids={111})
    r1 = await throttle.acquire("warm1")
    r2 = await throttle.acquire("warm2")
    assert r1 is JoinThrottleResult.ALREADY_JOINED
    assert r2 is JoinThrottleResult.ALREADY_JOINED


@pytest.mark.asyncio
async def test_floodwait_retries_once_then_succeeds(throttle, now):
    """When join_with_throttle's join_callable raises FloodWaitError,
    JoinThrottle should sleep e.seconds and retry once."""

    class FakeFlood(Exception):
        def __init__(self, seconds): self.seconds = seconds

    join = AsyncMock(side_effect=[FakeFlood(45), "ok"])
    throttle._flood_exc_types = (FakeFlood,)  # injectable

    result = await throttle.run_join("retrygrp", join)
    assert result == "ok"
    assert join.await_count == 2
    # Should have slept 45s for the FloodWait.
    assert 45 in throttle._sleeps


@pytest.mark.asyncio
async def test_floodwait_second_failure_propagates(throttle, now):
    class FakeFlood(Exception):
        def __init__(self, seconds): self.seconds = seconds

    join = AsyncMock(side_effect=[FakeFlood(20), FakeFlood(30)])
    throttle._flood_exc_types = (FakeFlood,)

    with pytest.raises(FakeFlood):
        await throttle.run_join("dies", join)
    assert join.await_count == 2


@pytest.mark.asyncio
async def test_run_join_marks_joined_on_success(throttle, now):
    join = AsyncMock(return_value="ok")
    await throttle.run_join("newone", join)
    # Subsequent acquire should treat it as already joined.
    result = await throttle.acquire("newone")
    assert result is JoinThrottleResult.ALREADY_JOINED


@pytest.mark.asyncio
async def test_run_join_short_circuits_when_already_joined(throttle, now):
    join = AsyncMock()
    throttle.mark_joined("dup")
    result = await throttle.run_join("dup", join)
    assert result is None
    assert join.await_count == 0
