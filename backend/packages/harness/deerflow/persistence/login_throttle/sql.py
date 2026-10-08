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
  store's capacity eviction) so the table cannot grow without bound.

Database errors propagate: the users table lives in the same database, so a
login cannot succeed without it anyway, and failing closed keeps the throttle
from silently handing out unlimited verification.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.login_throttle.base import LoginThrottleRecord
from deerflow.persistence.login_throttle.model import LOGIN_THROTTLE_IP_LENGTH, LoginThrottleRow

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
            await self._sweep(session, now)
            insert = _insert_for(session)
            locks = LoginThrottleRow.fail_count + 1 >= max_attempts
            stmt = insert(LoginThrottleRow).values(ip=key, fail_count=1, locked_at=None, lock_duration_seconds=None, updated_at=stamp)
            stmt = stmt.on_conflict_do_update(
                index_elements=[LoginThrottleRow.ip],
                set_={
                    "fail_count": LoginThrottleRow.fail_count + 1,
                    "locked_at": case((locks, now), else_=None),
                    "lock_duration_seconds": case((locks, lockout_seconds), else_=None),
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
        """Compare-and-set predicate: the row still is the one the decision was made on."""
        return and_(
            LoginThrottleRow.ip == key,
            LoginThrottleRow.fail_count == snapshot.fail_count,
            LoginThrottleRow.locked_at == snapshot.locked_at,
            LoginThrottleRow.lock_duration_seconds == snapshot.lock_duration,
        )

    async def _discard(self, session: AsyncSession, key: str, snapshot: LoginThrottleRecord) -> None:
        await session.execute(delete(LoginThrottleRow).where(self._matches(key, snapshot)))
        await session.commit()

    async def _sweep(self, session: AsyncSession, now: float) -> None:
        """Bounded cleanup of served locks and stale never-locked counters."""
        served = and_(LoginThrottleRow.locked_at.is_not(None), LoginThrottleRow.locked_at + LoginThrottleRow.lock_duration_seconds <= now)
        stale = and_(LoginThrottleRow.locked_at.is_(None), LoginThrottleRow.updated_at <= _timestamp(now) - timedelta(seconds=STALE_COUNTER_SECONDS))
        victims = select(LoginThrottleRow.ip).where(or_(served, stale)).limit(SWEEP_BATCH_SIZE)
        await session.execute(delete(LoginThrottleRow).where(LoginThrottleRow.ip.in_(victims)))
        await session.commit()
