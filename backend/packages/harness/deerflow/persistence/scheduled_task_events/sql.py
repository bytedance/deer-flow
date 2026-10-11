"""SQL repository for scheduled-task lifecycle events.

``record_in_session`` runs inside the finalization transaction (the
scheduler's finalization observer calls it with the caller's session), so the
event commits or rolls back with the state change it reports. The insert is
``ON CONFLICT (task_id, anchor, event) DO NOTHING``: recovery that finalizes
the same transition again, or a replayed idle finish, adds no second row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_task_events.model import ScheduledTaskEventRow
from deerflow.utils.time import coerce_iso

# Payload keys the events route returns next to the row columns.
_PAYLOAD_FIELDS = ("task_title", "stop_condition", "run_thread_id", "run_agent_name", "run_number", "run_status", "max_runs", "end_at", "schedule_type")


class ScheduledTaskEventRepository:
    """Persistence facade for ``scheduled_task_events``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def to_api_dict(row: ScheduledTaskEventRow) -> dict[str, Any]:
        """The events-route shape: row columns plus the display payload, no owner."""
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        data: dict[str, Any] = {
            "id": row.id,
            "task_id": row.task_id,
            "event": row.event,
            "reason_code": row.reason_code,
        }
        for key in _PAYLOAD_FIELDS:
            data[key] = payload.get(key)
        data["after_run_id"] = row.after_run_id
        data["created_at"] = coerce_iso(row.created_at)
        return data

    @staticmethod
    async def record_in_session(
        session: AsyncSession,
        *,
        user_id: str,
        task_id: str,
        thread_id: str,
        occurrence_id: str | None,
        anchor: str,
        event: str,
        reason_code: str,
        after_run_id: str | None,
        payload: dict[str, Any],
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Stage one event row in the caller's transaction; a duplicate is ignored.

        Never commits and never rolls back: conflict handling must not undo the
        caller's state change or open a second writer while it holds the parent
        lock. Returns the stored row (the existing one on a duplicate).
        """
        dialect = session.get_bind().dialect.name
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError(f"Unsupported scheduled task event database dialect: {dialect}")
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        values = {
            "id": f"evt-{uuid.uuid4().hex}",
            "user_id": user_id,
            "task_id": task_id,
            "thread_id": thread_id,
            "occurrence_id": occurrence_id,
            "anchor": anchor,
            "event": event,
            "reason_code": reason_code,
            "after_run_id": after_run_id,
            "payload_json": dict(payload),
            "created_at": created_at or datetime.now(UTC),
        }
        statement = insert(ScheduledTaskEventRow).values(**values).on_conflict_do_nothing(index_elements=["task_id", "anchor", "event"])
        await session.execute(statement)
        row = await session.scalar(
            select(ScheduledTaskEventRow).where(
                ScheduledTaskEventRow.task_id == task_id,
                ScheduledTaskEventRow.anchor == anchor,
                ScheduledTaskEventRow.event == event,
            )
        )
        if row is None:
            raise RuntimeError("Scheduled task event insert produced no row")
        return ScheduledTaskEventRepository.to_api_dict(row)

    async def list_for_thread(self, *, user_id: str, thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """The caller's newest ``limit`` events of one chat, returned oldest first."""
        stmt = select(ScheduledTaskEventRow).where(ScheduledTaskEventRow.thread_id == thread_id, ScheduledTaskEventRow.user_id == user_id).order_by(ScheduledTaskEventRow.created_at.desc(), ScheduledTaskEventRow.id.desc()).limit(limit)
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
        return [self.to_api_dict(row) for row in reversed(rows)]

    async def delete_by_thread(self, thread_id: str, *, user_id: str | None) -> int:
        """Delete a chat's event rows; an explicit ``user_id`` scopes it to that owner.

        ``None`` removes every owner's rows (migration and CLI callers).
        """
        conditions = [ScheduledTaskEventRow.thread_id == thread_id]
        if user_id is not None:
            conditions.append(ScheduledTaskEventRow.user_id == user_id)
        async with self._sf() as session:
            result = await session.execute(delete(ScheduledTaskEventRow).where(*conditions))
            await session.commit()
            return int(result.rowcount or 0)
