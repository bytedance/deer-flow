"""SQL repository for ``channel_leases`` (SQLite or PostgreSQL).

Every write is one statement whose WHERE clause decides ownership against the
database clock of that statement (``statement_timestamp()`` on PostgreSQL,
``julianday('now')`` on SQLite, both as epoch seconds), so the decision never
depends on an instance's wall clock:

- ``acquire`` is one dialect-native upsert: ``INSERT ... ON CONFLICT
  (provider) DO UPDATE ... WHERE lease_expires_at + grace < now OR owner_id =
  :me``. A missing row is created at epoch 1; an existing row changes hands
  only when its lease has been expired for ``grace`` seconds (or this owner
  already holds it), and every acquisition bumps ``epoch``. Two instances
  racing on the same provider serialize on the row: PostgreSQL evaluates the
  ``DO UPDATE`` predicate on the row version the winner committed, and SQLite
  serializes writers, so exactly one statement changes a row. The winner reads
  its new epoch back in the same transaction (its own write, still locked).
- ``renew`` extends only a live lease: ``UPDATE ... WHERE owner_id = :me AND
  epoch = :epoch AND lease_expires_at > now``. A lease that already expired
  must be re-acquired (bumping the epoch) instead of silently revived, so a
  holder whose renewals lapsed cannot keep a lease a peer is about to take.
- ``release`` sets ``lease_expires_at`` to 0 under the same owner/epoch fence,
  so a peer may acquire on its next attempt instead of waiting out the TTL.
  The row stays (its epoch keeps growing across holders).

Outcomes are decided by the affected-row count, never by ``RETURNING``
values: through SQLAlchemy's aiosqlite adapter, an ``UPDATE ... RETURNING``
that runs while another connection reads the table has been observed to hand
back one of the statement's own bind values instead of the column (the stored
row is correct). A lease must not mistake such a row for a confirmed renewal,
so writes report ``rowcount`` and the epoch is read with a plain ``SELECT``.

The holder's own safety deadline is local and monotonic, and lives in
``app.channels.leadership``: the lease row only says who may connect, the
holder must stop its transport before a peer is allowed to.

Database errors propagate; the caller treats them as "renewal not confirmed".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Double, cast, extract, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.channel_leases.model import ChannelLeaseGrant, ChannelLeaseRow, ChannelLeaseState

#: Julian day number of the Unix epoch (1970-01-01T00:00:00Z).
_UNIX_EPOCH_JULIAN_DAY = 2440587.5
_SECONDS_PER_DAY = 86400.0


def _dialect(session: AsyncSession) -> str:
    name = session.get_bind().dialect.name
    if name not in ("postgresql", "sqlite"):
        raise ValueError(f"Unsupported channel lease database dialect: {name}")
    return name


def db_now(dialect: str) -> Any:
    """The current time of the statement, in epoch seconds, from the database clock.

    SQLite evaluates ``'now'`` once per statement step, PostgreSQL's
    ``statement_timestamp()`` is fixed for the statement, so every reference in
    one statement sees the same instant.
    """
    if dialect == "postgresql":
        return cast(extract("epoch", func.statement_timestamp()), Double)
    return (func.julianday("now") - _UNIX_EPOCH_JULIAN_DAY) * _SECONDS_PER_DAY


class SqlChannelLeaseRepository:
    """Persistence facade for ``channel_leases``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def acquire(self, provider: str, owner_id: str, *, ttl_seconds: float, grace_seconds: float) -> ChannelLeaseGrant | None:
        """Take the provider's lease, or return ``None`` while another owner holds it."""
        async with self._sf() as session:
            dialect = _dialect(session)
            now = db_now(dialect)
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            stmt = insert(ChannelLeaseRow).values(provider=provider, owner_id=owner_id, epoch=1, lease_expires_at=now + ttl_seconds, transport_running=False, updated_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=[ChannelLeaseRow.provider],
                set_={
                    "owner_id": owner_id,
                    "epoch": ChannelLeaseRow.epoch + 1,
                    "lease_expires_at": now + ttl_seconds,
                    "transport_running": False,
                    "updated_at": now,
                },
                where=or_(ChannelLeaseRow.lease_expires_at + grace_seconds < now, ChannelLeaseRow.owner_id == owner_id),
            )
            if (await session.execute(stmt)).rowcount != 1:
                await session.rollback()
                return None
            # Our own write, read inside the transaction that still holds it.
            row = (await session.execute(select(ChannelLeaseRow.epoch, ChannelLeaseRow.lease_expires_at).where(ChannelLeaseRow.provider == provider, ChannelLeaseRow.owner_id == owner_id))).one()
            await session.commit()
        return ChannelLeaseGrant(provider=provider, epoch=int(row.epoch), lease_expires_at=float(row.lease_expires_at))

    async def renew(self, provider: str, owner_id: str, epoch: int, *, ttl_seconds: float, transport_running: bool) -> bool:
        """Extend a live lease this owner holds at ``epoch``; ``False`` means it is no longer held."""
        async with self._sf() as session:
            now = db_now(_dialect(session))
            stmt = (
                update(ChannelLeaseRow)
                .where(
                    ChannelLeaseRow.provider == provider,
                    ChannelLeaseRow.owner_id == owner_id,
                    ChannelLeaseRow.epoch == epoch,
                    ChannelLeaseRow.lease_expires_at > now,
                )
                .values(lease_expires_at=now + ttl_seconds, transport_running=transport_running, updated_at=now)
            )
            renewed = (await session.execute(stmt)).rowcount == 1
            await session.commit()
        return renewed

    async def release(self, provider: str, owner_id: str, epoch: int) -> bool:
        """Give up the lease held at ``epoch`` so a peer can take it at once; ``False`` if it was not ours."""
        async with self._sf() as session:
            now = db_now(_dialect(session))
            stmt = update(ChannelLeaseRow).where(ChannelLeaseRow.provider == provider, ChannelLeaseRow.owner_id == owner_id, ChannelLeaseRow.epoch == epoch).values(lease_expires_at=0.0, transport_running=False, updated_at=now)
            released = (await session.execute(stmt)).rowcount == 1
            await session.commit()
        return released

    async def get(self, provider: str) -> ChannelLeaseState | None:
        """Read one provider's lease; ``live`` is judged against the database clock of the read."""
        states = await self._read(ChannelLeaseRow.provider == provider)
        return states[0] if states else None

    async def list_all(self) -> list[ChannelLeaseState]:
        return await self._read(None)

    async def _read(self, predicate: Any) -> list[ChannelLeaseState]:
        async with self._sf() as session:
            now = db_now(_dialect(session))
            stmt = select(
                ChannelLeaseRow.provider,
                ChannelLeaseRow.owner_id,
                ChannelLeaseRow.epoch,
                ChannelLeaseRow.lease_expires_at,
                ChannelLeaseRow.transport_running,
                (ChannelLeaseRow.lease_expires_at > now).label("live"),
            ).order_by(ChannelLeaseRow.provider)
            if predicate is not None:
                stmt = stmt.where(predicate)
            rows = (await session.execute(stmt)).all()
        return [
            ChannelLeaseState(
                provider=row.provider,
                owner_id=row.owner_id,
                epoch=int(row.epoch),
                lease_expires_at=float(row.lease_expires_at),
                transport_running=bool(row.transport_running),
                live=bool(row.live),
            )
            for row in rows
        ]
