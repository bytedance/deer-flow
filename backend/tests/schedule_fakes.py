"""Shared zero-IO doubles for the schedule context.

Lives in its own module rather than inside a test file so the port contract
suite and the service tests can both import it as an ordinary module, without
relying on the tests directory happening to be on ``sys.path``.

**Concurrency is explicitly out of scope.** These doubles model the
single-threaded semantics of each port -- which rows `claim_due` selects, that
`add` refuses a second active run -- and provide no atomicity whatsoever. A
green run here says nothing about two dispatchers racing; that is covered
against a real database in ``test_scheduled_task_dispatch_race.py``. Do not
read a passing contract suite as licence to run more than one scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from deerflow.domain.schedule.model import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    TERMINAL_TASK_STATUSES,
    ActiveRunConflictError,
    RunStatus,
    ScheduledRun,
    ScheduledTask,
    ScheduleType,
    TaskStatus,
)
from deerflow.domain.schedule.ports import LaunchedRun


@dataclass
class _TaskRow:
    """One stored task: the aggregate plus the columns the domain has no
    business knowing about.

    The lease lives here rather than on ``ScheduledTask`` for the same reason
    it lives in the table and not in the domain -- it is a storage-level
    concurrency control, not a business fact about the task.
    """

    task: ScheduledTask
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None


class InMemoryScheduledTaskRepository:
    """ScheduledTaskRepository double backed by a dict."""

    def __init__(self) -> None:
        self._rows: dict[str, _TaskRow] = {}

    # -- inspection helpers (tests only, not part of the port) -----------

    def lease_of(self, task_id: str) -> tuple[str | None, datetime | None]:
        row = self._rows[task_id]
        return row.lease_owner, row.lease_expires_at

    def seed(self, task: ScheduledTask, *, lease_owner: str | None = None, lease_expires_at: datetime | None = None) -> ScheduledTask:
        """Install a task directly, optionally already claimed."""
        self._rows[task.task_id] = _TaskRow(task=task, lease_owner=lease_owner, lease_expires_at=lease_expires_at)
        return task

    # -- port ------------------------------------------------------------

    async def add(self, task: ScheduledTask) -> ScheduledTask:
        self._rows[task.task_id] = _TaskRow(task=task)
        return task

    async def get(self, task_id: str, *, user_id: str) -> ScheduledTask | None:
        row = self._rows.get(task_id)
        if row is None or row.task.user_id != user_id:
            return None
        return row.task

    async def list_by_user(self, user_id: str) -> list[ScheduledTask]:
        rows = [row.task for row in self._rows.values() if row.task.user_id == user_id]
        return sorted(rows, key=lambda t: (t.created_at, t.task_id), reverse=True)

    async def list_by_user_and_thread(self, user_id: str, thread_id: str) -> list[ScheduledTask]:
        tasks = await self.list_by_user(user_id)
        return [task for task in tasks if task.thread_id == thread_id]

    async def save(self, task: ScheduledTask) -> ScheduledTask | None:
        row = self._rows.get(task.task_id)
        if row is None or row.task.user_id != task.user_id:
            return None
        row.task = task
        return task

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        row = self._rows.get(task_id)
        if row is None or row.task.user_id != user_id:
            return False
        del self._rows[task_id]
        return True

    async def claim_due(self, *, now: datetime, lease_seconds: int, limit: int) -> list[ScheduledTask]:
        def claimable(row: _TaskRow) -> bool:
            task = row.task
            if task.next_run_at is None or task.next_run_at > now:
                return False
            expired = row.lease_expires_at is not None and row.lease_expires_at < now
            if task.status is TaskStatus.ENABLED:
                return row.lease_expires_at is None or expired
            # Stuck mid-dispatch: the claimer died between claim and launch.
            return task.status is TaskStatus.RUNNING and expired

        due = sorted(
            (row for row in self._rows.values() if claimable(row)),
            key=lambda row: (row.task.next_run_at, row.task.task_id),
        )[:limit]

        claimed = []
        for row in due:
            # Stands in for whatever identity a real adapter records.
            row.lease_owner = "fake-worker"
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.task = replace(row.task, status=TaskStatus.RUNNING)
            claimed.append(row.task)
        return claimed

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
        row = self._rows.get(task_id)
        if row is None:
            return
        task = row.task
        if not (protect_terminal and task.status in TERMINAL_TASK_STATUSES):
            task = replace(task, status=status, last_error=last_error)
        task = replace(
            task,
            next_run_at=next_run_at,
            last_run_at=last_run_at,
            last_run_id=last_run_id,
            last_thread_id=last_thread_id,
        )
        if increment_run_count:
            task = replace(task, run_count=task.run_count + 1)
        row.task = task
        row.lease_owner = None
        row.lease_expires_at = None

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        cancelled = 0
        for row in self._rows.values():
            stuck = row.task.status is TaskStatus.RUNNING and row.task.schedule.schedule_type is ScheduleType.ONCE and row.lease_expires_at is None
            if stuck:
                row.task = replace(row.task, status=TaskStatus.CANCELLED, last_error=error)
                cancelled += 1
        return cancelled


class InMemoryScheduledRunRepository:
    """ScheduledRunRepository double that also models the active-slot rule.

    ``add`` refusing a second active record for one task is not an
    implementation detail to be skipped here: the service collapses that
    rejection to the same outcome as its own fast path, and a double that never
    raises would let that collapse go untested.
    """

    def __init__(self) -> None:
        self._rows: dict[str, ScheduledRun] = {}

    def all_runs(self) -> list[ScheduledRun]:
        """Inspection helper (tests only, not part of the port)."""
        return list(self._rows.values())

    async def add(self, run: ScheduledRun) -> ScheduledRun:
        if run.is_active and any(other.task_id == run.task_id and other.is_active for other in self._rows.values()):
            raise ActiveRunConflictError(f"scheduled task {run.task_id!r} already has an active run")
        self._rows[run.record_id] = run
        return run

    async def list_by_task(self, task_id: str, *, limit: int = 50, offset: int = 0) -> list[ScheduledRun]:
        rows = [run for run in self._rows.values() if run.task_id == task_id]
        rows.sort(key=lambda run: (run.created_at, run.record_id), reverse=True)
        return rows[offset : offset + limit]

    async def count_active(self) -> int:
        return sum(1 for run in self._rows.values() if run.is_active)

    async def has_active(self, task_id: str) -> bool:
        return any(run.task_id == task_id and run.is_active for run in self._rows.values())

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
        run = self._rows.get(record_id)
        if run is None:
            return
        if protect_terminal and run.status in TERMINAL_RUN_STATUSES:
            # Keep the terminal verdict; only backfill what it could not know.
            if run.run_id is None and run_id is not None:
                run = replace(run, run_id=run_id)
            if run.started_at is None and started_at is not None:
                run = replace(run, started_at=started_at)
            self._rows[record_id] = run
            return
        run = replace(run, status=status, run_id=run_id, error=error)
        if started_at is not None:
            run = replace(run, started_at=started_at)
        if finished_at is not None:
            run = replace(run, finished_at=finished_at)
        self._rows[record_id] = run

    async def mark_stale_active(self, *, error: str) -> int:
        stale = [run for run in self._rows.values() if run.status in ACTIVE_RUN_STATUSES]
        for run in stale:
            self._rows[run.record_id] = replace(run, status=RunStatus.INTERRUPTED, error=error)
        return len(stale)


@dataclass
class FakeRunLauncher:
    """RunLauncher double.

    `fail_with` makes every launch raise instead -- set it to a ThreadBusyError
    or a LaunchFailedError to drive the two branches the domain distinguishes.
    """

    fail_with: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    async def launch(
        self,
        *,
        thread_id: str,
        assistant_id: str | None,
        prompt: str,
        owner_user_id: str | None,
        metadata: dict[str, str],
    ) -> LaunchedRun:
        self.calls.append(
            {
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                "prompt": prompt,
                "owner_user_id": owner_user_id,
                "metadata": metadata,
            }
        )
        if self.fail_with is not None:
            raise self.fail_with
        return LaunchedRun(run_id=f"run-{len(self.calls)}", thread_id=thread_id)


class FakeThreadLookup:
    """ThreadLookup double backed by a thread_id -> owner mapping."""

    def __init__(self, threads: dict[str, str] | None = None) -> None:
        self._threads = dict(threads or {})

    async def exists_for_user(self, thread_id: str, user_id: str) -> bool:
        return self._threads.get(thread_id) == user_id
