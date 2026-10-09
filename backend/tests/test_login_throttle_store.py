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
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

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
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

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


def _policy(max_attempts: int, lockout_seconds: float) -> Callable[[], Awaitable[tuple[int, float]]]:
    """A ``check`` policy callable for a known policy (the router wraps its config read the same way)."""

    async def resolve() -> tuple[int, float]:
        return max_attempts, lockout_seconds

    return resolve


class _CountingPolicy:
    """Policy callable that counts how often ``check`` resolved it."""

    def __init__(self, max_attempts: int, lockout_seconds: float) -> None:
        self.calls = 0
        self._policy = (max_attempts, lockout_seconds)

    async def __call__(self) -> tuple[int, float]:
        self.calls += 1
        return self._policy


async def _lock(store: LoginThrottleStore, ip: str, *, max_attempts: int = 2, lockout_seconds: float = 60.0, now: float = T0) -> LoginThrottleRecord:
    record = None
    for _ in range(max_attempts):
        record = await store.record_failure(ip, max_attempts=max_attempts, lockout_seconds=lockout_seconds, now=now)
    assert record is not None
    return record


# ── shared contract ─────────────────────────────────────────────────────────


async def test_clean_ip_has_no_record_and_is_allowed(store):
    assert await store.get("192.0.2.1") is None
    assert await store.check("192.0.2.1", policy=_policy(5, 300.0), now=T0) == 0.0


async def test_lock_starts_when_failures_reach_max_attempts(store):
    ip = "10.0.0.1"
    for n in range(1, 5):
        record = await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + n)
        assert record == LoginThrottleRecord(fail_count=n, locked_at=0.0, lock_duration=0.0)
        assert await store.check(ip, policy=_policy(5, 300.0), now=T0 + n) == 0.0
    record = await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 5)
    assert record == LoginThrottleRecord(fail_count=5, locked_at=T0 + 5, lock_duration=300.0)
    assert await store.get(ip) == record
    assert await store.check(ip, policy=_policy(5, 300.0), now=T0 + 6) == pytest.approx(299.0)


async def test_reset_clears_the_counter(store):
    ip = "10.0.0.2"
    for _ in range(4):
        await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
    await store.reset(ip)
    assert await store.get(ip) is None
    assert await store.check(ip, policy=_policy(5, 300.0), now=T0) == 0.0
    # Resetting an unknown IP is a no-op.
    await store.reset("203.0.113.77")


async def test_expired_lock_is_cleared_on_check(store):
    ip = "10.0.0.3"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 59.0) > 0.0
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 61.0) == 0.0
    assert await store.get(ip) is None


async def test_raised_threshold_unblocks_and_keeps_the_count(store):
    """Raising max_login_attempts mid-lock immediately unblocks a lower count (#5108)."""
    ip = "10.0.0.4"
    await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 1) > 0.0
    assert await store.check(ip, policy=_policy(5, 60.0), now=T0 + 1) == 0.0
    assert (await store.get(ip)).fail_count == 2


async def test_tightened_threshold_preserves_failures_and_locks_on_next(store):
    ip = "10.0.0.5"
    for _ in range(4):
        await store.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0)
    # Over the new threshold but never locked under it: allowed once, count kept.
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 1) == 0.0
    assert (await store.get(ip)).fail_count == 4
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2)
    assert record == LoginThrottleRecord(fail_count=5, locked_at=T0 + 2, lock_duration=60.0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 3) > 0.0
    await store.reset(ip)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 3) == 0.0


async def test_lowered_duration_releases_an_active_lock_early(store):
    ip = "10.0.0.6"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 2) > 0.0
    assert await store.check(ip, policy=_policy(2, 1.0), now=T0 + 2) == 0.0
    assert await store.get(ip) is None


async def test_raised_duration_extends_an_active_lock(store):
    ip = "10.0.0.7"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 0.5) == pytest.approx(59.5)
    # The raise was committed while the lock was active, so it outlives the original 1s.
    assert (await store.get(ip)).lock_duration == 60.0
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 2.0) == pytest.approx(58.0)


async def test_served_sentence_is_not_resurrected_by_a_later_raise(store):
    ip = "10.0.0.8"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    # No check happened while the 1s sentence ran; raising afterwards must not revive it.
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 2.0) == 0.0
    assert await store.get(ip) is None


async def test_lowered_then_raised_duration_is_not_resurrected(store):
    ip = "10.0.0.9"
    await _lock(store, ip, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 10.0), now=T0 + 6.0) == pytest.approx(4.0)
    assert (await store.get(ip)).lock_duration == 10.0
    assert await store.check(ip, policy=_policy(2, 30.0), now=T0 + 20.0) == 0.0
    assert await store.get(ip) is None


async def test_concurrent_failures_do_not_lose_increments(store):
    """The upsert must be atomic: N racing failures count N, never fewer."""
    ip = "10.0.0.10"
    await asyncio.gather(*[store.record_failure(ip, max_attempts=100, lockout_seconds=60.0, now=T0 + i) for i in range(25)])
    assert (await store.get(ip)).fail_count == 25


async def test_concurrent_checks_of_an_expired_lock_all_resolve_cleanly(store):
    ip = "10.0.0.11"
    await _lock(store, ip, lockout_seconds=1.0, now=T0)
    results = await asyncio.gather(*[store.check(ip, policy=_policy(2, 1.0), now=T0 + 5.0) for _ in range(8)], return_exceptions=True)
    assert results == [0.0] * 8, results
    assert await store.get(ip) is None


async def test_now_defaults_to_the_wall_clock(store):
    ip = "10.0.0.12"
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0)
    assert record.fail_count == 1 and record.locked_at == 0.0
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0)
    assert record.locked_at > T0  # a real timestamp, after this test was written
    assert 0.0 < await store.check(ip, policy=_policy(2, 60.0)) <= 60.0


async def test_failures_during_an_active_lock_do_not_slide_the_sentence(store):
    """A failure recorded while the lock is active keeps the lock's start and committed duration.

    Review of #6501: re-stamping ``locked_at = now`` on every failure turned
    "N seconds after the lock started" into "N seconds after the last
    attempt", so a sustained attacker never served the sentence.
    """
    ip = "10.0.0.20"
    locked = await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)
    assert locked == LoginThrottleRecord(fail_count=2, locked_at=T0, lock_duration=60.0)
    for n, offset in enumerate((10.0, 20.0, 50.0), start=3):
        record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + offset)
        assert record == LoginThrottleRecord(fail_count=n, locked_at=T0, lock_duration=60.0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 59.0) == pytest.approx(1.0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 61.0) == 0.0  # expires at the original time
    assert await store.get(ip) is None


async def test_failure_during_an_active_lock_keeps_the_committed_duration_not_the_live_one(store):
    """The duration a ``check`` committed (here a lowered one) is what a later failure preserves."""
    ip = "10.0.0.21"
    await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)
    assert await store.check(ip, policy=_policy(2, 10.0), now=T0 + 2.0) == pytest.approx(8.0)  # commits 10s
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=300.0, now=T0 + 5.0)
    assert record == LoginThrottleRecord(fail_count=3, locked_at=T0, lock_duration=10.0)


async def test_failure_after_a_served_lock_starts_a_fresh_sentence(store):
    """A lock whose sentence elapsed (no check cleared it yet) is restarted by the next failure."""
    ip = "10.0.0.22"
    await _lock(store, ip, max_attempts=2, lockout_seconds=1.0, now=T0)
    record = await store.record_failure(ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 5.0)
    assert record == LoginThrottleRecord(fail_count=3, locked_at=T0 + 5.0, lock_duration=60.0)
    assert await store.check(ip, policy=_policy(2, 60.0), now=T0 + 6.0) == pytest.approx(59.0)


async def test_raised_threshold_clears_the_lock_below_the_new_max_and_restarts_it_when_reached(store):
    """Raising max_login_attempts mid-lock: a failure below the new threshold leaves the IP counting;
    the failure that reaches the new threshold starts a fresh lock at that moment."""
    ip = "10.0.0.23"
    await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)  # (2, T0, 60)
    record = await store.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 1.0)
    assert record == LoginThrottleRecord(fail_count=3, locked_at=0.0, lock_duration=0.0)  # counting again under the raised max
    assert await store.check(ip, policy=_policy(5, 60.0), now=T0 + 1.5) == 0.0
    record = await store.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 2.0)
    assert record == LoginThrottleRecord(fail_count=4, locked_at=0.0, lock_duration=0.0)
    record = await store.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 3.0)
    assert record == LoginThrottleRecord(fail_count=5, locked_at=T0 + 3.0, lock_duration=60.0)  # fresh lock, not the stale T0
    assert await store.check(ip, policy=_policy(5, 60.0), now=T0 + 4.0) == pytest.approx(59.0)


async def test_check_never_resolves_the_policy_for_a_clean_ip(store):
    """The clean-IP skip survives the lazy policy: no record, no config read."""
    policy = _CountingPolicy(5, 300.0)
    assert await store.check("192.0.2.200", policy=policy, now=T0) == 0.0
    assert policy.calls == 0


async def test_check_resolves_the_policy_exactly_once_for_a_recorded_ip(store):
    ip = "10.0.0.30"
    await store.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
    policy = _CountingPolicy(5, 300.0)
    assert await store.check(ip, policy=policy, now=T0 + 1) == 0.0
    assert policy.calls == 1
    await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0 + 2)
    policy = _CountingPolicy(2, 60.0)
    assert await store.check(ip, policy=policy, now=T0 + 3) > 0.0
    assert policy.calls == 1


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


class _CountingSession:
    """Session proxy counting ``commit()`` calls."""

    def __init__(self, inner, counters: dict) -> None:
        self._inner = inner
        self._counters = counters

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    async def commit(self) -> None:
        self._counters["commits"] += 1
        await self._inner.commit()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _counting_store(engine: AsyncEngine) -> tuple[SqlLoginThrottleStore, dict]:
    """A SQL store whose session factory counts sessions opened and commits issued."""
    real = async_sessionmaker(engine, expire_on_commit=False)
    counters = {"sessions": 0, "commits": 0}

    def factory():
        counters["sessions"] += 1
        return _CountingSession(real(), counters)

    return SqlLoginThrottleStore(factory), counters


async def test_sql_check_opens_exactly_one_session_per_call(tmp_path):
    """A recorded IP no longer costs two pool checkouts (probe + decision) on the unauthenticated login path."""
    engine = await _sqlite_engine(tmp_path / "sessions.db")
    try:
        store, counters = _counting_store(engine)
        ip = "10.0.0.31"
        assert await store.check(ip, policy=_policy(5, 300.0), now=T0) == 0.0  # clean IP
        assert counters["sessions"] == 1
        await _lock(store, ip, max_attempts=2, lockout_seconds=60.0, now=T0)
        counters["sessions"] = 0
        assert await store.check(ip, policy=_policy(2, 300.0), now=T0 + 1) > 0.0  # recorded IP, duration committed
        assert counters["sessions"] == 1
        counters["sessions"] = 0
        assert await store.check(ip, policy=_policy(2, 300.0), now=T0 + 2) > 0.0  # recorded IP, nothing to write
        assert counters["sessions"] == 1
    finally:
        await engine.dispose()


async def test_sql_record_failure_commits_one_transaction(tmp_path):
    """Housekeeping rides in the upsert's transaction: one commit per failed login, not two."""
    engine = await _sqlite_engine(tmp_path / "commits.db")
    try:
        store, counters = _counting_store(engine)
        await _lock(store, "other-served-lock", lockout_seconds=1.0, now=T0 - 10.0)
        counters["commits"] = 0
        await store.record_failure("10.0.0.32", max_attempts=5, lockout_seconds=300.0, now=T0)
        assert counters["commits"] == 1
        assert await store.get("other-served-lock") is None  # the sweep still ran, inside that transaction
    finally:
        await engine.dispose()


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


async def test_sql_sweep_leaves_the_row_being_recorded_to_the_upsert(tmp_path):
    """The sweep excludes the IP whose failure is being recorded, so the upsert applies the shared rule.

    A stale counter keeps counting (the memory store never expires counters on
    its own either) instead of collapsing into a fresh ``(1, NULL, NULL)``
    row, while other expired rows are still swept by the same call. The
    served-lock half of the rule is pinned for both stores by
    ``test_failure_after_a_served_lock_starts_a_fresh_sentence``.
    """
    engine = await _sqlite_engine(tmp_path / "keep.db")
    try:
        store = _sql_store(engine)
        stale_now = T0 - STALE_COUNTER_SECONDS - 1
        for _ in range(4):
            await store.record_failure("stale-counter", max_attempts=5, lockout_seconds=60.0, now=stale_now)
        await _lock(store, "other-served-lock", lockout_seconds=1.0, now=T0 - 10.0)

        record = await store.record_failure("stale-counter", max_attempts=5, lockout_seconds=60.0, now=T0)
        assert record == LoginThrottleRecord(fail_count=5, locked_at=T0, lock_duration=60.0)  # 4 + 1 reaches the threshold
        assert await store.get("other-served-lock") is None  # swept by that same call
    finally:
        await engine.dispose()


async def test_sql_stores_truncate_overlong_keys_consistently(tmp_path, caplog):
    """A trusted proxy can forward an arbitrarily long X-Real-IP; the row key is bounded and the truncation is logged."""
    import logging

    engine = await _sqlite_engine(tmp_path / "long.db")
    try:
        store = _sql_store(engine)
        key = "x" * 400
        with caplog.at_level(logging.WARNING):
            await _lock(store, key, lockout_seconds=60.0, now=T0)
        truncation_warnings = [r.message for r in caplog.records if "truncat" in r.message.lower()]
        assert truncation_warnings, caplog.records
        assert "400" in truncation_warnings[0] and str(LoginThrottleRow.ip.type.length) in truncation_warnings[0]
        assert key not in truncation_warnings[0]  # never log the (possibly token-like) key itself
        assert await store.check(key, policy=_policy(2, 60.0), now=T0 + 1) > 0.0
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
        assert await replica_a.check(ip, policy=_policy(5, 300.0), now=T0 + 2) > 0.0
        assert await replica_b.check(ip, policy=_policy(5, 300.0), now=T0 + 2) > 0.0
        # A successful login on one replica releases the IP everywhere.
        await replica_b.reset(ip)
        assert await replica_a.check(ip, policy=_policy(5, 300.0), now=T0 + 3) == 0.0
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_failure_committing_after_a_reset_counts_as_a_fresh_first_failure(tmp_path):
    """A reset and a peer's failure serialize at the database; whichever commits last defines the state.

    A failure that commits after the successful login's reset leaves
    ``fail_count = 1`` — one genuine failed attempt after the history was
    cleared, not a resurrected counter or lock. (A failure that commits
    before the reset is cleared by it.) The memory store has the same ordering
    semantics; "a successful login clears the IP everywhere" holds either way.
    """
    path = tmp_path / "reset-race.db"
    engine_a = await _sqlite_engine(path)
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        replica_a, replica_b = _sql_store(engine_a), _sql_store(engine_b)
        ip = "198.51.100.9"
        await _lock(replica_a, ip, max_attempts=5, lockout_seconds=300.0, now=T0)
        await replica_a.reset(ip)  # successful login on replica A
        record = await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0 + 1.0)  # peer's wrong password lands after
        assert record == LoginThrottleRecord(fail_count=1, locked_at=0.0, lock_duration=0.0)
        assert await replica_a.get(ip) == record
        assert await replica_a.check(ip, policy=_policy(5, 300.0), now=T0 + 2.0) == 0.0
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_two_memory_stores_do_not_share_the_lock():
    """Documents the per-process behavior the SQL store exists to replace."""
    replica_a, replica_b = MemoryLoginThrottleStore(), MemoryLoginThrottleStore()
    ip = "198.51.100.8"
    for _ in range(5):
        await replica_a.record_failure(ip, max_attempts=5, lockout_seconds=300.0, now=T0)
    assert await replica_a.check(ip, policy=_policy(5, 300.0), now=T0 + 1) > 0.0
    assert await replica_b.check(ip, policy=_policy(5, 300.0), now=T0 + 1) == 0.0
    assert await replica_b.get(ip) is None


# ── sweep versus a concurrent lock extension ─────────────────────────────────


def _outer_where_without_candidate_subquery(sql: str) -> str:
    """The DELETE's own WHERE clause with the ``IN (SELECT ...)`` candidate subquery replaced by ``(...)``."""
    outer = sql[sql.index("WHERE") :]
    start = outer.index("IN (") + len("IN ")
    depth, end = 0, start
    for end in range(start, len(outer)):
        depth += {"(": 1, ")": -1}.get(outer[end], 0)
        if depth == 0:
            break
    return outer[:start] + "(...)" + outer[end + 1 :]


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["postgresql", "sqlite"])
async def test_sweep_delete_repeats_the_expiry_predicate_on_the_deleted_row(dialect):
    """The sweep's DELETE must re-check expiry on the row it deletes, not only IP membership.

    PostgreSQL READ COMMITTED re-evaluates only the DELETE's *own* WHERE on a
    row it had to wait for; the ``IN (SELECT ... LIMIT n)`` candidate subquery is
    bound to the statement snapshot. With ``ip IN (...)`` alone, a lock that a
    concurrent ``check`` extended between the snapshot and the row lock would
    still be deleted (review of #6501). Compiling the statement pins the guard
    without a live PostgreSQL.
    """
    sql = str(SqlLoginThrottleStore.sweep_statement(T0).compile(dialect=dialect))
    assert sql.startswith("DELETE FROM login_throttle")
    assert "LIMIT" in sql  # bounded candidate selection is kept
    outer = _outer_where_without_candidate_subquery(sql)
    assert "login_throttle.ip IN" in outer
    assert "login_throttle.locked_at IS NOT NULL" in outer
    assert "login_throttle.locked_at + login_throttle.lock_duration_seconds <=" in outer
    assert "login_throttle.locked_at IS NULL" in outer
    assert "login_throttle.updated_at <=" in outer
    # The row being recorded is excluded on the target too, not only among the candidates.
    with_keep = str(SqlLoginThrottleStore.sweep_statement(T0, keep="203.0.113.1").compile(dialect=dialect))
    assert "login_throttle.ip !=" in _outer_where_without_candidate_subquery(with_keep)


async def _wait_until_a_session_waits_on_a_lock(engine: AsyncEngine, *, timeout: float = 15.0) -> None:
    """Block until another backend of this database is waiting on a lock (pg_stat_activity)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with engine.connect() as conn:
            waiting = await conn.scalar(sa.text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"))
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the sweeping replica never blocked on the extending replica's row lock")


async def test_postgres_sweep_keeps_a_lock_extended_by_a_concurrent_check():
    """Reproduces the #6501 review interleaving on a real PostgreSQL.

    Replica A evaluates an expiring lock under a raised ``lockout_seconds``
    and extends it (the UPDATE ``check`` issues) without committing yet. An
    unrelated failed login on replica B sweeps: its snapshot still lists the IP
    as expired, its DELETE waits on A's row lock, and once A commits the
    re-evaluated row must survive — otherwise the next attempt from that IP
    gets a clean record and reaches password verification.
    """
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (PostgreSQL READ COMMITTED sweep/update interleaving)")
    schema = f"login_throttle_sweep_{uuid.uuid4().hex}"
    engines = [create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)) for _ in range(2)]
    engine_a, engine_b = engines
    try:
        async with engine_a.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(Base.metadata.create_all, tables=[LoginThrottleRow.__table__])
        session_factory_a = async_sessionmaker(engine_a, expire_on_commit=False)
        replica_a, replica_b = _sql_store(engine_a), _sql_store(engine_b)
        ip = "198.51.100.42"
        await _lock(replica_a, ip, lockout_seconds=1.0, now=T0)  # sentence ends at T0 + 1

        async with session_factory_a() as extending:
            # Replica A at T0 + 0.5 under lockout_seconds=60: the lock is still
            # active, so check() commits the longer sentence — held open here.
            await extending.execute(sa.update(LoginThrottleRow).where(LoginThrottleRow.ip == ip).values(lock_duration_seconds=60.0, updated_at=datetime.fromtimestamp(T0 + 0.5, UTC)))
            # Replica B at T0 + 2: an unrelated failure sweeps; its snapshot sees
            # the IP as expired and the DELETE blocks on A's row lock.
            sweeping = asyncio.create_task(replica_b.record_failure("203.0.113.5", max_attempts=5, lockout_seconds=60.0, now=T0 + 2.0))
            await _wait_until_a_session_waits_on_a_lock(engine_a)
            await extending.commit()
            await sweeping

        assert await replica_a.get(ip) == LoginThrottleRecord(fail_count=2, locked_at=T0, lock_duration=60.0)
        assert await replica_b.check(ip, policy=_policy(2, 60.0), now=T0 + 2.0) == pytest.approx(58.0)
        assert (await replica_b.get("203.0.113.5")).fail_count == 1  # the sweeping failure was still counted
    finally:
        async with engine_a.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for engine in engines:
            await engine.dispose()


# ── check(): compare-and-set misses between the snapshot read and the write ──


class _RacingSession:
    """Session proxy that lets a peer act right after ``check`` ends its read transaction.

    ``check`` reads its snapshot and ends that transaction with ``rollback()``
    before writing. Running the peer mutation at that point — on another
    engine over the same database — is exactly the reviewer's interleaving
    (#6501): the compare-and-set that follows sees a row that changed since
    the snapshot. The hook fires after the first read only unless
    ``every_time`` is set, which forces a miss on every attempt.
    """

    def __init__(self, inner, on_read_end: Callable[[], Awaitable[None]], state, *, every_time: bool) -> None:
        self._inner = inner
        self._on_read_end = on_read_end
        self._state = state
        self._every_time = every_time

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    async def rollback(self) -> None:
        await self._inner.rollback()
        if self._every_time or self._state["fired"] == 0:
            self._state["fired"] += 1
            await self._on_read_end()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _racing_store(engine: AsyncEngine, on_read_end: Callable[[], Awaitable[None]], *, every_time: bool = False) -> tuple[SqlLoginThrottleStore, dict]:
    real = async_sessionmaker(engine, expire_on_commit=False)
    state = {"fired": 0}
    return SqlLoginThrottleStore(lambda: _RacingSession(real(), on_read_end, state, every_time=every_time)), state


async def _two_replicas(path: Path):
    engine_a = await _sqlite_engine(path)
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    return engine_a, engine_b


async def test_check_recommits_a_raised_duration_after_a_concurrent_increment(tmp_path):
    """Reviewer's interleaving: the extension must be committed, not merely reported.

    Lock (5, T, 1s); operator raises lockout_seconds to 60. Replica A reads
    the row at T+0.5; before A's UPDATE an admitted wrong password on replica
    B increments the count (keeping the active lock's 1s duration). A's
    compare-and-set misses on ``fail_count``; it must re-read and commit the
    60s sentence on the fresh row, so a check at T+2 still reports locked.
    """
    engine_a, engine_b = await _two_replicas(tmp_path / "raise.db")
    try:
        replica_b = _sql_store(engine_b)
        ip = "198.51.100.50"
        for _ in range(5):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=1.0, now=T0)

        async def peer_failure() -> None:
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=1.0, now=T0 + 0.5)

        replica_a, state = _racing_store(engine_a, peer_failure)
        policy = _CountingPolicy(5, 60.0)
        assert await replica_a.check(ip, policy=policy, now=T0 + 0.5) == pytest.approx(59.5)
        assert state["fired"] == 1
        assert policy.calls == 1  # resolved once, even though the compare-and-set retried
        assert await replica_b.get(ip) == LoginThrottleRecord(fail_count=6, locked_at=T0, lock_duration=60.0)  # increment kept, extension committed
        assert await replica_b.check(ip, policy=_policy(5, 60.0), now=T0 + 2.0) == pytest.approx(58.0)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_check_recommits_a_lowered_duration_after_a_concurrent_increment(tmp_path):
    engine_a, engine_b = await _two_replicas(tmp_path / "lower.db")
    try:
        replica_b = _sql_store(engine_b)
        ip = "198.51.100.51"
        for _ in range(5):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0)

        async def peer_failure() -> None:
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 6.0)

        replica_a, state = _racing_store(engine_a, peer_failure)
        assert await replica_a.check(ip, policy=_policy(5, 10.0), now=T0 + 6.0) == pytest.approx(4.0)
        assert state["fired"] == 1
        assert await replica_b.get(ip) == LoginThrottleRecord(fail_count=6, locked_at=T0, lock_duration=10.0)  # the decrease is committed
        assert await replica_b.check(ip, policy=_policy(5, 30.0), now=T0 + 12.0) == 0.0  # 10s sentence served; not resurrected
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_check_releases_early_on_the_fresh_row_after_a_concurrent_increment(tmp_path):
    engine_a, engine_b = await _two_replicas(tmp_path / "release.db")
    try:
        replica_b = _sql_store(engine_b)
        ip = "198.51.100.52"
        for _ in range(5):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0)

        async def peer_failure() -> None:
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=60.0, now=T0 + 20.0)

        replica_a, state = _racing_store(engine_a, peer_failure)
        # Lowered to 10s and 20s have passed: release early — on the row as it is now.
        assert await replica_a.check(ip, policy=_policy(5, 10.0), now=T0 + 20.0) == 0.0
        assert state["fired"] == 1
        assert await replica_b.get(ip) is None
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_check_allows_when_a_reset_lands_between_read_and_write(tmp_path):
    """A successful login on a peer clears the row mid-check: allowed, and nothing is recreated."""
    engine_a, engine_b = await _two_replicas(tmp_path / "reset.db")
    try:
        replica_b = _sql_store(engine_b)
        ip = "198.51.100.53"
        for _ in range(5):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=1.0, now=T0)

        async def peer_success() -> None:
            await replica_b.reset(ip)

        replica_a, state = _racing_store(engine_a, peer_success)
        assert await replica_a.check(ip, policy=_policy(5, 60.0), now=T0 + 0.5) == 0.0
        assert state["fired"] == 1
        assert await replica_b.get(ip) is None
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_check_fails_closed_when_the_compare_and_set_keeps_missing(tmp_path, caplog):
    """Sustained contention exhausts the bounded retries: report the last snapshot under the live policy, write nothing."""
    import logging

    from deerflow.persistence.login_throttle.sql import CHECK_CAS_ATTEMPTS

    engine_a, engine_b = await _two_replicas(tmp_path / "exhaust.db")
    try:
        replica_b = _sql_store(engine_b)
        ip = "198.51.100.54"
        for _ in range(5):
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=1.0, now=T0)

        async def peer_failure() -> None:
            await replica_b.record_failure(ip, max_attempts=5, lockout_seconds=1.0, now=T0 + 0.5)

        replica_a, state = _racing_store(engine_a, peer_failure, every_time=True)
        with caplog.at_level(logging.DEBUG, logger="deerflow.persistence.login_throttle.sql"):
            remaining = await replica_a.check(ip, policy=_policy(5, 60.0), now=T0 + 0.5)
        assert remaining == pytest.approx(59.5)  # locked snapshot under the live 60s policy: fail closed
        # One probe read before the policy is resolved, then one read per compare-and-set attempt.
        assert state["fired"] == 1 + CHECK_CAS_ATTEMPTS
        # Nothing was committed by the losing checks; every peer increment survived.
        assert await replica_b.get(ip) == LoginThrottleRecord(fail_count=5 + 1 + CHECK_CAS_ATTEMPTS, locked_at=T0, lock_duration=1.0)
        assert any("compare-and-set" in r.message for r in caplog.records if r.levelno == logging.DEBUG)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
