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
    """A concurrent dispatch already holds the task's active-occurrence slot.

    Coordinated admission serializes on the parent task before inserting the
    queue row. The partial unique index remains the database backstop for
    direct repository callers and legacy interleavings. Both paths surface the
    same domain exception without coupling the service to SQLAlchemy errors.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"scheduled task {task_id!r} already has an active run")


class ScheduledTaskAdmissionRejected(Exception):
    """The parent task changed or disappeared before queue admission."""

    def __init__(self, task_id: str, *, reason: str) -> None:
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"scheduled task {task_id!r} admission rejected: {reason}")


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
    async def _lock_task(session: AsyncSession, task_id: str) -> ScheduledTaskRow | None:
        # SQLite ignores SELECT ... FOR UPDATE. Touch the parent first so its
        # single-writer lock provides the same serialization point used by
        # Postgres row locking for admission, mutation, pause, and delete.
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(updated_at=ScheduledTaskRow.updated_at))
        return await session.get(ScheduledTaskRow, task_id, with_for_update=True)

    @staticmethod
    def _associate_scheduled_run(
        row: ScheduledTaskRunRow,
        candidate: RunRow,
    ) -> None:
        """Fill launch bookkeeping that the durable run already proves."""
        row.run_id = candidate.run_id
        if row.started_at is None:
            row.started_at = candidate.created_at

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
        coordinate_with_task: bool = False,
        expected_task_user_id: str | None = None,
        expected_task_status: str | None = None,
        expected_task_updated_at: datetime | str | None = None,
        expected_task_lease_owner: str | None = None,
        release_task_lease_status: str | None = None,
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
            task: ScheduledTaskRow | None = None
            if coordinate_with_task:
                task = await self._lock_task(session, task_id)
                if task is None or (expected_task_user_id is not None and task.user_id != expected_task_user_id):
                    await session.rollback()
                    raise ScheduledTaskAdmissionRejected(task_id, reason="not_found")
                if expected_task_lease_owner is not None:
                    if task.lease_owner != expected_task_lease_owner:
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                else:
                    if expected_task_status is not None and task.status != expected_task_status:
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                    if expected_task_updated_at is not None and coerce_iso(task.updated_at) != coerce_iso(expected_task_updated_at):
                        await session.rollback()
                        raise ScheduledTaskAdmissionRejected(task_id, reason="stale")
                active_status = await session.scalar(
                    select(ScheduledTaskRunRow.status)
                    .where(
                        ScheduledTaskRunRow.task_id == task_id,
                        ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .limit(1)
                )
                if active_status is not None:
                    await session.rollback()
                    raise ActiveScheduledRunConflict(task_id)
            session.add(row)
            if task is not None and release_task_lease_status is not None:
                task.status = release_task_lease_status
                task.lease_owner = None
                task.lease_expires_at = None
                task.updated_at = datetime.now(UTC)
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
                older.status.in_(ACTIVE_RUN_STATUSES),
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
                    older.status.in_(ACTIVE_RUN_STATUSES),
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
        """Expire waiting rows and update each parent in one transaction.

        The queued child keeps the task unclaimable until the parent lock is
        held.  Releasing the child slot and advancing the parent in the same
        transaction prevents a peer scheduler from taking a stale due-task
        lease between those two writes.
        """
        async with self._sf() as session:
            candidate_keys = list(
                (
                    await session.execute(
                        select(
                            ScheduledTaskRunRow.id,
                            ScheduledTaskRunRow.task_id,
                        )
                        .where(
                            ScheduledTaskRunRow.status == "queued",
                            ScheduledTaskRunRow.created_at <= created_before,
                        )
                        .order_by(
                            ScheduledTaskRunRow.task_id.asc(),
                            ScheduledTaskRunRow.id.asc(),
                        )
                    )
                ).all()
            )

        expired: list[dict[str, Any]] = []
        for row_id, task_id in candidate_keys:
            async with self._sf() as session:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status != "queued":
                    await session.rollback()
                    continue

                row.status = "failed"
                row.error = error
                row.finished_at = now
                row.lease_owner = None
                row.lease_expires_at = None

                if task is not None:
                    if task.status == "paused":
                        # A concurrent/later pause owns the parent presentation.
                        task.lease_owner = None
                        task.lease_expires_at = None
                    else:
                        if row.trigger == "manual":
                            next_at = task.next_run_at
                            task_status = task.status or "enabled"
                        else:
                            next_at = compute_next_run_at(
                                task.schedule_type,
                                task.schedule_spec,
                                task.timezone,
                                now=now,
                            )
                            task_status = "failed" if task.schedule_type == "once" else "enabled"
                        task.status = task_status
                        task.next_run_at = next_at
                        task.last_thread_id = row.thread_id
                        task.last_error = error
                        task.lease_owner = None
                        task.lease_expires_at = None
                    task.updated_at = datetime.now(UTC)

                await session.commit()
                expired.append(self._row_to_dict(row))
        return expired

    async def fail_launching_run(
        self,
        run_record_id: str,
        *,
        task_id: str,
        lease_owner: str,
        error: str,
        now: datetime,
    ) -> bool:
        """Fail a claimed launch and update its parent without a release gap."""
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.task_id != task_id or row.status != "launching" or row.lease_owner != lease_owner:
                await session.rollback()
                return False

            row.status = "failed"
            row.error = error
            row.started_at = now
            row.finished_at = now
            row.lease_owner = None
            row.lease_expires_at = None

            if task is not None:
                if row.trigger == "manual":
                    task_status = task.status or "enabled"
                    next_at = task.next_run_at
                else:
                    task_status = "failed" if task.schedule_type == "once" else "enabled"
                    next_at = compute_next_run_at(
                        task.schedule_type,
                        task.schedule_spec,
                        task.timezone,
                        now=now,
                    )
                task.status = task_status
                task.next_run_at = next_at
                task.last_run_at = now
                task.last_run_id = None
                task.last_thread_id = row.thread_id
                task.last_error = error
                task.lease_owner = None
                task.lease_expires_at = None
                task.updated_at = datetime.now(UTC)

            await session.commit()
            return True

    async def reconcile_launched_run(
        self,
        run_record_id: str,
        *,
        task_id: str,
        run_id: str,
        started_at: datetime,
    ) -> bool:
        """Associate a run that committed after its short claim was recovered.

        The Gateway launch path is idempotent per scheduled occurrence, so a
        peer that already reclaimed this row resolves to the same durable run.
        Parent-first locking restores the active slot before later parent
        bookkeeping can make the task due again.
        """
        async with self._sf() as session:
            await self._lock_task(session, task_id)
            row = await session.get(ScheduledTaskRunRow, run_record_id, with_for_update=True)
            if row is None or row.task_id != task_id:
                await session.rollback()
                return False
            if row.status in TERMINAL_RUN_STATUSES:
                if row.run_id is None:
                    # Timeout/pause can terminalize a claim that recovery
                    # briefly returned to ``queued`` while Gateway admission
                    # was still completing.  A returned durable run is the
                    # stronger fact; completion-owned terminal rows already
                    # carry this exact run_id and stay terminal below.
                    row.status = "running"
                    row.run_id = run_id
                    row.error = None
                    row.finished_at = None
                    row.started_at = row.started_at or started_at
                elif row.run_id != run_id:
                    await session.rollback()
                    return False
                elif row.started_at is None:
                    row.started_at = started_at
            else:
                row.status = "running"
                row.run_id = run_id
                row.error = None
                row.started_at = row.started_at or started_at
                row.lease_owner = None
                row.lease_expires_at = None
            await session.commit()
            return True

    async def recover_expired_launch_claims(self, *, error: str, now: datetime) -> int:
        """Recover single-instance claims that outlived their short lease."""
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(
                ScheduledTaskRunRow.status == "launching",
                or_(
                    ScheduledTaskRunRow.lease_expires_at.is_(None),
                    ScheduledTaskRunRow.lease_expires_at < now,
                ),
            )
            .order_by(
                ScheduledTaskRunRow.task_id.asc(),
                ScheduledTaskRunRow.id.asc(),
            )
        )
        async with self._sf() as session:
            row_keys = list((await session.execute(stmt)).all())
            recovered = 0
            for row_id, task_id in row_keys:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status != "launching":
                    continue
                candidate = await self._find_underlying_run(session, row, task)
                row.lease_owner = None
                row.lease_expires_at = None
                if candidate is None:
                    row.status = "queued"
                else:
                    self._associate_scheduled_run(row, candidate)
                    self._associate_task_with_run(task, row, candidate)
                    if candidate.status in {"pending", "running"}:
                        row.status = "running"
                        row.error = None
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
        stmt = (
            select(
                ScheduledTaskRunRow.id,
                ScheduledTaskRunRow.task_id,
            )
            .where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
            .order_by(
                ScheduledTaskRunRow.task_id.asc(),
                ScheduledTaskRunRow.id.asc(),
            )
        )
        now = datetime.now(UTC)
        async with self._sf() as session:
            row_keys = list((await session.execute(stmt)).all())
            recovered = 0
            for row_id, task_id in row_keys:
                task = await self._lock_task(session, task_id)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in EXECUTING_RUN_STATUSES:
                    continue
                row.lease_owner = None
                row.lease_expires_at = None
                candidate = await self._find_underlying_run(session, row, task)
                if row.status == "launching" and candidate is None:
                    row.status = "queued"
                else:
                    if candidate is not None:
                        self._associate_scheduled_run(row, candidate)
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
                recovered += 1
            await session.commit()
            return recovered

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
            result = await session.execute(
                select(
                    ScheduledTaskRunRow.id,
                    ScheduledTaskRunRow.task_id,
                )
                .where(ScheduledTaskRunRow.status.in_(EXECUTING_RUN_STATUSES))
                .order_by(
                    ScheduledTaskRunRow.task_id.asc(),
                    ScheduledTaskRunRow.id.asc(),
                )
            )
            row_keys = list(result.all())
            stale = 0
            associations: list[tuple[ScheduledTaskRow | None, ScheduledTaskRunRow, RunRow]] = []
            for row_id, task_id in row_keys:
                # Keep the same task -> scheduled-run lock order used by
                # pause/delete. Reversing these two locks lets a user action
                # and a peer reconciliation deadlock each other on Postgres.
                # Multi-instance reconciliation is Postgres-only. Keep this a
                # row lock without SQLite's writer-lock emulation because the
                # SQLite regression path performs durable-run takeover in a
                # nested short transaction below.
                task = await session.get(ScheduledTaskRow, task_id, with_for_update=True)
                row = await session.get(ScheduledTaskRunRow, row_id, with_for_update=True)
                if row is None or row.status not in EXECUTING_RUN_STATUSES:
                    continue
                candidate = await self._find_underlying_run(session, row, task)
                if candidate is not None:
                    self._associate_scheduled_run(row, candidate)
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
                        # A peer can observe the committed durable run before
                        # the launcher writes its scheduled-run bookkeeping.
                        # Once reconciliation releases the short launch claim,
                        # that owner-fenced write must be allowed to fail
                        # without leaving incomplete or stale history behind.
                        row.error = None
                        if row.status == "launching":
                            row.status = "running"
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
