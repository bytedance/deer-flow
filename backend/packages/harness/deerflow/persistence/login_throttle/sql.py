"""SQL-backed failed-login counter shared across Gateway replicas.

One ``login_throttle`` row per client IP in the application database (SQLite
or PostgreSQL). Every replica that shares the database sees the same row, so
``max_login_attempts`` is enforced once per IP instead of once per process.

Concurrency contract:

- ``record_failure`` is one dialect-native upsert (``INSERT ... ON CONFLICT
  (ip) DO UPDATE``) that increments the counter and starts the lock in the
  same statement, so racing failures never lose an increment and the
  "count reached ``max_attempts``" decision is made on the row's own value,
  not on a value read earlier.
- ``check`` reads the row in one short transaction and applies its decision
  (clear a served lock, commit a changed sentence) with a compare-and-set
  predicate on the snapshot it decided on, in a *separate* write transaction.
  Keeping the read transaction out of the write avoids SQLite's read→write
  upgrade (``SQLITE_BUSY`` / ``BUSY_SNAPSHOT`` under contention) while the
  predicate guarantees a racing success or failure is never clobbered — the
  same compare-and-set discipline the memory store uses on its dict.
- Cleanup is amortized into ``record_failure``: a bounded ``DELETE`` removes
  locks whose sentence has elapsed and never-locked counters idle for
  :data:`STALE_COUNTER_SECONDS` (the shared-table equivalent of the memory
  store's capacity eviction) so the table cannot grow without bound. The
  candidates come from an ``IN (SELECT ... LIMIT n)`` subquery bound to the
  statement snapshot, and the same expiry predicate is repeated on the
  ``DELETE`` target: PostgreSQL READ COMMITTED re-evaluates only the
  statement's *own* WHERE on a row it had to wait for, so without the outer
  predicate a lock that a concurrent ``check`` extended (or a stale counter a
  concurrent failure re-armed) between the snapshot and the row lock would
  still be deleted. Every other write (``_discard``, the ``check`` UPDATE)
  already carries its full compare-and-set predicate on the target row for
  the same reason; ``reset`` is unconditional by design.

A failure recorded while a lock is active keeps the lock's ``locked_at`` and
committed duration (the sentence is "N seconds after the lock started", not
"after the last attempt"); only a never-locked or already-served row gets a
fresh stamp. The upsert decides that from the row's own values in one
statement, so it stays atomic under racing failures.

``locked_at`` is the wall clock (``time.time()``) of whichever replica
recorded the failure, and every replica evaluates expiry against its own
clock. Replicas sharing a database must therefore run NTP: a skew of a few
seconds shifts lock evaluation by that much, which is acceptable for
lockouts measured in minutes but is the inherent cost of a wall-clock
lockout shared across hosts.

Housekeeping constants: the shared table, unlike the memory store's bounded
dict, has no implicit size limit, so every ``record_failure`` sweeps.
:data:`STALE_COUNTER_SECONDS` is 24 hours — the same guard the upload-staging
and project-document sweeps use for leftovers that may still be in use on
another replica — long enough that a legitimate user's typos a day apart are
not chained together, short enough to keep scanner one-offs from piling up.
:data:`SWEEP_BATCH_SIZE` (200) bounds the rows one failed login may delete,
so the write transaction stays short even if a backlog exists.

Database errors propagate: the users table lives in the same database, so a
login cannot succeed without it anyway, and failing closed keeps the throttle
from silently handing out unlimited verification.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.login_throttle.base import LoginThrottleRecord
from deerflow.persistence.login_throttle.model import LOGIN_THROTTLE_IP_LENGTH, LoginThrottleRow

logger = logging.getLogger(__name__)

#: Never-locked counters untouched for this long are dropped by the sweep.
STALE_COUNTER_SECONDS = 24 * 60 * 60
#: Rows one ``record_failure`` call may delete; bounds the write transaction.
SWEEP_BATCH_SIZE = 200


def _insert_for(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert
    if dialect == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported login throttle database dialect: {dialect}")


def _record(fail_count: int, locked_at: float | None, lock_duration: float | None) -> LoginThrottleRecord:
    return LoginThrottleRecord(fail_count=int(fail_count), locked_at=float(locked_at or 0.0), lock_duration=float(lock_duration or 0.0))


def _key(ip: str) -> str:
    """Bound the row key to the column length; a trusted proxy may forward a token-like ``X-Real-IP``.

    The key itself is never logged: it may be an identifier the proxy did not
    mean to expose, and it is unbounded. Truncation keeps the throttle
    fail-closed (colliding prefixes share a stricter budget).
    """
    if len(ip) <= LOGIN_THROTTLE_IP_LENGTH:
        return ip
    logger.warning("Login throttle client key of %d characters truncated to %d; check the trusted proxy's X-Real-IP value.", len(ip), LOGIN_THROTTLE_IP_LENGTH)
    return ip[:LOGIN_THROTTLE_IP_LENGTH]


def _timestamp(now: float) -> datetime:
    return datetime.fromtimestamp(now, UTC)


class SqlLoginThrottleStore:
    """Persistence facade for ``login_throttle``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self, ip: str) -> LoginThrottleRecord | None:
        async with self._sf() as session:
            row = (await session.execute(self._select(_key(ip)))).first()
        return None if row is None else _record(*row)

    async def check(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> float:
        key = _key(ip)
        async with self._sf() as session:
            row = (await session.execute(self._select(key))).first()
            await session.rollback()  # end the read transaction before any write
            if row is None:
                return 0.0
            record = _record(*row)
            if record.fail_count < max_attempts:
                return 0.0
            if not record.locked:
                # Over the current threshold but never locked under it (the
                # operator tightened max_login_attempts mid-count): keep the
                # count, the next failure starts the lock.
                return 0.0
            now = time.time() if now is None else now
            if now >= record.expires_at:
                # Served the sentence committed when it started; a later raise
                # of lockout_seconds must not resurrect it.
                await self._discard(session, key, record)
                return 0.0
            if now < record.locked_at + lockout_seconds:
                # Still locked under the current duration; commit that
                # evaluation (decreases included) so the stored sentence
                # matches the policy the lock was last evaluated under.
                if lockout_seconds != record.lock_duration:
                    await session.execute(update(LoginThrottleRow).where(self._matches(key, record)).values(lock_duration_seconds=lockout_seconds, updated_at=_timestamp(now)))
                    await session.commit()
                return record.locked_at + lockout_seconds - now
            # Original sentence still running but the current (lowered)
            # duration already elapsed: release early.
            await self._discard(session, key, record)
            return 0.0

    async def record_failure(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> LoginThrottleRecord:
        key = _key(ip)
        now = time.time() if now is None else now
        stamp = _timestamp(now)
        async with self._sf() as session:
            await self._sweep(session, now, keep=key)
            insert = _insert_for(session)
            # One atomic decision on the row's own values (see the module
            # docstring): below the threshold -> counting, lock cleared; at or
            # over it during an *active* lock -> keep the lock's start and
            # committed duration; otherwise (never locked / served) -> stamp now.
            reaches = LoginThrottleRow.fail_count + 1 >= max_attempts
            active = and_(LoginThrottleRow.locked_at.is_not(None), LoginThrottleRow.locked_at + LoginThrottleRow.lock_duration_seconds > now)
            stmt = insert(LoginThrottleRow).values(ip=key, fail_count=1, locked_at=None, lock_duration_seconds=None, updated_at=stamp)
            stmt = stmt.on_conflict_do_update(
                index_elements=[LoginThrottleRow.ip],
                set_={
                    "fail_count": LoginThrottleRow.fail_count + 1,
                    "locked_at": case((and_(reaches, active), LoginThrottleRow.locked_at), (reaches, now), else_=None),
                    "lock_duration_seconds": case((and_(reaches, active), LoginThrottleRow.lock_duration_seconds), (reaches, lockout_seconds), else_=None),
                    "updated_at": stamp,
                },
            ).returning(LoginThrottleRow.fail_count, LoginThrottleRow.locked_at, LoginThrottleRow.lock_duration_seconds)
            row = (await session.execute(stmt)).one()
            await session.commit()
        return _record(*row)

    async def reset(self, ip: str) -> None:
        async with self._sf() as session:
            await session.execute(delete(LoginThrottleRow).where(LoginThrottleRow.ip == _key(ip)))
            await session.commit()

    @staticmethod
    def _select(key: str):
        return select(LoginThrottleRow.fail_count, LoginThrottleRow.locked_at, LoginThrottleRow.lock_duration_seconds).where(LoginThrottleRow.ip == key)

    @staticmethod
    def _matches(key: str, snapshot: LoginThrottleRecord):
        """Compare-and-set predicate: the row still is the one the decision was made on.

        Carried by the target row of every ``check`` write, so a database
        that re-evaluates the WHERE after waiting on a concurrent writer
        (PostgreSQL READ COMMITTED) sees the changed tuple and skips the
        stale decision instead of applying it.
        """
        return and_(
            LoginThrottleRow.ip == key,
            LoginThrottleRow.fail_count == snapshot.fail_count,
            LoginThrottleRow.locked_at == snapshot.locked_at,
            LoginThrottleRow.lock_duration_seconds == snapshot.lock_duration,
        )

    async def _discard(self, session: AsyncSession, key: str, snapshot: LoginThrottleRecord) -> None:
        await session.execute(delete(LoginThrottleRow).where(self._matches(key, snapshot)))
        await session.commit()

    @staticmethod
    def _expired(now: float):
        """Rows the sweep may drop: served locks and never-locked counters idle past the stale window."""
        served = and_(LoginThrottleRow.locked_at.is_not(None), LoginThrottleRow.locked_at + LoginThrottleRow.lock_duration_seconds <= now)
        stale = and_(LoginThrottleRow.locked_at.is_(None), LoginThrottleRow.updated_at <= _timestamp(now) - timedelta(seconds=STALE_COUNTER_SECONDS))
        return or_(served, stale)

    @classmethod
    def sweep_statement(cls, now: float, *, keep: str | None = None):
        """The bounded cleanup ``DELETE`` (see the module docstring's cleanup contract).

        ``keep`` is the key the calling ``record_failure`` is about to upsert:
        that row is live and the upsert decides its fate from its own values
        (a served lock starts a fresh sentence, a stale counter keeps counting),
        exactly as the memory store does; sweeping it first would turn the
        failure into a fresh ``(1, NULL, NULL)`` row and split the contract.

        The expiry predicate appears twice on purpose: once inside the
        ``IN (SELECT ... LIMIT n)`` subquery that bounds the batch, and again
        on the ``DELETE`` target. The subquery is evaluated against the
        statement snapshot; PostgreSQL READ COMMITTED re-evaluates only the
        outer WHERE on a row whose lock it had to wait for, and ``ip IN (...)``
        still holds for that old candidate — so without the repeated predicate
        a lock that a concurrent ``check`` just extended (its UPDATE committed
        while this DELETE waited) would be deleted and the next attempt from
        that IP would reach password verification. SQLite serializes writers,
        so there the repetition is merely redundant.
        """
        candidates = cls._expired(now) if keep is None else and_(LoginThrottleRow.ip != keep, cls._expired(now))
        victims = select(LoginThrottleRow.ip).where(candidates).limit(SWEEP_BATCH_SIZE)
        target = cls._expired(now) if keep is None else and_(LoginThrottleRow.ip != keep, cls._expired(now))
        return delete(LoginThrottleRow).where(LoginThrottleRow.ip.in_(victims), target)

    async def _sweep(self, session: AsyncSession, now: float, *, keep: str) -> None:
        """Bounded cleanup of served locks and stale never-locked counters, leaving ``keep`` to the upsert."""
        await session.execute(self.sweep_statement(now, keep=keep))
        await session.commit()
