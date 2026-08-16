from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.utils.time import coerce_iso

TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"success", "failed", "skipped", "interrupted"})
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("queued", "running")


def _lease_is_alive(lease_expires_at: datetime | None, *, now: datetime, grace_seconds: int) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now - timedelta(seconds=grace_seconds)


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
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._sf = session_factory
        self._run_repository = run_repository or RunRepository(session_factory)

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

    async def reconcile_active_runs(
        self,
        *,
        error: str,
        now: datetime,
        lease_grace_seconds: int = 10,
    ) -> int:
        """Reconcile only rows whose underlying owner is no longer live.

        ``RunManager`` owns the durable run lease. A scheduled row with a live
        underlying run, or a queued row whose parent task still has a dispatch
        lease, belongs to another process and must survive this startup.
        """
        async with self._sf() as session:
            result = await session.execute(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES)))
            row_ids = list(result.scalars())
            stale = 0
            for row_id in row_ids:
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in ACTIVE_RUN_STATUSES:
                    continue
                task = await session.get(ScheduledTaskRow, row.task_id, with_for_update=True)
                candidate = await self._find_underlying_run(session, row, task)
                if candidate is not None and candidate.status in {"pending", "running"}:
                    if _lease_is_alive(candidate.lease_expires_at, now=now, grace_seconds=lease_grace_seconds):
                        continue
                    # Run takeover commits in its own short transaction. If this
                    # outer commit fails, the next poll finishes scheduled-row
                    # bookkeeping while the run remains safely terminal.
                    claimed = await self._run_repository.claim_for_takeover(
                        candidate.run_id,
                        grace_seconds=lease_grace_seconds,
                        error=error,
                        stop_reason="scheduled_task_orphan_recovered",
                    )
                    if not claimed:
                        refreshed = await self._run_repository.get(candidate.run_id, user_id=None)
                        if refreshed is not None and refreshed.get("status") in {"pending", "running"}:
                            continue
                if row.run_id is None and task is not None and _lease_is_alive(task.lease_expires_at, now=now, grace_seconds=0):
                    continue
                row.status = "interrupted"
                row.error = error
                row.finished_at = now
                stale += 1
            await session.commit()
            return stale

    @staticmethod
    async def _find_underlying_run(session: AsyncSession, row: ScheduledTaskRunRow, task: ScheduledTaskRow | None) -> RunRow | None:
        run_ids = [candidate for candidate in (row.run_id, task.last_run_id if task is not None else None) if candidate]
        for run_id in dict.fromkeys(run_ids):
            candidate = await session.get(RunRow, run_id)
            if candidate is None:
                continue
            linked_task_run_id = (candidate.metadata_json or {}).get("scheduled_task_run_id")
            # A stale parent ``last_run_id`` may point at a previous occurrence.
            # Let the current scheduled-run metadata lookup recover the live row.
            if linked_task_run_id is None or linked_task_run_id == row.id:
                return candidate

        result = await session.execute(select(RunRow).where(RunRow.metadata_json["scheduled_task_run_id"].as_string() == row.id).order_by(RunRow.created_at.desc()).limit(1))
        return result.scalars().first()
