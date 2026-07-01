from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.utils.time import coerce_iso


class ScheduledTaskRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRunRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in ("scheduled_for", "started_at", "finished_at", "created_at"):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        run_record_id: str,
        task_id: str,
        thread_id: str,
        scheduled_for: datetime,
        trigger: str,
        status: str,
    ) -> dict[str, Any]:
        row = ScheduledTaskRunRow(
            id=run_record_id,
            task_id=task_id,
            thread_id=thread_id,
            scheduled_for=scheduled_for,
            trigger=trigger,
            status=status,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_by_task(self, task_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(ScheduledTaskRunRow.task_id == task_id)
            .order_by(
                ScheduledTaskRunRow.created_at.desc(),
                ScheduledTaskRunRow.id.desc(),
            )
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def update_status(
        self,
        run_record_id: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return
            row.status = status
            row.run_id = run_id
            row.error = error
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()

    async def update_by_run_id(
        self,
        run_id: str,
        *,
        status: str,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        stmt = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.run_id == run_id).order_by(ScheduledTaskRunRow.created_at.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return
            row.status = status
            row.error = error
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()
