"""Tests for BotQueryThrottle — pace queries to a bot, cap per run."""

from types import SimpleNamespace

import pytest

from tg_intel_crawler.collector.bot_search_throttle import (
    BotQueryThrottle,
    BotQueryLimitExceeded,
)


@pytest.fixture
def now():
    return SimpleNamespace(t=10_000.0)


@pytest.fixture
def throttle(now):
    sleeps: list[float] = []

    async def fake_sleep(s: float):
        sleeps.append(s)
        now.t += s

    t = BotQueryThrottle(
        interval_seconds=10,
        max_queries_per_run=5,
        sleep_fn=fake_sleep,
        time_fn=lambda: now.t,
    )
    t._sleeps = sleeps
    return t


@pytest.mark.asyncio
async def test_first_query_passes_immediately(throttle, now):
    start = now.t
    await throttle.acquire()
    assert throttle._sleeps == []
    assert now.t == start


@pytest.mark.asyncio
async def test_second_query_waits_interval(throttle, now):
    await throttle.acquire()
    await throttle.acquire()
    assert any(abs(s - 10) < 0.001 for s in throttle._sleeps)


@pytest.mark.asyncio
async def test_run_cap_blocks_after_n_queries(throttle, now):
    for _ in range(5):
        await throttle.acquire()
    with pytest.raises(BotQueryLimitExceeded):
        await throttle.acquire()


@pytest.mark.asyncio
async def test_zero_interval_disables_spacing(now):
    t = BotQueryThrottle(
        interval_seconds=0,
        max_queries_per_run=10,
        sleep_fn=lambda s: _no_sleep(s, now),
        time_fn=lambda: now.t,
    )
    sleeps: list[float] = []
    async def fake_sleep(s):
        sleeps.append(s)
    t._sleep = fake_sleep
    await t.acquire()
    await t.acquire()
    assert sleeps == []  # no spacing when interval=0


async def _no_sleep(s, now):
    pass


@pytest.mark.asyncio
async def test_already_waited_long_enough_no_extra_sleep(throttle, now):
    """If natural wall-clock between two acquires already exceeded the
    interval, don't sleep again."""
    await throttle.acquire()
    now.t += 30  # simulate 30s of real work between calls
    throttle._sleeps.clear()
    await throttle.acquire()
    assert throttle._sleeps == []
