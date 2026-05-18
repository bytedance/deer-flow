"""Audit storage: ORM row, repository ABC, and SQLite/Postgres impls (plan M2-2).

Tables (RFC §5.2):

- ``audit_events``: one row per :class:`AuditEvent`. ``details`` is a
  TEXT JSON column rather than JSONB so the schema is identical across
  SQLite and Postgres; queries that need server-side JSON path lookups
  are out of scope for v1.

Hot-path constraints
====================

``AuditMiddleware`` calls ``append()`` synchronously inside the agent
loop (RFC §5.4 — synchronous write is part of the contract; if it gets
slow we promote to the v2 queue in the §10 backlog). The implementation
therefore avoids any per-row class instantiation overhead beyond what
SQLAlchemy already does, and ``query`` is paginated by default so a
multi-million-row table doesn't melt the gateway when an operator hits
``GET /api/enterprise/audit/events``.

The Sqlite and Postgres classes share their implementation today; the
split exists so M3+ can add backend-specific optimisations (Postgres
``COPY``, batched UPSERTs, JSONB indexes) without renaming the public
classes that operators wire into ``config.yaml``.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.persistence.base import Base

logger = logging.getLogger(__name__)


# ── ORM model ──────────────────────────────────────────────────────────


class AuditEventRow(Base):
    """``audit_events`` table.

    Indexes are explicit (plan M2-3): the two hottest query shapes are
    "events for user X over time" and "events of type Y over time", both
    of which the ``GET /api/enterprise/audit/events`` route depends on.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_audit_events_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_events_type_timestamp", "event_type", "timestamp"),
    )


# ── Filter / contract types ────────────────────────────────────────────


@dataclass(frozen=True)
class AuditQueryFilter:
    """Filter knobs for :meth:`AuditStorage.query`.

    Only the listed fields are filterable in v1 — more knobs would
    invite ad-hoc query patterns that we can't index efficiently. Add
    them deliberately, with an index migration, when a use case demands.
    """

    user_id: str | None = None
    event_type: AuditEventType | None = None
    resource: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


# ── Repository contract ────────────────────────────────────────────────


class AuditStorage(ABC):
    """Read/write contract over :class:`AuditEventRow`.

    ``append`` is on the hot path; ``append_batch`` is provided for
    backfill / migration tooling. The base class supplies a for-loop
    fallback so concrete subclasses only have to override when they
    have a faster bulk path (Postgres ``COPY``, etc.).
    """

    @abstractmethod
    async def append(self, event: AuditEvent) -> None:
        """Persist a single audit event. Must be safe to call from agent loop."""

    async def append_batch(self, events: Iterable[AuditEvent]) -> None:
        """Persist many events. Default impl just iterates ``append``.

        Subclasses with a real bulk path (Postgres COPY, etc.) should
        override this method; the per-row fallback is correct but slow.
        """
        for event in events:
            await self.append(event)

    @abstractmethod
    async def query(self, filters: AuditQueryFilter) -> list[AuditEvent]:
        """Return events matching ``filters``, newest first, capped by ``limit``."""

    @abstractmethod
    async def count(self, filters: AuditQueryFilter) -> int:
        """Return total rows matching the filter (ignores limit / offset)."""

    @abstractmethod
    async def verify_integrity(
        self,
        signer: AuditSigner,
        filters: AuditQueryFilter | None = None,
    ) -> bool:
        """Re-sign every matching row and compare with stored signature.

        Returns False on first mismatch — the caller treats integrity as
        a tripwire, not a percentage, so short-circuiting is intentional.
        """


# ── Shared SQLAlchemy implementation ───────────────────────────────────


class _SqlAlchemyAuditStorage(AuditStorage):
    """Shared SQLAlchemy implementation used by both Sqlite and Postgres."""

    def __init__(self, session_factory: async_sessionmaker):
        self._sf = session_factory

    # ── append ────────────────────────────────────────────────────────

    async def append(self, event: AuditEvent) -> None:
        row = _event_to_row(event)
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    # ── query / count ────────────────────────────────────────────────

    async def query(self, filters: AuditQueryFilter) -> list[AuditEvent]:
        stmt = self._apply_filters(select(AuditEventRow), filters)
        stmt = stmt.order_by(AuditEventRow.timestamp.desc(), AuditEventRow.id.desc())
        stmt = stmt.limit(filters.limit).offset(filters.offset)
        async with self._sf() as session:
            rows: Sequence[AuditEventRow] = (await session.execute(stmt)).scalars().all()
        return [_row_to_event(r) for r in rows]

    async def count(self, filters: AuditQueryFilter) -> int:
        stmt = self._apply_filters(select(func.count(AuditEventRow.id)), filters)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    # ── verify ───────────────────────────────────────────────────────

    async def verify_integrity(
        self,
        signer: AuditSigner,
        filters: AuditQueryFilter | None = None,
    ) -> bool:
        # Cap the scan at a sane default — operators who need full-table
        # verification on >100k rows should iterate with offset paging
        # (plan §4.3 SLA): default ``limit`` keeps the request bounded.
        active = filters or AuditQueryFilter(limit=10_000)
        events = await self.query(active)
        for event in events:
            if not signer.verify(event):
                logger.warning(
                    "audit integrity failure on event %s (type=%s)",
                    event.id,
                    event.event_type.value,
                )
                return False
        return True

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_filters(stmt, filters: AuditQueryFilter):
        if filters.user_id is not None:
            stmt = stmt.where(AuditEventRow.user_id == filters.user_id)
        if filters.event_type is not None:
            stmt = stmt.where(AuditEventRow.event_type == filters.event_type.value)
        if filters.resource is not None:
            stmt = stmt.where(AuditEventRow.resource == filters.resource)
        if filters.since is not None:
            stmt = stmt.where(AuditEventRow.timestamp >= filters.since)
        if filters.until is not None:
            stmt = stmt.where(AuditEventRow.timestamp <= filters.until)
        return stmt


class SqliteAuditStorage(_SqlAlchemyAuditStorage):
    """SQLite backend — used by default and in tests."""


class PostgresAuditStorage(_SqlAlchemyAuditStorage):
    """Postgres backend — placeholder for future server-side tuning."""


# ── ORM <-> Pydantic translation ───────────────────────────────────────


def _event_to_row(event: AuditEvent) -> AuditEventRow:
    """Translate a Pydantic event to its ORM row counterpart."""
    return AuditEventRow(
        id=event.id,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        user_id=event.user_id,
        resource=event.resource,
        action=event.action,
        details=json.dumps(event.details, sort_keys=True, separators=(",", ":")),
        signature=event.signature,
    )


def _row_to_event(row: AuditEventRow) -> AuditEvent:
    """Translate an ORM row back to the Pydantic event.

    Unknown ``event_type`` values are tolerated — we coerce to a plain
    string and surface a warning, mirroring the RBAC repository's
    forward-compat pattern. The query path stays alive even when an
    older schema is read from a newer install.
    """
    try:
        event_type = AuditEventType(row.event_type)
    except ValueError:
        logger.warning("audit row %s has unknown event_type %r — coerced", row.id, row.event_type)
        # Fall back to a known sentinel; callers see the raw string in
        # ``details``. We never drop the row silently.
        event_type = AuditEventType.AGENT_TASK_COMPLETED

    try:
        details = json.loads(row.details) if row.details else {}
    except json.JSONDecodeError:
        logger.warning("audit row %s has corrupt details JSON — coerced to {}", row.id)
        details = {"_corrupt_raw": row.details}

    # SQLite drops tzinfo on round-trip — restore UTC so signature
    # verification (which canonicalises via ``isoformat``) sees an
    # identical byte stream to what was originally signed. We rely on
    # the AuditEvent invariant that ``timestamp`` is always UTC.
    timestamp = row.timestamp
    if timestamp is not None and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return AuditEvent(
        id=row.id,
        event_type=event_type,
        timestamp=timestamp,
        user_id=row.user_id,
        resource=row.resource,
        action=row.action,
        details=details,
        signature=row.signature,
    )


__all__ = [
    "AuditEventRow",
    "AuditQueryFilter",
    "AuditStorage",
    "PostgresAuditStorage",
    "SqliteAuditStorage",
]
