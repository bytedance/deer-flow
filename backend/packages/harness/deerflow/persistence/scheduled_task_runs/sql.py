from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.utils.time import coerce_iso

TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"success", "failed", "skipped", "interrupted"})
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")


class ActiveScheduledRunConflict(Exception):
    """A concurrent dispatch already holds the task's single active-run slot.

    Raised by :meth:`ScheduledTaskRunRepository.create` when inserting an
    active (queued/running) run row would violate the partial unique index
    ``uq_scheduled_task_run_active`` (at most one active run per ``task_id``).
    This is the atomic counterpart to the non-atomic ``has_active_runs`` check
    in ``ScheduledTaskService.dispatch_task``: two dispatches can both pass that
    check, but only one can insert the active row — the loser lands here.

    Translating the SQLAlchemy ``IntegrityError`` into a domain exception at
    the repository boundary keeps the service layer free of ``sqlalchemy.exc``
    coupling (mirrors ``deerflow.runtime.ConflictError`` for the runs table).
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"scheduled task {task_id!r} already has an active run")


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
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Only active-status inserts can trip the partial unique index
                # ``uq_scheduled_task_run_active``; a terminal-status row (e.g.
                # a "skipped" tombstone) is outside its predicate and cannot
                # conflict, so any IntegrityError there is a genuine fault and
                # is re-raised untranslated.
                if status in ACTIVE_RUN_STATUSES:
                    raise ActiveScheduledRunConflict(task_id) from None
                raise
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_by_task(self, task_id: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(ScheduledTaskRunRow.task_id == task_id)
            .order_by(
                ScheduledTaskRunRow.created_at.desc(),
                ScheduledTaskRunRow.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def count_active_runs(self) -> int:
        """Global count of queued/running rows, used to bound cross-task concurrency."""
        stmt = select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def update_status(
        self,
        run_record_id: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        protect_terminal: bool = False,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return
            if protect_terminal and row.status in TERMINAL_RUN_STATUSES:
                # The launch-path "running" write lost the race against the
                # completion hook; keep the terminal status/error and only
                # backfill bookkeeping the completion write could not know.
                if row.run_id is None and run_id is not None:
                    row.run_id = run_id
                if row.started_at is None and started_at is not None:
                    row.started_at = started_at
                await session.commit()
                return
            row.status = status
            row.run_id = run_id
            row.error = error
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()

    async def has_active_runs(self, task_id: str) -> bool:
        stmt = (
            select(ScheduledTaskRunRow.id)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return result.scalars().first() is not None

    async def mark_stale_active_runs(self, *, error: str) -> int:
        """Fail-fast bookkeeping for runs orphaned by a process crash.

        Agent runs execute in-process, so any ``queued``/``running`` row found
        at scheduler startup belongs to a run whose process is gone. Only valid
        under the MVP's single-scheduler-instance assumption.
        """
        stmt = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES))
        now = datetime.now(UTC)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.status = "interrupted"
                row.error = error
                row.finished_at = now
            await session.commit()
            return len(rows)
