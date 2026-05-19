"""Async SQLAlchemy repository for closure tickets, events, and SLA configs.

The repository is a thin layer over the ORM models -- all business rules
(state transitions, permission checks, event publishing) live in the service
layer. The repository exists so the service layer can be unit-tested with a
fake repo and so SQL details (sessions, JSON encoding, pagination) stay out of
``service.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.closed_loop.state_machine import DEFAULT_SLA_HOURS
from deerflow.persistence.models.closure_ticket import (
    ClosureSlaConfigRow,
    ClosureTicketEventRow,
    ClosureTicketRow,
)


@dataclass
class PageResult:
    items: list[ClosureTicketRow]
    total: int
    page: int
    page_size: int


def _row_to_dict(row: ClosureTicketRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "severity": row.severity,
        "device_id": row.device_id,
        "device_name": row.device_name,
        "created_by": row.created_by,
        "assignee_id": row.assignee_id,
        "verifier_id": row.verifier_id,
        "source_type": row.source_type,
        "source_run_id": row.source_run_id,
        "source_thread_id": row.source_thread_id,
        "metadata": row.extra_metadata or {},
        "due_at": row.due_at,
        "is_overdue": row.is_overdue,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "assigned_at": row.assigned_at,
        "started_at": row.started_at,
        "submitted_at": row.submitted_at,
        "closed_at": row.closed_at,
    }


def _event_row_to_dict(row: ClosureTicketEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "tenant_id": row.tenant_id,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "actor_id": row.actor_id,
        "payload": row.payload or {},
        "created_at": row.created_at,
    }


class ClosureRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------ create

    async def create_ticket(
        self,
        *,
        tenant_id: str,
        title: str,
        created_by: str,
        priority: str,
        source_type: str,
        description: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
        device_name: str | None = None,
        source_run_id: str | None = None,
        source_thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Insert a new ticket. Returns ``(ticket_dict, created)``.

        If a ticket with the same idempotency key
        ``(tenant_id, source_type, source_run_id, device_id)`` already exists,
        we return the existing row with ``created=False`` -- this matches the
        spec's "same source same device must not produce a second ticket"
        scenario.
        """
        row = ClosureTicketRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            title=title,
            description=description,
            status="pending",
            priority=priority,
            severity=severity,
            device_id=device_id,
            device_name=device_name,
            created_by=created_by,
            source_type=source_type,
            source_run_id=source_run_id,
            source_thread_id=source_thread_id,
            extra_metadata=metadata or {},
            is_overdue=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Idempotency: locate the existing row and return it.
                existing = await self._find_by_source(
                    session,
                    tenant_id=tenant_id,
                    source_type=source_type,
                    source_run_id=source_run_id,
                    device_id=device_id,
                )
                if existing is None:
                    raise
                return _row_to_dict(existing), False
            await session.refresh(row)
            return _row_to_dict(row), True

    @staticmethod
    async def _find_by_source(
        session: AsyncSession,
        *,
        tenant_id: str,
        source_type: str,
        source_run_id: str | None,
        device_id: str | None,
    ) -> ClosureTicketRow | None:
        stmt = select(ClosureTicketRow).where(
            ClosureTicketRow.tenant_id == tenant_id,
            ClosureTicketRow.source_type == source_type,
            ClosureTicketRow.source_run_id.is_(None) if source_run_id is None else ClosureTicketRow.source_run_id == source_run_id,
            ClosureTicketRow.device_id.is_(None) if device_id is None else ClosureTicketRow.device_id == device_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------- read

    async def get_ticket(self, *, tenant_id: str, ticket_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = select(ClosureTicketRow).where(
                ClosureTicketRow.tenant_id == tenant_id,
                ClosureTicketRow.id == ticket_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None

    async def list_tickets(
        self,
        *,
        tenant_id: str,
        device_id: str | None = None,
        status: str | None = None,
        statuses: Sequence[str] | None = None,
        assignee_id: str | None = None,
        created_by: str | None = None,
        source_type: str | None = None,
        priority: str | None = None,
        is_overdue: bool | None = None,
        created_at_gte: datetime | None = None,
        created_at_lt: datetime | None = None,
        closed_at_gte: datetime | None = None,
        closed_at_lt: datetime | None = None,
        due_at_gte: datetime | None = None,
        due_at_lt: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> PageResult:
        clauses = [ClosureTicketRow.tenant_id == tenant_id]
        if device_id is not None:
            clauses.append(ClosureTicketRow.device_id == device_id)
        if status is not None:
            clauses.append(ClosureTicketRow.status == status)
        if statuses:
            clauses.append(ClosureTicketRow.status.in_(list(statuses)))
        if assignee_id is not None:
            clauses.append(ClosureTicketRow.assignee_id == assignee_id)
        if created_by is not None:
            clauses.append(ClosureTicketRow.created_by == created_by)
        if source_type is not None:
            clauses.append(ClosureTicketRow.source_type == source_type)
        if priority is not None:
            clauses.append(ClosureTicketRow.priority == priority)
        if is_overdue is not None:
            clauses.append(ClosureTicketRow.is_overdue == is_overdue)
        if created_at_gte is not None:
            clauses.append(ClosureTicketRow.created_at >= created_at_gte)
        if created_at_lt is not None:
            clauses.append(ClosureTicketRow.created_at < created_at_lt)
        if closed_at_gte is not None:
            clauses.append(ClosureTicketRow.closed_at >= closed_at_gte)
        if closed_at_lt is not None:
            clauses.append(ClosureTicketRow.closed_at < closed_at_lt)
        if due_at_gte is not None:
            clauses.append(ClosureTicketRow.due_at >= due_at_gte)
        if due_at_lt is not None:
            clauses.append(ClosureTicketRow.due_at < due_at_lt)

        order_col = getattr(ClosureTicketRow, order_by, ClosureTicketRow.created_at)
        order_clause = order_col.desc() if order_desc else order_col.asc()

        async with self._sf() as session:
            count_stmt = select(func.count()).select_from(ClosureTicketRow).where(*clauses)
            total = (await session.execute(count_stmt)).scalar_one()

            stmt = (
                select(ClosureTicketRow)
                .where(*clauses)
                .order_by(order_clause)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

        return PageResult(items=rows, total=total, page=page, page_size=page_size)

    # ------------------------------------------------------------------ update

    async def update_ticket_fields(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        column_updates: dict[str, Any],
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Apply column-level updates inside a single transaction.

        ``metadata_patch`` shallow-merges into ``extra_metadata``. We refuse
        ``status`` here so callers cannot bypass the state machine.
        """
        if "status" in column_updates:
            raise ValueError("Direct status updates are forbidden -- use transition()")

        async with self._sf() as session:
            stmt = select(ClosureTicketRow).where(
                ClosureTicketRow.tenant_id == tenant_id,
                ClosureTicketRow.id == ticket_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            for key, value in column_updates.items():
                setattr(row, key, value)
            if metadata_patch:
                merged = {**(row.extra_metadata or {}), **metadata_patch}
                row.extra_metadata = merged
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def apply_transition(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        column_updates: dict[str, Any],
        action: str,
        actor_id: str | None,
        from_status: str,
        to_status: str,
        event_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Atomically update the ticket and append an audit event."""
        async with self._sf() as session:
            stmt = select(ClosureTicketRow).where(
                ClosureTicketRow.tenant_id == tenant_id,
                ClosureTicketRow.id == ticket_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None

            for key, value in column_updates.items():
                setattr(row, key, value)

            event = ClosureTicketEventRow(
                id=str(uuid.uuid4()),
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                action=action,
                from_status=from_status,
                to_status=to_status,
                actor_id=actor_id,
                payload=event_payload or {},
                created_at=datetime.now(UTC),
            )
            session.add(event)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def list_events(self, *, tenant_id: str, ticket_id: str) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(ClosureTicketEventRow)
                .where(
                    ClosureTicketEventRow.tenant_id == tenant_id,
                    ClosureTicketEventRow.ticket_id == ticket_id,
                )
                .order_by(ClosureTicketEventRow.created_at.asc())
            )
            result = await session.execute(stmt)
            return [_event_row_to_dict(row) for row in result.scalars().all()]

    # --------------------------------------------------------- background job

    async def find_overdue_candidates(self, *, now: datetime, limit: int = 500) -> list[dict[str, Any]]:
        """Return open tickets whose ``due_at`` has passed but ``is_overdue`` is False."""
        async with self._sf() as session:
            stmt = (
                select(ClosureTicketRow)
                .where(
                    ClosureTicketRow.due_at.is_not(None),
                    ClosureTicketRow.due_at < now,
                    ClosureTicketRow.is_overdue == False,  # noqa: E712
                    ClosureTicketRow.status.notin_(["closed", "rejected"]),
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars().all()]

    async def mark_overdue(self, *, ticket_id: str, now: datetime) -> bool:
        """Idempotently flip ``is_overdue=True``. Returns True if the row changed."""
        async with self._sf() as session:
            stmt = (
                update(ClosureTicketRow)
                .where(
                    ClosureTicketRow.id == ticket_id,
                    ClosureTicketRow.is_overdue == False,  # noqa: E712
                    ClosureTicketRow.status.notin_(["closed", "rejected"]),
                )
                .values(is_overdue=True, updated_at=now)
            )
            result = await session.execute(stmt)
            await session.commit()
            return (result.rowcount or 0) > 0

    # --------------------------------------------------------- aggregates

    async def summary_counts(
        self, *, tenant_id: str, user_id: str | None
    ) -> dict[str, int]:
        async with self._sf() as session:
            base = select(func.count()).select_from(ClosureTicketRow).where(
                ClosureTicketRow.tenant_id == tenant_id,
                ClosureTicketRow.status.notin_(["closed", "rejected"]),
            )
            open_count = (await session.execute(base)).scalar_one()

            overdue_stmt = base.where(ClosureTicketRow.is_overdue == True)  # noqa: E712
            overdue_count = (await session.execute(overdue_stmt)).scalar_one()

            pv_stmt = (
                select(func.count())
                .select_from(ClosureTicketRow)
                .where(
                    ClosureTicketRow.tenant_id == tenant_id,
                    ClosureTicketRow.status == "pending_verification",
                )
            )
            pv_count = (await session.execute(pv_stmt)).scalar_one()

            assigned_count = 0
            if user_id is not None:
                assigned_stmt = (
                    select(func.count())
                    .select_from(ClosureTicketRow)
                    .where(
                        ClosureTicketRow.tenant_id == tenant_id,
                        ClosureTicketRow.assignee_id == user_id,
                        ClosureTicketRow.status.notin_(["closed", "rejected"]),
                    )
                )
                assigned_count = (await session.execute(assigned_stmt)).scalar_one()

            return {
                "open_count": int(open_count),
                "overdue_count": int(overdue_count),
                "pending_verification_count": int(pv_count),
                "assigned_to_me_count": int(assigned_count),
            }

    # ----------------------------------------------------------- SLA configs

    async def get_sla_overrides(self, *, tenant_id: str) -> dict[str, int]:
        """Return tenant SLA overrides; falls back to defaults for missing keys."""
        async with self._sf() as session:
            stmt = select(ClosureSlaConfigRow).where(
                or_(
                    ClosureSlaConfigRow.tenant_id == tenant_id,
                    ClosureSlaConfigRow.tenant_id == "__default__",
                )
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

        defaults = dict(DEFAULT_SLA_HOURS)
        # Apply __default__ first, then tenant rows so tenant takes precedence.
        for row in sorted(rows, key=lambda r: 0 if r.tenant_id == "__default__" else 1):
            defaults[row.priority] = int(row.sla_hours)
        return defaults
