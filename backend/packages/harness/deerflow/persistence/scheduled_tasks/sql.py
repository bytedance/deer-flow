from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.utils.time import coerce_iso


class ScheduledTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in (
            "created_at",
            "updated_at",
            "next_run_at",
            "last_run_at",
            "lease_expires_at",
        ):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        task_id: str,
        user_id: str,
        thread_id: str | None,
        context_mode: str,
        assistant_id: str | None,
        title: str,
        prompt: str,
        schedule_type: str,
        schedule_spec: dict[str, Any],
        timezone: str,
        next_run_at: datetime | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = ScheduledTaskRow(
            id=task_id,
            user_id=user_id,
            thread_id=thread_id,
            context_mode=context_mode,
            assistant_id=assistant_id,
            title=title,
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_spec=schedule_spec,
            timezone=timezone,
            next_run_at=next_run_at,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, task_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def update(
        self,
        task_id: str,
        *,
        user_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            for key, value in updates.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def claim_due_tasks(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.status == "enabled",
                ScheduledTaskRow.next_run_at.is_not(None),
                ScheduledTaskRow.next_run_at <= now,
                or_(
                    ScheduledTaskRow.lease_expires_at.is_(None),
                    ScheduledTaskRow.lease_expires_at < now,
                ),
            )
            .order_by(ScheduledTaskRow.next_run_at.asc(), ScheduledTaskRow.id.asc())
            .limit(limit)
            .with_for_update()
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.status = "running"
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def release_lease(self, task_id: str, *, user_id: str | None = None) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            if user_id is not None and row.user_id != user_id:
                return
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def update_after_launch(
        self,
        task_id: str,
        *,
        status: str,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_run_id: str | None,
        last_thread_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            row.status = status
            row.next_run_at = next_run_at
            row.last_run_at = last_run_at
            row.last_run_id = last_run_id
            row.last_thread_id = last_thread_id
            row.last_error = last_error
            if increment_run_count:
                row.run_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
