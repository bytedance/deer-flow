from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.scheduler.schedules import next_run_at as compute_next_run_at
from deerflow.utils.time import coerce_iso

TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"success", "failed", "skipped", "interrupted"})
QUEUED_RUN_STATUSES: tuple[str, ...] = ("queued",)
EXECUTING_RUN_STATUSES: tuple[str, ...] = ("launching", "running")
ACTIVE_RUN_STATUSES: tuple[str, ...] = (*QUEUED_RUN_STATUSES, *EXECUTING_RUN_STATUSES)
_SCHEDULER_BUDGET_LOCK_KEY = 4694001


def _lease_is_alive(lease_expires_at: datetime | None, *, now: datetime, grace_seconds: int) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now - timedelta(seconds=grace_seconds)


class ActiveScheduledRunConflict(Exception):
    """A concurrent dispatch already holds the task's single active-run slot.

    Raised by :meth:`ScheduledTaskRunRepository.create` when inserting an
    active (queued/launching/running) run row would violate the partial unique index
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
        for key in (
            "scheduled_for",
            "lease_expires_at",
            "started_at",
            "finished_at",
            "created_at",
        ):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    @staticmethod
    def _associate_task_with_run(
        task: ScheduledTaskRow | None,
        row: ScheduledTaskRunRow,
        candidate: RunRow,
    ) -> None:
        """Repair the parent update if launch committed before bookkeeping."""
        if task is None or task.last_run_id == candidate.run_id:
            return
        launched_at = candidate.created_at
        if launched_at.tzinfo is None:
            launched_at = launched_at.replace(tzinfo=UTC)
        task.last_run_at = launched_at
        task.last_run_id = candidate.run_id
        task.last_thread_id = row.thread_id
        task.next_run_at = compute_next_run_at(
            task.schedule_type,
            task.schedule_spec,
            task.timezone,
            now=launched_at,
        )
        task.run_count += 1
        task.lease_owner = None
        task.lease_expires_at = None
        if task.schedule_type == "once":
            if candidate.status == "success":
                task.status = "completed"
                task.last_error = None
            elif candidate.status in {"error", "timeout"}:
                task.status = "failed"
                task.last_error = candidate.error
            elif candidate.status == "interrupted":
                task.status = "cancelled"
                task.last_error = candidate.error
            else:
                task.status = "running"
                task.last_error = None
        elif not (row.trigger == "manual" and task.status == "paused"):
            task.status = "enabled"
            task.last_error = candidate.error if candidate.status in {"error", "timeout", "interrupted"} else None

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
        """Count launch claims and live runs; waiting rows do not consume slots."""
        stmt = select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar() or 0)

    async def list_queued_runs(self, *, limit: int) -> list[dict[str, Any]]:
        older = aliased(ScheduledTaskRunRow)
        older_same_thread = exists(
            select(older.id).where(
                older.thread_id == ScheduledTaskRunRow.thread_id,
                older.status == "queued",
                or_(
                    older.created_at < ScheduledTaskRunRow.created_at,
                    and_(
                        older.created_at == ScheduledTaskRunRow.created_at,
                        older.id < ScheduledTaskRunRow.id,
                    ),
                ),
            )
        )
        stmt = (
            select(ScheduledTaskRunRow)
            .where(
                ScheduledTaskRunRow.status == "queued",
                ~older_same_thread,
            )
            # Prefer rows that have had fewer launch attempts. A permanently
            # busy thread therefore cannot monopolize the bounded drain batch,
            # while created_at/id preserve FIFO order among equal attempts.
            .order_by(
                ScheduledTaskRunRow.attempt_count.asc(),
                ScheduledTaskRunRow.created_at.asc(),
                ScheduledTaskRunRow.id.asc(),
            )
            .limit(limit)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def get_active_run(self, task_id: str) -> dict[str, Any] | None:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(ScheduledTaskRunRow.created_at.asc(), ScheduledTaskRunRow.id.asc())
            .limit(1)
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._row_to_dict(row) if row is not None else None

    async def claim_queued_run(
        self,
        run_record_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
        global_max_concurrent_runs: int,
    ) -> dict[str, Any] | None:
        """Atomically move one waiting row into the lease-fenced launch phase."""
        async with self._sf() as session:
            if session.get_bind().dialect.name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _SCHEDULER_BUDGET_LOCK_KEY},
                )
            executing = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES)))
            if int(executing or 0) >= global_max_concurrent_runs:
                await session.rollback()
                return None
            older = aliased(ScheduledTaskRunRow)
            older_same_thread = exists(
                select(older.id).where(
                    older.thread_id == ScheduledTaskRunRow.thread_id,
                    older.status == "queued",
                    or_(
                        older.created_at < ScheduledTaskRunRow.created_at,
                        and_(
                            older.created_at == ScheduledTaskRunRow.created_at,
                            older.id < ScheduledTaskRunRow.id,
                        ),
                    ),
                )
            )
            result = await session.execute(
                update(ScheduledTaskRunRow)
                .where(
                    ScheduledTaskRunRow.id == run_record_id,
                    ScheduledTaskRunRow.status == "queued",
                    ~older_same_thread,
                )
                .values(
                    status="launching",
                    lease_owner=lease_owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=ScheduledTaskRunRow.attempt_count + 1,
                )
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            return self._row_to_dict(row) if row is not None else None

    async def requeue_claimed_run(
        self,
        run_record_id: str,
        *,
        lease_owner: str,
        error: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                update(ScheduledTaskRunRow)
                .where(
                    ScheduledTaskRunRow.id == run_record_id,
                    ScheduledTaskRunRow.status == "launching",
                    ScheduledTaskRunRow.lease_owner == lease_owner,
                )
                .values(
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    error=error,
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def expire_queued_runs(
        self,
        *,
        created_before: datetime,
        error: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(
                ScheduledTaskRunRow.status == "queued",
                ScheduledTaskRunRow.created_at <= created_before,
            )
            .order_by(ScheduledTaskRunRow.created_at.asc(), ScheduledTaskRunRow.id.asc())
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
            for row in rows:
                row.status = "failed"
                row.error = error
                row.finished_at = now
                row.lease_owner = None
                row.lease_expires_at = None
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def recover_expired_launch_claims(self, *, error: str, now: datetime) -> int:
        """Recover single-instance claims that outlived their short lease."""
        stmt = select(ScheduledTaskRunRow.id).where(
            ScheduledTaskRunRow.status == "launching",
            or_(
                ScheduledTaskRunRow.lease_expires_at.is_(None),
                ScheduledTaskRunRow.lease_expires_at < now,
            ),
        )
        async with self._sf() as session:
            row_ids = list((await session.execute(stmt)).scalars())
            recovered = 0
            for row_id in row_ids:
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status != "launching":
                    continue
                task = await session.get(ScheduledTaskRow, row.task_id)
                candidate = await self._find_underlying_run(session, row, task)
                row.lease_owner = None
                row.lease_expires_at = None
                if candidate is None:
                    row.status = "queued"
                else:
                    row.run_id = candidate.run_id
                    self._associate_task_with_run(task, row, candidate)
                    if candidate.status in {"pending", "running"}:
                        row.status = "running"
                    elif candidate.status == "success":
                        row.status = "success"
                        row.error = None
                        row.finished_at = now
                    elif candidate.status in {"error", "timeout"}:
                        row.status = "failed"
                        row.error = candidate.error
                        row.finished_at = now
                    else:
                        row.status = "interrupted"
                        row.error = candidate.error or error
                        row.finished_at = now
                recovered += 1
            await session.commit()
            return recovered

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
        expected_lease_owner: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return False
            if protect_terminal and row.status in TERMINAL_RUN_STATUSES:
                # The launch-path "running" write lost the race against the
                # completion hook; keep the terminal status/error and only
                # backfill bookkeeping the completion write could not know.
                # Completion clears the short launch lease, so allow that
                # backfill after an owner mismatch only when the terminal row
                # already identifies the exact same durable run.  A stale
                # launcher for another run remains fenced.
                same_run = run_id is not None and row.run_id == run_id
                if expected_lease_owner is not None and row.lease_owner != expected_lease_owner and not same_run:
                    await session.rollback()
                    return False
                if row.run_id is None and run_id is not None:
                    row.run_id = run_id
                if row.started_at is None and started_at is not None:
                    row.started_at = started_at
                await session.commit()
                return True
            if expected_lease_owner is not None and row.lease_owner != expected_lease_owner:
                await session.rollback()
                return False
            row.status = status
            row.run_id = run_id
            row.error = error
            if status != "launching":
                row.lease_owner = None
                row.lease_expires_at = None
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()
            return True

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
        """Recover single-instance launch claims and fail orphaned live runs.

        Waiting rows are durable queue entries and survive restart. A
        ``launching`` row without a committed live run is safe to retry; a
        ``running`` row belonged to the dead in-process runtime.
        """
        stmt = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
        now = datetime.now(UTC)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = None
                row.lease_expires_at = None
                task = await session.get(ScheduledTaskRow, row.task_id)
                candidate = await self._find_underlying_run(session, row, task)
                if row.status == "launching" and candidate is None:
                    row.status = "queued"
                else:
                    if candidate is not None:
                        row.run_id = candidate.run_id
                        self._associate_task_with_run(task, row, candidate)
                    if candidate is not None and candidate.status == "success":
                        row.status = "success"
                        row.error = None
                    elif candidate is not None and candidate.status in {"error", "timeout"}:
                        row.status = "failed"
                        row.error = candidate.error
                    else:
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
            result = await session.execute(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES)))
            row_ids = list(result.scalars())
            stale = 0
            associations: list[tuple[ScheduledTaskRow | None, ScheduledTaskRunRow, RunRow]] = []
            for row_id in row_ids:
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in EXECUTING_RUN_STATUSES:
                    continue
                task = await session.get(ScheduledTaskRow, row.task_id, with_for_update=True)
                candidate = await self._find_underlying_run(session, row, task)
                if candidate is not None:
                    row.run_id = candidate.run_id
                    # Defer parent writes until all run takeovers have finished.
                    # Flushing a parent mutation before claim_for_takeover()
                    # would hold SQLite's writer lock across the nested short
                    # transaction used by that durable-run CAS.
                    associations.append((task, row, candidate))
                if candidate is not None and candidate.status not in {"pending", "running"}:
                    row.lease_owner = None
                    row.lease_expires_at = None
                    if candidate.status == "success":
                        row.status = "success"
                        row.error = None
                    elif candidate.status in {"error", "timeout"}:
                        row.status = "failed"
                        row.error = candidate.error
                    else:
                        row.status = "interrupted"
                        row.error = candidate.error or error
                    row.finished_at = now
                    stale += 1
                    continue
                if candidate is not None and candidate.status in {"pending", "running"}:
                    if _lease_is_alive(candidate.lease_expires_at, now=now, grace_seconds=lease_grace_seconds):
                        if row.status == "launching":
                            row.status = "running"
                            row.run_id = candidate.run_id
                            row.lease_owner = None
                            row.lease_expires_at = None
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
                if row.status == "launching" and row.run_id is None:
                    if _lease_is_alive(row.lease_expires_at, now=now, grace_seconds=0):
                        continue
                    row.status = "queued"
                    row.lease_owner = None
                    row.lease_expires_at = None
                    stale += 1
                    continue
                row.status = "interrupted"
                row.error = error
                row.finished_at = now
                row.lease_owner = None
                row.lease_expires_at = None
                stale += 1
            for task, row, candidate in associations:
                self._associate_task_with_run(task, row, candidate)
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
