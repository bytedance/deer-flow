"""SQL repository for scheduled runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso

ACTIVE = "active"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
MISSED = "missed"


class ScheduledTaskRepository:
    """Persistence facade for one-time scheduled runs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _coerce_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRow) -> dict[str, Any]:
        data = row.to_dict()
        data["metadata"] = data.pop("metadata_json") or {}
        for key in ("run_at", "lease_until", "created_at", "updated_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = coerce_iso(value)
        return data

    async def create_once(
        self,
        *,
        owner_user_id: str,
        thread_id: str,
        prompt: str,
        run_at: datetime,
        timezone: str = "UTC",
        assistant_id: str = "lead_agent",
        agent_name: str | None = None,
        title: str | None = None,
        channel_name: str | None = None,
        chat_id: str | None = None,
        topic_id: str | None = None,
        thread_ts: str | None = None,
        channel_user_id: str | None = None,
        connection_id: str | None = None,
        owner_channel_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = ScheduledTaskRow(
            id=self._new_id(),
            owner_user_id=owner_user_id,
            thread_id=thread_id,
            assistant_id=assistant_id or "lead_agent",
            agent_name=agent_name,
            title=title,
            prompt=prompt,
            schedule_type="once",
            run_at=self._coerce_datetime(run_at),
            timezone=timezone or "UTC",
            status=ACTIVE,
            channel_name=channel_name,
            chat_id=chat_id,
            topic_id=topic_id,
            thread_ts=thread_ts,
            channel_user_id=channel_user_id,
            connection_id=connection_id,
            owner_channel_user_id=owner_channel_user_id,
            metadata_json=dict(metadata or {}),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(
        self,
        task_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ScheduledTaskRepository.get")
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.owner_user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list(
        self,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        resolved_user_id = resolve_user_id(user_id, method_name="ScheduledTaskRepository.list")
        stmt = select(ScheduledTaskRow).order_by(ScheduledTaskRow.created_at.desc()).limit(limit)
        if resolved_user_id is not None:
            stmt = stmt.where(ScheduledTaskRow.owner_user_id == resolved_user_id)
        if thread_id:
            stmt = stmt.where(ScheduledTaskRow.thread_id == thread_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def cancel(
        self,
        task_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        resolved_user_id = resolve_user_id(user_id, method_name="ScheduledTaskRepository.cancel")
        stmt = update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).where(ScheduledTaskRow.status.in_([ACTIVE, RUNNING])).values(status=CANCELLED, lease_until=None, updated_at=datetime.now(UTC))
        if resolved_user_id is not None:
            stmt = stmt.where(ScheduledTaskRow.owner_user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def list_due(self, *, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        now = self._coerce_datetime(now)
        claimable_status = or_(
            ScheduledTaskRow.status == ACTIVE,
            and_(ScheduledTaskRow.status == RUNNING, ScheduledTaskRow.lease_until < now),
        )
        stmt = select(ScheduledTaskRow).where(claimable_status).where(ScheduledTaskRow.run_at <= now).order_by(ScheduledTaskRow.run_at.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def claim_due(self, task_id: str, *, now: datetime, lease_seconds: int) -> dict[str, Any] | None:
        now = self._coerce_datetime(now)
        lease_until = now + timedelta(seconds=lease_seconds)
        async with self._sf() as session:
            stmt = (
                update(ScheduledTaskRow)
                .where(ScheduledTaskRow.id == task_id)
                .where(
                    or_(
                        ScheduledTaskRow.status == ACTIVE,
                        and_(ScheduledTaskRow.status == RUNNING, ScheduledTaskRow.lease_until < now),
                    )
                )
                .values(status=RUNNING, lease_until=lease_until, updated_at=now, last_error=None)
            )
            result = await session.execute(stmt)
            if not result.rowcount:
                await session.rollback()
                return None
            await session.commit()
            row = await session.get(ScheduledTaskRow, task_id)
            return self._row_to_dict(row) if row else None

    async def mark_completed(self, task_id: str, *, run_id: str | None = None) -> None:
        await self._mark_terminal(task_id, COMPLETED, run_id=run_id)

    async def mark_failed(self, task_id: str, *, error: str, run_id: str | None = None) -> None:
        await self._mark_terminal(task_id, FAILED, error=error, run_id=run_id)

    async def mark_missed(self, task_id: str, *, error: str) -> None:
        await self._mark_terminal(task_id, MISSED, error=error)

    async def _mark_terminal(self, task_id: str, status: str, *, error: str | None = None, run_id: str | None = None) -> None:
        values: dict[str, Any] = {
            "status": status,
            "lease_until": None,
            "updated_at": datetime.now(UTC),
        }
        if error is not None:
            values["last_error"] = error[:4000]
        if run_id is not None:
            values["last_run_id"] = run_id
        async with self._sf() as session:
            await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(**values))
            await session.commit()
