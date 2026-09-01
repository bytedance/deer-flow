"""Tests for scheduler completion consistency fixes.

Bug 1: handle_run_completion crash between two transactions mislabels
        successful once-tasks as cancelled.
Bug 2: restart reconciliation (cancel_stuck_once_tasks and
        reconcile_stuck_once_tasks) was not outcome-aware.

These tests exercise the REAL repositories against file-backed SQLite so
that partial-unique-index and ORM constraints are enforced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


async def _init_db(tmp_path) -> tuple[ScheduledTaskRepository, ScheduledTaskRunRepository]:
    """Set up a fresh file-backed SQLite database and return both repos."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    return ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)


async def _create_once_task(
    task_repo: ScheduledTaskRepository,
    *,
    task_id: str = "task-once-1",
) -> dict:
    """Insert a once-type task (status set by the caller via ``_set_task_running``)."""
    return await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Once Task",
        prompt="do it",
        schedule_type="once",
        schedule_spec={"run_at": "2026-07-15T12:00:00Z"},
        timezone="UTC",
        next_run_at=None,
    )


async def _create_cron_task(
    task_repo: ScheduledTaskRepository,
    *,
    task_id: str = "task-cron-1",
) -> dict:
    """Insert a cron-type task."""
    now = _NOW
    return await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Cron Task",
        prompt="do it daily",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=now + timedelta(hours=1),
    )


async def _create_run(
    run_repo: ScheduledTaskRunRepository,
    *,
    run_id: str = "task-run-1",
    task_id: str = "task-once-1",
    status: str = "running",
    error: str | None = None,
    created_at: datetime | None = None,
    scheduled_for: datetime | None = None,
) -> dict:
    """Insert a scheduled_task_runs row."""
    now = created_at or _NOW
    run_row = await run_repo.create(
        run_record_id=run_id,
        task_id=task_id,
        thread_id="thread-1",
        scheduled_for=scheduled_for or now,
        trigger="scheduled",
        status=status,
    )
    # Explicitly set created_at so multi-history regressions exercise the
    # secondary recency key behind _fetch_latest_run. scheduled_for still
    # defaults to the logical occurrence time unless a test overrides it.
    if created_at is not None:
        async with run_repo._sf() as session:
            await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == run_id).values(created_at=created_at))
            await session.commit()
    return run_row


async def _set_task_running(task_repo: ScheduledTaskRepository, task_id: str) -> None:
    """Directly set a task to 'running' status (simulating post-launch state)."""
    sf = get_session_factory()
    assert sf is not None
    async with sf() as session:
        await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(status="running", lease_owner=None, lease_expires_at=None, updated_at=_NOW))
        await session.commit()


async def _get_task(task_repo: ScheduledTaskRepository, task_id: str) -> dict | None:
    """Read a task dict, bypassing user_id check for internal access."""
    return await task_repo.get_internal(task_id)


# ---------------------------------------------------------------------------
# Bug 1 & 2: cancel_stuck_once_tasks outcome-aware recovery
# ---------------------------------------------------------------------------


class TestCancelStuckOnceTasksOutcomeAware:
    """Verify that cancel_stuck_once_tasks respects terminal run statuses."""

    async def test_successful_run_reconciles_to_completed(self, tmp_path):
        """Crash after run committed 'success' but before parent update.

        cancel_stuck_once_tasks must mark the parent 'completed', not
        'cancelled'.
        """
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-success")
            await _set_task_running(task_repo, "task-success")

            # Run row is terminal success — the completion hook wrote it
            # but crashed before updating the parent task.
            await _create_run(run_repo, run_id="run-success", task_id="task-success", status="success")

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-success")
            assert task is not None
            assert task["status"] == "completed"
            assert task["last_error"] is None
        finally:
            await close_engine()

    async def test_failed_run_reconciles_to_failed_with_error(self, tmp_path):
        """Crash after run committed 'failed' but before parent update.

        cancel_stuck_once_tasks must mark the parent 'failed' and
        propagate the run's own error message.
        """
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-failed")
            await _set_task_running(task_repo, "task-failed")

            await _create_run(run_repo, run_id="run-failed", task_id="task-failed", status="failed")
            # Write the error on the run row.
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-failed").values(error="LLM rate limited"))
                await session.commit()

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-failed")
            assert task is not None
            assert task["status"] == "failed"
            assert task["last_error"] == "LLM rate limited"
        finally:
            await close_engine()

    async def test_interrupted_run_reconciles_to_cancelled_with_run_error(self, tmp_path):
        """Crash after run committed 'interrupted' but before parent update.

        cancel_stuck_once_tasks must mark the parent 'cancelled' and use
        the run's own error if present.
        """
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-interrupted")
            await _set_task_running(task_repo, "task-interrupted")

            await _create_run(run_repo, run_id="run-int", task_id="task-interrupted", status="interrupted")
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-int").values(error="user cancelled"))
                await session.commit()

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-interrupted")
            assert task is not None
            assert task["status"] == "cancelled"
            assert task["last_error"] == "user cancelled"
        finally:
            await close_engine()

    async def test_interrupted_run_without_error_uses_recovery_message(self, tmp_path):
        """Interrupted run with no error of its own should use the recovery error."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-int-norun")
            await _set_task_running(task_repo, "task-int-norun")

            await _create_run(run_repo, run_id="run-int2", task_id="task-int-norun", status="interrupted")

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-int-norun")
            assert task is not None
            assert task["status"] == "cancelled"
            assert task["last_error"] == "interrupted: gateway restarted"
        finally:
            await close_engine()

    async def test_no_run_row_preserves_original_cancel_behaviour(self, tmp_path):
        """No run row at all → generic cancel (active runs are left untouched)."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-norun")
            await _set_task_running(task_repo, "task-norun")

            # No run row created at all.
            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-norun")
            assert task is not None
            assert task["status"] == "cancelled"
            assert task["last_error"] == "interrupted: gateway restarted"
        finally:
            await close_engine()

    async def test_active_run_leaves_parent_unchanged(self, tmp_path):
        """An active (non-terminal) run row → parent left unchanged, not cancelled."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-active-run")
            await _set_task_running(task_repo, "task-active-run")

            await _create_run(run_repo, run_id="run-active", task_id="task-active-run", status="running")

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 0

            task = await _get_task(task_repo, "task-active-run")
            assert task is not None
            assert task["status"] == "running"
        finally:
            await close_engine()

    async def test_recurring_task_not_affected(self, tmp_path):
        """Recurring tasks with status='running' must not be touched."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_cron_task(task_repo, task_id="task-cron")

            # Manually set it to running (simulating an in-progress cron task).
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == "task-cron").values(status="running", lease_owner=None, lease_expires_at=None))
                await session.commit()

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            # cancel_stuck_once_tasks only selects schedule_type == "once".
            assert count == 0

            task = await _get_task(task_repo, "task-cron")
            assert task is not None
            assert task["status"] == "running"
        finally:
            await close_engine()

    async def test_leased_once_task_not_cancelled(self, tmp_path):
        """A once task still holding a lease is left alone."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-leased")

            # Set status=running but keep a future lease.
            sf = get_session_factory()
            assert sf is not None
            future = _NOW + timedelta(hours=1)
            async with sf() as session:
                await session.execute(
                    update(ScheduledTaskRow)
                    .where(ScheduledTaskRow.id == "task-leased")
                    .values(
                        status="running",
                        lease_owner="worker-1",
                        lease_expires_at=future,
                    )
                )
                await session.commit()

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 0

            task = await _get_task(task_repo, "task-leased")
            assert task is not None
            assert task["status"] == "running"
        finally:
            await close_engine()

    async def test_multiple_stuck_tasks_mixed_outcomes(self, tmp_path):
        """Multiple stuck tasks with different run statuses are reconciled correctly."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            # Task 1: successful run
            await _create_once_task(task_repo, task_id="task-mixed-1")
            await _set_task_running(task_repo, "task-mixed-1")
            await _create_run(run_repo, run_id="run-m1", task_id="task-mixed-1", status="success")

            # Task 2: failed run with error
            await _create_once_task(task_repo, task_id="task-mixed-2")
            await _set_task_running(task_repo, "task-mixed-2")
            await _create_run(run_repo, run_id="run-m2", task_id="task-mixed-2", status="failed")
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-m2").values(error="timeout"))
                await session.commit()

            # Task 3: no run row
            await _create_once_task(task_repo, task_id="task-mixed-3")
            await _set_task_running(task_repo, "task-mixed-3")

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 3

            t1 = await _get_task(task_repo, "task-mixed-1")
            assert t1["status"] == "completed"
            assert t1["last_error"] is None

            t2 = await _get_task(task_repo, "task-mixed-2")
            assert t2["status"] == "failed"
            assert t2["last_error"] == "timeout"

            t3 = await _get_task(task_repo, "task-mixed-3")
            assert t3["status"] == "cancelled"
            assert t3["last_error"] == "interrupted: gateway restarted"
        finally:
            await close_engine()

    async def test_cancel_sees_run_committed_before_finalize(self, tmp_path):
        """Monkeypatch _fetch_latest_run to simulate the race: a completion
        commits success after recovery has observed the stale 'running' state.

        The test proves the post-lock fresh read picks up the committed success.
        A reverted pre-lock batch implementation never calls _fetch_latest_run,
        so the monkeypatch never fires and the test fails — catching the regression.
        """
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-cancel-race")
            await _set_task_running(task_repo, "task-cancel-race")
            await _create_run(run_repo, run_id="run-crace", task_id="task-cancel-race", status="running")

            original_fetch = ScheduledTaskRepository._fetch_latest_run
            fresh_sf = get_session_factory()
            assert fresh_sf is not None
            intercepted = False

            async def _intercepted_fetch(session, task_id: str):
                nonlocal intercepted
                if not intercepted and task_id == "task-cancel-race":
                    intercepted = True
                    # Concurrent completion commits success in a separate session.
                    async with fresh_sf() as cs:
                        await cs.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-crace").values(status="success"))
                        await cs.commit()
                    # Fresh read with populate_existing — production code's guarantee.
                    return await original_fetch(session, task_id)
                return await original_fetch(session, task_id)

            ScheduledTaskRepository._fetch_latest_run = staticmethod(_intercepted_fetch)
            try:
                count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
                assert count == 1
                task = await _get_task(task_repo, "task-cancel-race")
                assert task is not None
                assert task["status"] == "completed"
                assert task["last_error"] is None
            finally:
                ScheduledTaskRepository._fetch_latest_run = staticmethod(original_fetch)
        finally:
            await close_engine()


# ---------------------------------------------------------------------------
# Bug 1 & 2: reconcile_stuck_once_tasks (multi-instance path)
# ---------------------------------------------------------------------------


class TestReconcileStuckOnceTasksOutcomeAware:
    """Verify the multi-instance path is also outcome-aware."""

    async def test_successful_run_reconciles_to_completed(self, tmp_path):
        """reconcile_stuck_once_tasks with terminal success run → completed."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-recon-success")
            await _set_task_running(task_repo, "task-recon-success")

            await _create_run(run_repo, run_id="run-rs1", task_id="task-recon-success", status="success")

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-recon-success")
            assert task is not None
            assert task["status"] == "completed"
            assert task["last_error"] is None
        finally:
            await close_engine()

    async def test_failed_run_reconciles_to_failed(self, tmp_path):
        """reconcile_stuck_once_tasks with terminal failed run → failed."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-recon-failed")
            await _set_task_running(task_repo, "task-recon-failed")

            await _create_run(run_repo, run_id="run-rf1", task_id="task-recon-failed", status="failed")
            sf = get_session_factory()
            assert sf is not None
            async with sf() as session:
                await session.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-rf1").values(error="agent crashed"))
                await session.commit()

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-recon-failed")
            assert task is not None
            assert task["status"] == "failed"
            assert task["last_error"] == "agent crashed"
        finally:
            await close_engine()

    async def test_no_terminal_run_gets_generic_cancel(self, tmp_path):
        """reconcile_stuck_once_tasks with no terminal run → cancelled."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-recon-noterm")
            await _set_task_running(task_repo, "task-recon-noterm")

            # No run row at all.
            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-recon-noterm")
            assert task is not None
            assert task["status"] == "cancelled"
            assert task["last_error"] == "interrupted: lease expired"
        finally:
            await close_engine()

    async def test_reconcile_sees_run_committed_before_finalize(self, tmp_path):
        """Monkeypatch _fetch_latest_run to simulate the race: a completion
        commits success after recovery has observed the stale 'running' state.

        The test proves the post-lock fresh read picks up the committed success.
        A reverted pre-lock batch implementation never calls _fetch_latest_run,
        so the monkeypatch never fires and the test fails — catching the regression.
        """
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-recon-race")
            await _set_task_running(task_repo, "task-recon-race")
            await _create_run(run_repo, run_id="run-rrace", task_id="task-recon-race", status="running")

            original_fetch = ScheduledTaskRepository._fetch_latest_run
            fresh_sf = get_session_factory()
            assert fresh_sf is not None
            intercepted = False

            async def _intercepted_fetch(session, task_id: str):
                nonlocal intercepted
                if not intercepted and task_id == "task-recon-race":
                    intercepted = True
                    async with fresh_sf() as cs:
                        await cs.execute(update(ScheduledTaskRunRow).where(ScheduledTaskRunRow.id == "run-rrace").values(status="success"))
                        await cs.commit()
                    return await original_fetch(session, task_id)
                return await original_fetch(session, task_id)

            ScheduledTaskRepository._fetch_latest_run = staticmethod(_intercepted_fetch)
            try:
                count = await task_repo.reconcile_stuck_once_tasks(
                    error="interrupted: lease expired",
                    now=_NOW,
                    lease_grace_seconds=10,
                )
                assert count == 1
                task = await _get_task(task_repo, "task-recon-race")
                assert task is not None
                assert task["status"] == "completed"
                assert task["last_error"] is None
            finally:
                ScheduledTaskRepository._fetch_latest_run = staticmethod(original_fetch)
        finally:
            await close_engine()


# ---------------------------------------------------------------------------
# Regression: multiple historical runs for both reconciliation paths
# ---------------------------------------------------------------------------


class TestCancelStuckMultipleRuns:
    """Regression: cancel_stuck_once_tasks with multiple historical runs.

    Ensures the latest run row is used for finalisation, not an older one.
    """

    async def test_older_success_newer_skipped_marks_cancelled(self, tmp_path):
        """Older success + newer skipped → task should be cancelled (not completed)."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-cs")
            await _set_task_running(task_repo, "task-multi-cs")

            # Older run succeeded.
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-cs",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
            )
            # Newer run was skipped — the latest run determines the outcome.
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-cs",
                status="skipped",
                created_at=_NOW,
            )

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-multi-cs")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_newer_created_at_with_earlier_scheduled_for_wins(self, tmp_path):
        """Newer created_at + earlier scheduled_for → latest run should still win."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-cs-skew")
            await _set_task_running(task_repo, "task-multi-cs-skew")

            await _create_run(
                run_repo,
                run_id="run-old-scheduled-late",
                task_id="task-multi-cs-skew",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
                scheduled_for=_NOW + timedelta(minutes=5),
            )
            await _create_run(
                run_repo,
                run_id="run-new-scheduled-early",
                task_id="task-multi-cs-skew",
                status="skipped",
                created_at=_NOW,
                scheduled_for=_NOW - timedelta(minutes=5),
            )

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-multi-cs-skew")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_same_scheduled_for_uses_created_at_recency_tie_break(self, tmp_path):
        """Same scheduled_for + newer created_at skipped → task should be cancelled."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-cs-tie")
            await _set_task_running(task_repo, "task-multi-cs-tie")

            same_scheduled_for = _NOW
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-cs-tie",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
                scheduled_for=same_scheduled_for,
            )
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-cs-tie",
                status="skipped",
                created_at=_NOW,
                scheduled_for=same_scheduled_for,
            )

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 1

            task = await _get_task(task_repo, "task-multi-cs-tie")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_older_success_newer_active_leaves_parent_unchanged(self, tmp_path):
        """Older success + newer running → latest run is active, parent left unchanged (not cancelled)."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-ca")
            await _set_task_running(task_repo, "task-multi-ca")

            # Older run succeeded.
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-ca",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
            )
            # Newer run is still running — active occurrence left untouched.
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-ca",
                status="running",
                created_at=_NOW,
            )

            count = await task_repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
            assert count == 0

            task = await _get_task(task_repo, "task-multi-ca")
            assert task is not None
            assert task["status"] == "running"
        finally:
            await close_engine()


class TestReconcileStuckMultipleRuns:
    """Regression: reconcile_stuck_once_tasks with multiple historical runs.

    Ensures the latest run row is used for finalisation, not an older one.
    """

    async def test_same_scheduled_for_uses_created_at_recency_tie_break(self, tmp_path):
        """Same scheduled_for + newer created_at skipped → task should be cancelled."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-rs-tie")
            await _set_task_running(task_repo, "task-multi-rs-tie")

            same_scheduled_for = _NOW
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-rs-tie",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
                scheduled_for=same_scheduled_for,
            )
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-rs-tie",
                status="skipped",
                created_at=_NOW,
                scheduled_for=same_scheduled_for,
            )

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-multi-rs-tie")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_newer_created_at_with_earlier_scheduled_for_wins(self, tmp_path):
        """Newer created_at + earlier scheduled_for → latest run should still win."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-rs-skew")
            await _set_task_running(task_repo, "task-multi-rs-skew")

            await _create_run(
                run_repo,
                run_id="run-old-scheduled-late",
                task_id="task-multi-rs-skew",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
                scheduled_for=_NOW + timedelta(minutes=5),
            )
            await _create_run(
                run_repo,
                run_id="run-new-scheduled-early",
                task_id="task-multi-rs-skew",
                status="skipped",
                created_at=_NOW,
                scheduled_for=_NOW - timedelta(minutes=5),
            )

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-multi-rs-skew")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_older_success_newer_skipped_marks_cancelled(self, tmp_path):
        """Older success + newer skipped → task should be cancelled (not completed)."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-rs")
            await _set_task_running(task_repo, "task-multi-rs")

            # Older run succeeded.
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-rs",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
            )
            # Newer run was skipped.
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-rs",
                status="skipped",
                created_at=_NOW,
            )

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 1

            task = await _get_task(task_repo, "task-multi-rs")
            assert task is not None
            assert task["status"] == "cancelled"
        finally:
            await close_engine()

    async def test_older_success_newer_active_leaves_parent_unchanged(self, tmp_path):
        """Older success + newer running → latest run is active, parent left unchanged (not cancelled)."""
        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-multi-ra")
            await _set_task_running(task_repo, "task-multi-ra")

            # Older run succeeded.
            await _create_run(
                run_repo,
                run_id="run-old",
                task_id="task-multi-ra",
                status="success",
                created_at=_NOW - timedelta(minutes=5),
            )
            # Newer run is still running — not terminal, so parent left unchanged.
            await _create_run(
                run_repo,
                run_id="run-new",
                task_id="task-multi-ra",
                status="running",
                created_at=_NOW,
            )

            count = await task_repo.reconcile_stuck_once_tasks(
                error="interrupted: lease expired",
                now=_NOW,
                lease_grace_seconds=10,
            )
            assert count == 0

            task = await _get_task(task_repo, "task-multi-ra")
            assert task is not None
            assert task["status"] == "running"
        finally:
            await close_engine()


# ---------------------------------------------------------------------------
# handle_run_completion happy path (Bug 1 guard)
# ---------------------------------------------------------------------------


class TestHandleRunCompletionHappyPath:
    """Ensure handle_run_completion correctly finalises a once task on success."""

    async def test_success_completes_once_task(self, tmp_path):
        """Call the real handle_run_completion and verify the once task transitions to completed."""

        task_repo, run_repo = await _init_db(tmp_path)
        try:
            await _create_once_task(task_repo, task_id="task-completion")
            await _set_task_running(task_repo, "task-completion")

            # The run row is in 'running' — simulating the state just before
            # the completion hook fires.
            await _create_run(run_repo, run_id="run-comp", task_id="task-completion", status="running")

            service = ScheduledTaskService(
                task_repo=task_repo,
                task_run_repo=run_repo,
                launch_run=lambda **_kw: None,
                poll_interval_seconds=5,
                lease_seconds=120,
                max_concurrent_runs=3,
            )

            record = RunRecord(
                run_id="run-comp",
                thread_id="thread-1",
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.continue_,
                metadata={
                    "scheduled_task_id": "task-completion",
                    "scheduled_task_run_id": "run-comp",
                },
                user_id="user-1",
            )

            await service.handle_run_completion(record)

            task = await _get_task(task_repo, "task-completion")
            assert task is not None
            assert task["status"] == "completed"
            assert task["last_error"] is None
        finally:
            await close_engine()
