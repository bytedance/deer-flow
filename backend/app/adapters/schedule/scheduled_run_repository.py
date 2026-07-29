"""Secondary adapter (owned persistence) -- the scheduled_task_runs table in SQL.

Implements `ScheduledRunRepository` from `deerflow.domain.schedule.ports`. This
context owns the `scheduled_task_runs` table and writes its own queries.
Queries are migrated unchanged from the legacy repository.

The load-bearing piece is the `IntegrityError` translation in `add`: the
partial unique index `uq_scheduled_task_run_active` is the atomic arbiter of
"at most one active run per task", and turning its rejection into
`ActiveRunConflictError` is what lets the service collapse a lost race into
exactly the same outcome as its own non-atomic fast path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.domain.schedule.exceptions import ActiveRunConflictError
from deerflow.domain.schedule.model import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, RunStatus, ScheduledRun, TriggerKind
from deerflow.domain.schedule.ports import ScheduledRunRepository

# Transitional: the ORM row stays in the harness until engine, models, and
# migrations move into app/adapters together.
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow

_ACTIVE_STATUS_VALUES = tuple(str(status) for status in ACTIVE_RUN_STATUSES)


def _tz_aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read; stored values are always UTC."""
    return value if value is None or value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlScheduledRunRepository(ScheduledRunRepository):
    """SQL implementation of the `ScheduledRunRepository` port."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _to_domain(row: ScheduledTaskRunRow) -> ScheduledRun:
        return ScheduledRun(
            record_id=row.id,
            task_id=row.task_id,
            thread_id=row.thread_id,
            scheduled_for=_tz_aware(row.scheduled_for),
            trigger=TriggerKind(row.trigger),
            status=RunStatus(row.status),
            run_id=row.run_id,
            error=row.error,
            started_at=_tz_aware(row.started_at),
            finished_at=_tz_aware(row.finished_at),
            created_at=_tz_aware(row.created_at),
        )

    async def add(self, run: ScheduledRun) -> ScheduledRun:
        row = ScheduledTaskRunRow(
            id=run.record_id,
            task_id=run.task_id,
            thread_id=run.thread_id,
            run_id=run.run_id,
            scheduled_for=run.scheduled_for,
            trigger=str(run.trigger),
            status=str(run.status),
            error=run.error,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
        )
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Only an active-status insert can trip the partial unique
                # index; a terminal row (e.g. a skip tombstone) is outside its
                # predicate and cannot conflict, so an IntegrityError there is
                # a genuine fault and is re-raised untranslated.
                if run.is_active:
                    raise ActiveRunConflictError(f"scheduled task {run.task_id!r} already has an active run") from None
                raise
            await session.refresh(row)
            return self._to_domain(row)

    async def list_by_task(self, task_id: str, *, limit: int = 50, offset: int = 0) -> list[ScheduledRun]:
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
            return [self._to_domain(row) for row in result.scalars()]

    async def count_active(self) -> int:
        """Global count of active rows, used to bound cross-task concurrency."""
        stmt = select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(_ACTIVE_STATUS_VALUES))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def has_active(self, task_id: str) -> bool:
        stmt = (
            select(ScheduledTaskRunRow.id)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(_ACTIVE_STATUS_VALUES),
            )
            .limit(1)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return result.scalars().first() is not None

    async def update_status(
        self,
        record_id: str,
        *,
        status: RunStatus,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        protect_terminal: bool = False,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, record_id)
            if row is None:
                return
            if protect_terminal and RunStatus(row.status) in TERMINAL_RUN_STATUSES:
                # The launch-path "running" write lost the race against the
                # completion hook; keep the terminal status/error and only
                # backfill bookkeeping the completion write could not know.
                if row.run_id is None and run_id is not None:
                    row.run_id = run_id
                if row.started_at is None and started_at is not None:
                    row.started_at = started_at
                await session.commit()
                return
            row.status = str(status)
            row.run_id = run_id
            row.error = error
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()

    async def mark_stale_active(self, *, error: str) -> int:
        """Fail-fast bookkeeping for runs orphaned by a process crash.

        Agent runs execute in-process, so any active row found at scheduler
        startup belongs to a run whose process is gone. Only valid under the
        single-scheduler-instance assumption.
        """
        stmt = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(_ACTIVE_STATUS_VALUES))
        now = datetime.now(UTC)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.status = str(RunStatus.INTERRUPTED)
                row.error = error
                row.finished_at = now
            await session.commit()
            return len(rows)
