"""Login-throttle store contract: the in-process counter and the shared SQL table.

Both stores must implement the semantics the auth router relied on while the
counter was a module-level dict: a lock starts when the failure count reaches
``max_attempts``; the duration committed at lock time is honored even when the
policy shrinks mid-lock; an active lock follows the live duration (decreases
included); a served sentence is never resurrected by a later raise; a
successful login resets the IP; and the memory store bounds its tracked-IP
set. The SQL store additionally shares that state across every Gateway
replica using one database, which is the whole point of the change (and the
red-on-main reproduction here: two SQL stores over one SQLite file agree on
the lock, two memory stores do not).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.login_throttle import (
    MAX_TRACKED_IPS,
    STALE_COUNTER_SECONDS,
    LoginThrottleRecord,
    LoginThrottleRow,
    LoginThrottleStore,
    MemoryLoginThrottleStore,
    SqlLoginThrottleStore,
)

pytestmark = pytest.mark.asyncio

T0 = 1_700_000_000.0


async def _sqlite_engine(path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[LoginThrottleRow.__table__], checkfirst=True)
    return engine


def _sql_store(engine: AsyncEngine) -> SqlLoginThrottleStore:
    return SqlLoginThrottleStore(async_sessionmaker(engine, expire_on_commit=False))


@pytest_asyncio.fixture(params=["memory", "sql"])
async def store(request, tmp_path) -> AsyncIterator[LoginThrottleStore]:
    if request.param == "memory":
        yield MemoryLoginThrottleStore()
        return
    engine = await _sqlite_engine(tmp_path / "throttle.db")
    try:
        yield _sql_store(engine)
    finally:
        await engine.dispose()


async def _lock(store: LoginThrottleStore, ip: str, *, max_attempts: int = 2, lockout_seconds: float = 60.0, now: float = T0) -> LoginThrottleRecord:
    record = None
    for _ in range(max_attempts):
        record = await store.record_failure(ip, max_attempts=max_attempts, lockout_seconds=lockout_seconds, now=now)
    assert record is not None
    return record


# ── shared contract ─────────────────────────────────────────────────────────


async def test_clean_ip_has_no_record_and_is_allowed(store):
    assert await store.get("192.0.2.1") is None
    assert await store.check("192.0.2.1", max_attempts=5, lockout_seconds=300.0, now=T0) == 0.0


async def test_lock_starts_when_failures_reach_max_attempts(store):
    ip = "10.0.0.1"
    for n in range(1, 5):
        record = await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + n)
        assert record == LoginThrottleRecord(fail_count=n, locked_at=0.0, lock_duration=0.0)
        assert await store.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + n) == 0.0
    record = await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 5)
    assert record == LoginThrottleRecord(fail_count=5, locked_at=T0 + 5, lock_duration=300.0)
    assert await store.get(ip) == record
    assert await store.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 6) == pytest.approx(299.0)


async def test_reset_clears_the_counter(store):
    ip = "10.0.0.2"
    for _ in range(4):
        await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
    await store.reset(ip)
    assert await store.get(ip) is None
    assert await store.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0) == 0.0
    # Resetting an unknown IP is a no-op.
    await store.reset("203.0.113.77")


async def test_expired_lock_is_cleared_on_check(store):
    ip = "10.0.0.3"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 59.0) > 0.0
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 61.0) == 0.0
    assert await store.get(ip) is None


async def test_raised_threshold_unblocks_and_keeps_the_count(store):
    """Raising max_login_attempts mid-lock immediately unblocks a lower count (#5108)."""
    ip = "10.0.0.4"
    await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 1) > 0.0
    assert await store.check(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 1) == 0.0
    assert (await store.get(ip)).fail_count == 2


async def test_tightened_threshold_preserves_failures_and_locks_on_next(store):
    ip = "10.0.0.5"
    for _ in range(4):
        await store.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0)
    # Over the new threshold but never locked under it: allowed once, count kept.
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 1) == 0.0
    assert (await store.get(ip)).fail_count == 4
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2)
    assert record == LoginThrottleRecord(fail_count=5, locked_at=T0 + 2, lock_duration=60.0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 3) > 0.0
    await store.reset(ip)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 3) == 0.0


async def test_lowered_duration_releases_an_active_lock_early(store):
    ip = "10.0.0.6"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2) > 0.0
    assert await store.check(ip, max_attempts=2, lockout_seconds=1.0, now=T0 + 2) == 0.0
    assert await store.get(ip) is None


async def test_raised_duration_extends_an_active_lock(store):
    ip = "10.0.0.7"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 0.5) == pytest.approx(59.5)
    # The raise was committed while the lock was active, so it outlives the original 1s.
    assert (await store.get(ip)).lock_duration == 60.0
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2.0) == pytest.approx(58.0)


async def test_served_sentence_is_not_resurrected_by_a_later_raise(store):
    ip = "10.0.0.8"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    # No check happened while the 1s sentence ran; raising afterwards must not revive it.
    assert await store.check(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2.0) == 0.0
    assert await store.get(ip) is None


async def test_lowered_then_raised_duration_is_not_resurrected(store):
    ip = "10.0.0.9"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, max_attempts=2, lockout_seconds=10.0, now=T0 + 6.0) == pytest.approx(4.0)
    assert (await store.get(ip)).lock_duration == 10.0
    assert await store.check(ip, max_attempts=2, lockout_seconds=30.0, now=T0 + 20.0) == 0.0
    assert await store.get(ip) is None


async def test_concurrent_failures_do_not_lose_increments(store):
    """The upsert must be atomic: N racing failures count N, never fewer."""
    ip = "10.0.0.10"
    await asyncio.gather(*[store.record_failure(ip, max_attempts=100, lockout_seconds=60.0, now=T0 + i) for i in range(25)])
    assert (await store.get(ip)).fail_count == 25


async def test_concurrent_checks_of_an_expired_lock_all_resolve_cleanly(store):
    ip = "10.0.0.11"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    results = await asyncio.gather(*[store.check(ip, max_attempts=2, lockout_seconds=1.0, now=T0 + 5.0) for _ in range(8)], return_exceptions=True)
    assert results == [0.0] * 8, results
    assert await store.get(ip) is None


async def test_now_defaults_to_the_wall_clock(store):
    ip = "10.0.0.12"
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0)
    assert record.fail_count == 1 and record.locked_at == 0.0
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0)
    assert record.locked_at > T0  # a real timestamp, after this test was written
    assert 0.0 < await store.check(ip, max_attempts=2, lockout_seconds=60.0) <= 60.0


# ── memory store specifics ──────────────────────────────────────────────────


async def test_memory_eviction_expires_by_stored_sentence_not_current_threshold():
    """The capacity sweep expires records by their own committed sentence.

    A record locked under an old, lower threshold has a count below the live
    max; gating expiry on ``count >= max`` would keep that served record
    resident while the capacity fallback evicts live counters first (they sort
    earliest), handing an active offender a fresh budget.
    """
    store = MemoryLoginThrottleStore(max_tracked_ips=2)
    # Seed the lock first: the capacity sweep runs inside record_failure once
    # the set is full, and this test wants the sweep to run on the fresh IP.
    await _lock(store, "expired-lock", max_attempts=2, lockout_seconds=1.0, now=10.0)  # served at 11.0
    await store.record_failure("live-counter", max_attempts=3, lockout_seconds=60.0, now=90.0)

    await store.record_failure("fresh-ip", max_attempts=3, lockout_seconds=60.0, now=100.0)  # hits the sweep

    assert await store.get("expired-lock") is None
    assert await store.get("live-counter") == LoginThrottleRecord(fail_count=1, locked_at=0.0, lock_duration=0.0)
    assert (await store.get("fresh-ip")).fail_count == 1


async def test_memory_eviction_drops_the_cheapest_half_when_nothing_expired():
    store = MemoryLoginThrottleStore(max_tracked_ips=4)
    await _lock(store, "lock-early", lockout_seconds=60.0, now=T0)
    await _lock(store, "lock-late", lockout_seconds=600.0, now=T0)
    await store.record_failure("counter-a", max_attempts=5, lockout_seconds=60.0, now=T0)
    await store.record_failure("counter-b", max_attempts=5, lockout_seconds=60.0, now=T0)

    await store.record_failure("fresh-ip", max_attempts=5, lockout_seconds=60.0, now=T0 + 1)

    # Never-locked counters sort first (expiry key 0.0) and go; locks survive.
    assert await store.get("counter-a") is None
    assert await store.get("counter-b") is None
    assert (await store.get("lock-early")).locked_at == T0
    assert (await store.get("lock-late")).locked_at == T0
    assert (await store.get("fresh-ip")).fail_count == 1


async def test_memory_store_default_capacity_matches_the_historical_constant():
    assert MAX_TRACKED_IPS == 10000
    assert MemoryLoginThrottleStore()._max_tracked_ips == MAX_TRACKED_IPS


# ── SQL store specifics ─────────────────────────────────────────────────────


async def test_sql_record_failure_sweeps_expired_locks_and_stale_counters(tmp_path):
    engine = await _sqlite_engine(tmp_path / "sweep.db")
    try:
        store = _sql_store(engine)
        await _lock(store, "expired-lock", lockout_seconds=1.0, now=T0)  # served at T0 + 1
        await store.record_failure("stale-counter", max_attempts=5, lockout_seconds=60.0, now=T0 - STALE_COUNTER_SECONDS - 1)
        await store.record_failure("live-counter", max_attempts=5, lockout_seconds=60.0, now=T0)
        await _lock(store, "live-lock", lockout_seconds=600.0, now=T0)

        await store.record_failure("fresh-ip", max_attempts=5, lockout_seconds=60.0, now=T0 + 5)

        async with engine.connect() as conn:
            ips = set((await conn.execute(sa.select(LoginThrottleRow.ip))).scalars())
        assert ips == {"live-counter", "live-lock", "fresh-ip"}
    finally:
        await engine.dispose()


async def test_sql_stores_truncate_overlong_keys_consistently(tmp_path):
    """A trusted proxy can forward an arbitrarily long X-Real-IP; the row key is bounded."""
    engine = await _sqlite_engine(tmp_path / "long.db")
    try:
        store = _sql_store(engine)
        key = "x" * 400
        await _lock(store, key, lockout_seconds=60.0, now=T0)
        assert await store.check(key, max_attempts=2, lockout_seconds=60.0, now=T0 + 1) > 0.0
        async with engine.connect() as conn:
            stored = (await conn.execute(sa.select(LoginThrottleRow.ip))).scalar_one()
        assert len(stored) == LoginThrottleRow.ip.type.length
        await store.reset(key)
        assert await store.get(key) is None
    finally:
        await engine.dispose()


async def test_two_sql_stores_over_one_database_share_the_lock(tmp_path):
    """Multi-replica reproduction: replica B sees the failures replica A counted.

    Two engines over one SQLite file stand in for two Gateway Pods sharing one
    database. Before this change each Pod kept its own counter, so an attacker
    behind a load balancer got N x max_login_attempts guesses and a lockout on
    one Pod was invisible to the others.
    """
    path = tmp_path / "shared.db"
    engine_a = await _sqlite_engine(path)
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        replica_a, replica_b = _sql_store(engine_a), _sql_store(engine_b)
        ip = "198.51.100.7"
        for _ in range(3):
            await replica_a.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
        for _ in range(2):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 1)
        assert (await replica_a.get(ip)).fail_count == 5
        assert await replica_a.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 2) > 0.0
        assert await replica_b.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 2) > 0.0
        # A successful login on one replica releases the IP everywhere.
        await replica_b.reset(ip)
        assert await replica_a.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 3) == 0.0
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_two_memory_stores_do_not_share_the_lock():
    """Documents the per-process behavior the SQL store exists to replace."""
    replica_a, replica_b = MemoryLoginThrottleStore(), MemoryLoginThrottleStore()
    ip = "198.51.100.8"
    for _ in range(5):
        await replica_a.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
    assert await replica_a.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 1) > 0.0
    assert await replica_b.check(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 1) == 0.0
    assert await replica_b.get(ip) is None
