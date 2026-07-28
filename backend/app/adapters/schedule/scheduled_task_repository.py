"""Secondary adapter (owned persistence) -- the scheduled_tasks table in SQL.

Implements `ScheduledTaskRepository` from `deerflow.domain.schedule.ports`.
This context owns the `scheduled_tasks` table and writes its own queries, so
SQL/ORM vocabulary stops at this file: methods exchange domain objects and
normalize SQLite's tz-naive reads.

Sibling of `scheduled_run_repository.py`. The stored `schedule_spec` JSON
column is translated by `spec_column.py`, which belongs to this side of the
boundary only -- the HTTP shape has its own translation next to the router.

**The queries are migrated unchanged from the legacy repository.** The claim
statement's `FOR UPDATE SKIP LOCKED` and the `protect_terminal` conditional
write are the module's concurrency contract, not style choices -- rewriting
them is how the invariants silently break.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.schedule.spec_column import column_to_spec, spec_to_column
from deerflow.domain.schedule.model import (
    TERMINAL_TASK_STATUSES,
    ContextMode,
    InvalidScheduleError,
    ScheduledTask,
    TaskStatus,
)
from deerflow.domain.schedule.ports import ScheduledTaskRepository

# Transitional: the ORM row stays in the harness until engine, models, and
# migrations move into app/adapters together.
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

logger = logging.getLogger(__name__)


def _tz_aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read; stored values are always UTC."""
    return value if value is None or value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlScheduledTaskRepository(ScheduledTaskRepository):
    """SQL implementation of the `ScheduledTaskRepository` port.

    Explicit inheritance is a readability aid only: a missing method would
    still instantiate fine (Protocol bodies are inherited), so the contract
    test suite must cover every port method.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        # Diagnostics only. The domain deliberately does not carry this -- who
        # claimed a task is an identity, not a rule, and nothing reads it back.
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _to_domain(row: ScheduledTaskRow) -> ScheduledTask:
        """ORM row -> aggregate.

        Raises InvalidScheduleError for a row whose stored schedule can no
        longer be parsed. That is a **new** failure mode: the legacy repository
        returned bare dicts and a corrupt spec only surfaced at dispatch time.
        Single-row reads let it propagate; list reads skip and log, so one bad
        row cannot 500 an entire listing.
        """
        return ScheduledTask(
            task_id=row.id,
            user_id=row.user_id,
            title=row.title,
            prompt=row.prompt,
            schedule=column_to_spec(row.schedule_type, row.schedule_spec, row.timezone),
            context_mode=ContextMode(row.context_mode),
            thread_id=row.thread_id,
            assistant_id=row.assistant_id,
            status=TaskStatus(row.status),
            overlap_policy=row.overlap_policy,
            next_run_at=_tz_aware(row.next_run_at),
            last_run_at=_tz_aware(row.last_run_at),
            last_run_id=row.last_run_id,
            last_thread_id=row.last_thread_id,
            last_error=row.last_error,
            run_count=row.run_count,
            created_at=_tz_aware(row.created_at),
            updated_at=_tz_aware(row.updated_at),
        )

    @classmethod
    def _to_domain_or_skip(cls, row: ScheduledTaskRow) -> ScheduledTask | None:
        try:
            return cls._to_domain(row)
        except InvalidScheduleError:
            logger.warning("Skipping scheduled task %s: stored schedule is unparseable", row.id, exc_info=True)
            return None

    @staticmethod
    def _apply(row: ScheduledTaskRow, task: ScheduledTask) -> None:
        """Aggregate -> ORM row. Explicit field list: a new column stays
        invisible here until it is deliberately mapped."""
        row.user_id = task.user_id
        row.title = task.title
        row.prompt = task.prompt
        row.schedule_type = str(task.schedule.schedule_type)
        row.schedule_spec = spec_to_column(task.schedule)
        row.timezone = task.schedule.timezone
        row.context_mode = str(task.context_mode)
        row.thread_id = task.thread_id
        row.assistant_id = task.assistant_id
        row.status = str(task.status)
        row.overlap_policy = task.overlap_policy
        row.next_run_at = task.next_run_at
        row.last_run_at = task.last_run_at
        row.last_run_id = task.last_run_id
        row.last_thread_id = task.last_thread_id
        row.last_error = task.last_error
        row.run_count = task.run_count

    # ------------------------------------------------------------------ port

    async def add(self, task: ScheduledTask) -> ScheduledTask:
        now = datetime.now(UTC)
        row = ScheduledTaskRow(id=task.task_id, created_at=now, updated_at=now)
        self._apply(row, task)
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._to_domain(row)

    async def get(self, task_id: str, *, user_id: str) -> ScheduledTask | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._to_domain(row)

    async def list_by_user(self, user_id: str) -> list[ScheduledTask]:
        stmt = select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [task for task in (self._to_domain_or_skip(row) for row in result.scalars()) if task is not None]

    async def list_by_user_and_thread(self, user_id: str, thread_id: str) -> list[ScheduledTask]:
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.user_id == user_id,
                ScheduledTaskRow.thread_id == thread_id,
            )
            .order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [task for task in (self._to_domain_or_skip(row) for row in result.scalars()) if task is not None]

    async def save(self, task: ScheduledTask) -> ScheduledTask | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task.task_id)
            if row is None or row.user_id != task.user_id:
                return None
            self._apply(row, task)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._to_domain(row)

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def claim_due(self, *, now: datetime, lease_seconds: int, limit: int) -> list[ScheduledTask]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.next_run_at.is_not(None),
                ScheduledTaskRow.next_run_at <= now,
                or_(
                    and_(
                        ScheduledTaskRow.status == "enabled",
                        or_(
                            ScheduledTaskRow.lease_expires_at.is_(None),
                            ScheduledTaskRow.lease_expires_at < now,
                        ),
                    ),
                    # A task stuck in "running" with an expired lease means the
                    # claiming process died between claim and dispatch; it must
                    # stay reclaimable or the task is dead forever.
                    and_(
                        ScheduledTaskRow.status == "running",
                        ScheduledTaskRow.lease_expires_at.is_not(None),
                        ScheduledTaskRow.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(ScheduledTaskRow.next_run_at.asc(), ScheduledTaskRow.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = self._lease_owner
                row.lease_expires_at = lease_expires_at
                row.status = "running"
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return [task for task in (self._to_domain_or_skip(row) for row in rows) if task is not None]

    async def record_launch(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_run_id: str | None,
        last_thread_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
        protect_terminal: bool = False,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            if protect_terminal and TaskStatus(row.status) in TERMINAL_TASK_STATUSES:
                # A fast-failing run can reach the completion hook (which
                # finalizes a `once` task) before this launch-path write
                # commits; keep the hook's status/error and only record the
                # launch bookkeeping.
                pass
            else:
                row.status = str(status)
                row.last_error = last_error
            row.next_run_at = next_run_at
            row.last_run_at = last_run_at
            row.last_run_id = last_run_id
            row.last_thread_id = last_thread_id
            if increment_run_count:
                row.run_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def record_completion(
        self,
        task_id: str,
        *,
        user_id: str,
        status: TaskStatus | None,
        error: str | None,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return
            # Field-level on purpose: `record_launch` may commit on either side
            # of this write, and the two must not undo each other. Assigning
            # anything below `last_error` here is what reintroduces the race --
            # see the port docstring.
            row.last_error = error
            if status is not None:
                row.status = str(status)
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        """Reconcile `once` tasks orphaned in `running` by a process crash.

        A launched `once` task stays `running` until the in-process completion
        hook moves it to a terminal status; its lease was cleared at launch, so
        the claim query's expired-lease branch never sees it. After a crash the
        hook is gone and the task would be stuck forever. Tasks still holding a
        lease are left alone -- they were claimed but not launched, and
        expired-lease reclaim recovers them safely.
        """
        stmt = select(ScheduledTaskRow).where(
            ScheduledTaskRow.schedule_type == "once",
            ScheduledTaskRow.status == "running",
            ScheduledTaskRow.lease_expires_at.is_(None),
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            now = datetime.now(UTC)
            for row in rows:
                row.status = "cancelled"
                row.last_error = error
                row.updated_at = now
            await session.commit()
            return len(rows)
