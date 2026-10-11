import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.scheduler.service import ScheduledTaskService
from deerflow.runtime import ConflictError, RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode


class DummyTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False
        self.updated = None
        self.completions = []
        self.release_calls = []
        self.cancelled_stuck_once = None
        self.reconciled_stuck_once = None

    async def cancel_stuck_once_tasks(self, *, error):
        self.cancelled_stuck_once = error
        return 0

    async def reconcile_stuck_once_tasks(self, **kwargs):
        self.reconciled_stuck_once = kwargs
        return 0

    async def claim_dispatch_lease(self, task_id, **_kwargs):
        return next((dict(row) for row in self.rows if row["id"] == task_id), None)

    async def release_queued_admission_lease(self, task_id):
        return False

    async def release_dispatch_lease(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        return True

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def update_after_launch(self, *args, **kwargs):
        self.updated = (args, kwargs)

    async def complete_run(self, task_id, **kwargs):
        self.completions.append((task_id, kwargs))
        return True

    async def get(self, task_id: str, *, user_id: str):
        row = next((item for item in self.rows if item["id"] == task_id and item["user_id"] == user_id), None)
        return dict(row) if row is not None else None

    async def get_internal(self, task_id: str):
        row = next((item for item in self.rows if item["id"] == task_id), None)
        return dict(row) if row is not None else None

    async def update(self, task_id: str, *, user_id: str, updates):
        row = next((item for item in self.rows if item["id"] == task_id and item["user_id"] == user_id), None)
        if row is None:
            return None
        row.update(updates)
        return dict(row)


class DummyRunRepo:
    def __init__(self, *, active=False, active_count=0):
        self.created = None
        self.updated = []
        self.active = active
        self.active_count = active_count
        self.stale_marked = None
        self.reconciled = None
        self.reconcile_count = 0

    async def count_active_runs(self):
        return self.active_count

    async def list_queued_runs(self, *, limit, **_kwargs):
        return []

    async def expire_queued_runs(self, **_kwargs):
        return []

    async def recover_expired_launch_claims(self, **_kwargs):
        return 0

    async def get_active_run(self, task_id):
        if not self.active:
            return None
        return {
            "id": "task-run-active",
            "task_id": task_id,
            "thread_id": "thread-active",
            "status": "running",
        }

    async def claim_queued_run(self, run_record_id, *, global_max_concurrent_runs, **_kwargs):
        if self.active_count >= global_max_concurrent_runs:
            return None
        return {"id": run_record_id, "status": "launching"}

    async def requeue_claimed_run(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, {"status": "queued", **kwargs}))
        return True

    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, kwargs))
        return True

    async def reconcile_launched_run(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, {"reconciled": True, **kwargs}))
        return True

    async def fail_launching_run(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, {"status": "failed", **kwargs}))
        return True

    async def has_active_runs(self, task_id):
        return self.active

    async def mark_stale_active_runs(self, *, error):
        self.stale_marked = error
        return 0

    async def reconcile_active_runs(self, **kwargs):
        self.reconcile_count += 1
        self.reconciled = kwargs
        return 0


@pytest.mark.asyncio
async def test_service_claims_and_dispatches_due_task():
    async def fake_launch(**kwargs):
        assert kwargs["owner_user_id"] == "user-1"
        assert kwargs["metadata"]["scheduled_task_id"] == "task-1"
        assert kwargs["metadata"]["scheduled_trigger"] == "scheduled"
        return {"run_id": "run-1", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-1",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "once",
                "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
                "timezone": "UTC",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert run_repo.created["task_id"] == "task-1"
    assert run_repo.updated[0][1]["status"] == "running"
    assert run_repo.updated[0][1]["protect_terminal"] is True
    # `once` terminal status is owned by handle_run_completion, not the launch.
    assert task_repo.updated[1]["status"] == "running"


@pytest.mark.asyncio
async def test_manual_trigger_keeps_paused_cron_task_paused():
    async def fake_launch(**kwargs):
        return {"run_id": "run-2", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-2",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "paused",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="manual",
    )

    assert task_repo.updated[1]["status"] == "paused"


@pytest.mark.asyncio
async def test_fresh_thread_per_run_creates_new_execution_thread():
    async def fake_launch(**kwargs):
        assert kwargs["thread_id"] != "thread-template"
        return {"run_id": "run-3", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-3",
                "user_id": "user-1",
                "thread_id": "thread-template",
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="scheduled",
    )

    assert run_repo.created["thread_id"] != "thread-template"
    assert task_repo.updated[1]["last_thread_id"] == run_repo.created["thread_id"]


@pytest.mark.asyncio
async def test_scheduled_overlap_conflict_is_kept_in_queue():
    async def fake_launch(**_kwargs):
        raise ConflictError("Thread thread-1 already has an active run")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-4",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "running",
                "overlap_policy": "enqueue",
                "last_run_id": "run-old",
                "last_thread_id": "thread-1",
                "last_run_at": "2026-07-01T00:00:00+00:00",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="scheduled",
    )

    assert result["outcome"] == "queued"
    assert run_repo.created["status"] == "queued"
    assert run_repo.updated[-1][1]["status"] == "queued"
    assert task_repo.updated is None


@pytest.mark.asyncio
async def test_manual_overlap_conflict_is_kept_in_queue():
    async def fake_launch(**_kwargs):
        raise ConflictError("Thread thread-1 already has an active run")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-5",
                "user_id": "user-1",
                "thread_id": "thread-1",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
                "overlap_policy": "enqueue",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="manual",
    )

    assert result["outcome"] == "queued"
    assert run_repo.updated[-1][1]["status"] == "queued"
    assert task_repo.release_calls == []


@pytest.mark.asyncio
async def test_dispatch_task_records_failure_for_legacy_invalid_thread_id():
    """Rows persisted before the thread-id contract was centralized may store
    IDs that fail the canonical pattern (dots, >64 chars). Dispatch must record
    the failure through normal bookkeeping instead of raising — an uncaught
    ValueError surfaces as HTTP 500 on manual trigger and, in the poller,
    aborts the rest of the claimed batch every cycle."""

    async def fake_launch(**_kwargs):
        raise AssertionError("launch_run must not be called for an invalid thread_id")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-legacy",
                "user_id": "user-1",
                "thread_id": "thread.with.dot",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(
        task_repo.rows[0],
        now=datetime.now(UTC),
        trigger="scheduled",
    )

    assert result["outcome"] == "failed"
    assert result["task_run_id"] is None
    assert result["run_id"] is None
    assert "Invalid thread_id" in result["error"]
    assert run_repo.created is None
    assert task_repo.updated[1]["last_error"] == result["error"]
    assert task_repo.updated[1]["last_thread_id"] == "thread.with.dot"
    assert task_repo.updated[1]["increment_run_count"] is False


@pytest.mark.asyncio
async def test_run_once_continues_batch_after_invalid_thread_id():
    """A poison legacy row must not prevent later claimed tasks from dispatching."""
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-ok", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-legacy",
                "user_id": "user-1",
                "thread_id": "thread.with.dot",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            },
            {
                "id": "task-valid",
                "user_id": "user-1",
                "thread_id": "thread-ok",
                "context_mode": "reuse_thread",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            },
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.run_once(now=datetime.now(UTC))

    assert len(launched) == 1
    assert launched[0]["thread_id"] == "thread-ok"


@pytest.mark.asyncio
async def test_handle_run_completion_uses_atomic_repository_boundary():
    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-6",
                "user_id": "user-1",
                "thread_id": None,
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "0 9 * * *"},
                "timezone": "UTC",
                "status": "enabled",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    record = RunRecord(
        run_id="run-6",
        thread_id="thread-6",
        assistant_id="lead_agent",
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        metadata={
            "scheduled_task_id": "task-6",
            "scheduled_task_run_id": "task-run-6",
        },
        user_id="user-1",
    )

    await service.handle_run_completion(record)

    assert len(task_repo.completions) == 1
    task_id, completion = task_repo.completions[0]
    assert task_id == "task-6"
    assert completion["user_id"] == "user-1"
    assert completion["task_run_id"] == "task-run-6"
    assert completion["run_id"] == "run-6"
    assert completion["status"] == "success"
    assert completion["error"] is None
    assert completion["finished_at"].tzinfo == UTC
    assert run_repo.updated == []


def _make_service(task_repo, run_repo):
    return ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )


def _once_task_row(task_id="task-once", status="running"):
    return {
        "id": task_id,
        "user_id": "user-1",
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "title": "Once summary",
        "prompt": "Summarize thread",
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
        "timezone": "UTC",
        "status": status,
    }


def _completion_record(status, *, task_id="task-once", error=None, trigger="scheduled"):
    return RunRecord(
        run_id="run-x",
        thread_id="thread-x",
        assistant_id="lead_agent",
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata={
            "scheduled_task_id": task_id,
            "scheduled_task_run_id": "task-run-x",
            "scheduled_trigger": trigger,
        },
        user_id="user-1",
        error=error,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_status", "error", "occurrence_status", "expected_error"),
    [
        (RunStatus.success, None, "success", None),
        (RunStatus.error, "boom", "failed", "boom"),
        (RunStatus.timeout, "time limit", "failed", "time limit"),
        (RunStatus.interrupted, None, "interrupted", "run was interrupted before completion"),
        (RunStatus.interrupted, "cancelled by user", "interrupted", "cancelled by user"),
    ],
)
async def test_handle_run_completion_forwards_terminal_outcome(run_status, error, occurrence_status, expected_error):
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(run_status, error=error))

    assert len(task_repo.completions) == 1
    task_id, completion = task_repo.completions[0]
    assert task_id == "task-once"
    assert completion["status"] == occurrence_status
    assert completion["error"] == expected_error
    assert run_repo.updated == []


@pytest.mark.asyncio
async def test_existing_running_occurrence_blocks_duplicate_fresh_thread_run():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-9", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-9")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "running", "overlap_policy": "enqueue"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo(active=True)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="scheduled")

    assert result["outcome"] == "conflict"
    assert launched == []
    assert run_repo.created is None


@pytest.mark.asyncio
async def test_startup_sweep_reconciles_stale_runs_and_stuck_once_tasks():
    task_repo = DummyTaskRepo([])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.start()
    await service.stop()

    assert run_repo.stale_marked is not None
    assert task_repo.cancelled_stuck_once == run_repo.stale_marked


@pytest.mark.parametrize("failure_stage", ["occurrence", "parent"])
@pytest.mark.asyncio
async def test_single_instance_start_fails_closed_before_polling(failure_stage):
    order = []

    class StartupTaskRepo(DummyTaskRepo):
        def __init__(self):
            super().__init__([])
            self.recovery_attempts = 0

        async def cancel_stuck_once_tasks(self, *, error):
            self.recovery_attempts += 1
            order.append("parent")
            assert service._task is None
            if failure_stage == "parent" and self.recovery_attempts == 1:
                raise RuntimeError("simulated parent recovery failure")
            return await super().cancel_stuck_once_tasks(error=error)

    class StartupRunRepo(DummyRunRepo):
        def __init__(self):
            super().__init__()
            self.recovery_attempts = 0

        async def mark_stale_active_runs(self, *, error):
            self.recovery_attempts += 1
            order.append("occurrence")
            assert service._task is None
            if failure_stage == "occurrence" and self.recovery_attempts == 1:
                raise RuntimeError("simulated occurrence recovery failure")
            return await super().mark_stale_active_runs(error=error)

    task_repo = StartupTaskRepo()
    run_repo = StartupRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=0,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    async def parked_run_loop():
        await service._stop.wait()

    service._run_loop = parked_run_loop
    try:
        with pytest.raises(RuntimeError, match=f"simulated {failure_stage} recovery failure"):
            await service.start()
        assert run_repo.recovery_attempts == 1
        assert task_repo.recovery_attempts == (0 if failure_stage == "occurrence" else 1)
        assert order == (["occurrence"] if failure_stage == "occurrence" else ["occurrence", "parent"])
        assert service._task is None
        assert task_repo.claimed is False
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_multi_instance_start_uses_lease_aware_reconciliation():
    task_repo = DummyTaskRepo([])
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=lambda **_kwargs: None,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
        multi_instance=True,
        run_lease_grace_seconds=17,
    )

    await service.start()
    await asyncio.sleep(0)
    await service.stop()

    assert run_repo.reconcile_count == 1
    assert run_repo.reconciled is not None
    assert run_repo.reconciled["lease_grace_seconds"] == 17
    assert task_repo.reconciled_stuck_once is not None
    assert task_repo.reconciled_stuck_once["lease_grace_seconds"] == 17
    assert task_repo.cancelled_stuck_once is None


@pytest.mark.asyncio
async def test_manual_trigger_with_active_run_returns_conflict_without_launching():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-x", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-manual-busy")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "enabled", "overlap_policy": "enqueue"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo(active=True)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "conflict"
    assert launched == []
    # Nothing was scheduled to happen, so no run-history row is recorded.
    assert run_repo.created is None
    assert result["task_run_id"] is None


@pytest.mark.asyncio
async def test_run_once_admits_due_occurrences_independently_of_execution_budget():
    claim_limits = []

    class BudgetTaskRepo(DummyTaskRepo):
        async def claim_due_tasks(self, **kwargs):
            claim_limits.append(kwargs["limit"])
            return []

    task_repo = BudgetTaskRepo([])
    run_repo = DummyRunRepo(active_count=2)
    service = _make_service(task_repo, run_repo)

    await service.run_once(now=datetime.now(UTC))
    assert claim_limits == [3]

    run_repo.active_count = 3
    await service.run_once(now=datetime.now(UTC))
    assert claim_limits == [3, 3]


@pytest.mark.asyncio
async def test_launch_bookkeeping_passes_protect_terminal():
    async def fake_launch(**kwargs):
        return {"run_id": "run-pt", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo([_once_task_row(task_id="task-pt", status="enabled")])
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.dispatch_task(task_repo.rows[0], now=datetime.now(UTC), trigger="scheduled")

    assert task_repo.updated[1]["protect_terminal"] is True


class _StatefulRunRepo:
    """Stateful fake ``ScheduledTaskRunRepository`` for the #4452 tests.

    Mirrors just enough of the real repository to let a second dispatch
    observe the active slot held by the first:

      * ``create()`` tracks each row by id, carrying its ``status`` and
        ``run_id``;
      * with ``fail_first_update=True`` the very FIRST ``update_status()``
        call raises, simulating a transient DB failure on the
        ``queued -> running`` write that fires right after ``_launch_run``
        returns a live ``run_id``; every later ``update_status()`` applies;
      * ``has_active_runs()`` reflects whether any tracked row for the task
        is still in an active status (``queued``/``running``), exactly like
        the partial unique index ``uq_scheduled_task_run_active``.
    """

    _ACTIVE = {"queued", "launching", "running"}

    def __init__(self, *, fail_first_update: bool = False, fail_updates: int = 0) -> None:
        self.created: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.rows: dict[str, dict] = {}
        self._fail_updates = max(fail_updates, 1 if fail_first_update else 0)
        self._updates_raised = 0

    async def count_active_runs(self) -> int:
        return sum(1 for row in self.rows.values() if row["status"] in {"launching", "running"})

    async def list_queued_runs(self, *, limit: int, **_kwargs) -> list[dict]:
        return []

    async def expire_queued_runs(self, **_kwargs) -> list[dict]:
        return []

    async def create(self, **kwargs) -> dict:
        self.created.append(kwargs)
        self.rows[kwargs["run_record_id"]] = {
            "id": kwargs["run_record_id"],
            "task_id": kwargs["task_id"],
            "thread_id": kwargs["thread_id"],
            "trigger": kwargs["trigger"],
            "status": kwargs["status"],
            "run_id": None,
        }
        return {"id": kwargs["run_record_id"]}

    async def get_active_run(self, task_id: str) -> dict | None:
        return next(
            (dict(row) for row in self.rows.values() if row["task_id"] == task_id and row["status"] in self._ACTIVE),
            None,
        )

    async def claim_queued_run(self, run_record_id: str, **_kwargs) -> dict | None:
        row = self.rows.get(run_record_id)
        if row is None or row["status"] != "queued":
            return None
        row["status"] = "launching"
        return dict(row)

    async def requeue_claimed_run(self, run_record_id: str, **_kwargs) -> bool:
        row = self.rows.get(run_record_id)
        if row is None or row["status"] != "launching":
            return False
        row["status"] = "queued"
        return True

    async def update_status(self, run_record_id: str, **kwargs) -> bool:
        self.updates.append((run_record_id, kwargs))
        if self._updates_raised < self._fail_updates:
            # The launch-path queued->running write fails AFTER _launch_run has
            # already returned a live run_id. Some tests fail both attempts to
            # pin the last-resort active-slot behavior.
            self._updates_raised += 1
            raise RuntimeError("simulated transient DB error on queued->running write")
        row = self.rows.get(run_record_id)
        if row is None:
            return False
        if "status" in kwargs:
            row["status"] = kwargs["status"]
        if kwargs.get("run_id") is not None:
            row["run_id"] = kwargs["run_id"]
        return True

    async def reconcile_launched_run(self, run_record_id: str, **kwargs) -> bool:
        row = self.rows.get(run_record_id)
        if row is None:
            return False
        row["status"] = "running"
        row["run_id"] = kwargs["run_id"]
        return True

    async def fail_launching_run(self, run_record_id: str, **kwargs) -> bool:
        row = self.rows.get(run_record_id)
        if row is None or row["status"] != "launching":
            return False
        row["status"] = "failed"
        return True

    async def has_active_runs(self, task_id: str) -> bool:
        return any(row["task_id"] == task_id and row["status"] in self._ACTIVE for row in self.rows.values())

    async def mark_stale_active_runs(self, *, error: str) -> int:
        return 0


@pytest.mark.asyncio
async def test_post_launch_bookkeeping_failure_does_not_release_active_slot():
    """Regression for issue #4452.

    A transient failure in the ``queued -> running`` bookkeeping write
    (after ``_launch_run`` has already returned a live ``run_id``) must NOT
    flip the task-run row to ``failed``: ``failed`` is outside the partial
    unique index ``uq_scheduled_task_run_active``, so releasing the slot
    would let the next dispatch launch a DUPLICATE run. The fix keeps the
    row ``running`` with the launched ``run_id`` retained for recovery,
    reconciliation, and cancellation.
    """
    launched: list[dict] = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": f"run-{len(launched)}", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-4452",
                "user_id": "user-1",
                "thread_id": None,
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "do the thing",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "*/5 * * * *"},
                "timezone": "UTC",
                "status": "enabled",
                "overlap_policy": "enqueue",
            }
        ]
    )
    run_repo = _StatefulRunRepo(fail_first_update=True)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    now = datetime.now(UTC)
    task = dict(task_repo.rows[0])

    first = await service.dispatch_task(task, now=now, trigger="scheduled")
    # The run launched despite the post-launch bookkeeping error; the
    # outcome and run_id reflect that a live run is in flight.
    assert first["outcome"] == "launched"
    assert first["run_id"] == "run-1"
    assert first["error"] is not None  # the bookkeeping error is surfaced, not hidden

    # Second dispatch must observe the active slot held by run-1 and NOT
    # launch a duplicate. On main (bug) this would launch run-2 here.
    second = await service.dispatch_task(task, now=now, trigger="scheduled")
    assert len(launched) == 1, launched
    assert second["outcome"] == "conflict", second

    # The launched run_id is retained on the task-run row (status "running",
    # not "failed") so reconciliation / cancellation can still reach it.
    first_row_id = run_repo.created[0]["run_record_id"]
    assert run_repo.rows[first_row_id]["status"] == "running"
    assert run_repo.rows[first_row_id]["run_id"] == "run-1"

    # The bookkeeping transient is NOT surfaced as the parent task's
    # last_error: the run launched and is still in flight, so the task list
    # must not show an error on an actively running task (matching the
    # success path's clear-on-launch model). The real terminal outcome is
    # written by handle_run_completion.
    assert task_repo.updated[1]["last_error"] is None


@pytest.mark.asyncio
async def test_both_post_launch_association_writes_can_fail_without_releasing_slot():
    launched: list[dict] = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-live", "thread_id": kwargs["thread_id"]}

    class FailingTaskRepo(DummyTaskRepo):
        def __init__(self, rows):
            super().__init__(rows)
            self.failures_remaining = 1

        async def update_after_launch(self, *args, **kwargs):
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise RuntimeError("simulated parent bookkeeping failure")
            await super().update_after_launch(*args, **kwargs)

    task = {
        "id": "task-double-failure",
        "user_id": "user-1",
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "prompt": "do the thing",
        "schedule_type": "cron",
        "schedule_spec": {"cron": "*/5 * * * *"},
        "timezone": "UTC",
        "status": "enabled",
        "overlap_policy": "enqueue",
    }
    task_repo = FailingTaskRepo([task])
    run_repo = _StatefulRunRepo(fail_updates=2)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )
    now = datetime.now(UTC)

    first = await service.dispatch_task(dict(task), now=now, trigger="scheduled")
    assert first["outcome"] == "launched"
    first_row_id = run_repo.created[0]["run_record_id"]
    assert run_repo.rows[first_row_id]["task_id"] == "task-double-failure"
    assert run_repo.rows[first_row_id]["status"] == "launching"
    assert run_repo.rows[first_row_id]["run_id"] is None

    second = await service.dispatch_task(dict(task), now=now, trigger="scheduled")
    assert len(launched) == 1
    assert second["outcome"] == "conflict"


@pytest.mark.asyncio
async def test_pre_launch_failure_still_releases_active_slot():
    """Complement to the #4452 fix: when ``_launch_run`` itself fails (no run
    was ever started), the task-run row is marked ``failed`` and the active
    slot is released as before -- the post-launch retention path does not
    apply because there is no live run to protect.
    """
    launched: list[dict] = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        raise RuntimeError("runtime refused to start the run")

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-4452-pre",
                "user_id": "user-1",
                "thread_id": None,
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "do the thing",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "*/5 * * * *"},
                "timezone": "UTC",
                "status": "enabled",
                "overlap_policy": "enqueue",
            }
        ]
    )
    run_repo = _StatefulRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(dict(task_repo.rows[0]), now=datetime.now(UTC), trigger="scheduled")

    assert result["outcome"] == "failed"
    assert result["run_id"] is None
    # launch was attempted (and raised), so exactly one launch attempt, and
    # the row is terminal -> the slot is released for the next dispatch.
    assert len(launched) == 1
    first_row_id = run_repo.created[0]["run_record_id"]
    assert run_repo.rows[first_row_id]["status"] == "failed"
    assert run_repo.rows[first_row_id]["run_id"] is None


@pytest.mark.asyncio
async def test_malformed_launch_result_still_retains_active_slot():
    """Defense-in-depth for the #4452 invariant.

    If ``_launch_run`` returns a malformed result (e.g. missing ``run_id``),
    the unpacking line raises AFTER a live run was already created. The
    dispatch must still take the retention path (keep the row active so the
    slot stays held and no duplicate launches) rather than the pre-launch
    generic-failure path, which would mark the row ``failed`` and release
    the slot while a run is in flight. Keyed off ``launch_succeeded``, not
    ``launched_run_id is not None``.
    """
    launched: list[dict] = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        # Live run started, but the result payload is malformed.
        return {"thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-4452-malformed",
                "user_id": "user-1",
                "thread_id": None,
                "context_mode": "fresh_thread_per_run",
                "assistant_id": "lead_agent",
                "prompt": "do the thing",
                "schedule_type": "cron",
                "schedule_spec": {"cron": "*/5 * * * *"},
                "timezone": "UTC",
                "status": "enabled",
                "overlap_policy": "enqueue",
            }
        ]
    )
    run_repo = _StatefulRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    now = datetime.now(UTC)
    task = dict(task_repo.rows[0])

    first = await service.dispatch_task(task, now=now, trigger="scheduled")
    # Launch succeeded, so the outcome is "launched" (a run is in flight)
    # even though the result unpacking raised; run_id is unknown.
    assert first["outcome"] == "launched"
    assert first["run_id"] is None

    # Second dispatch must observe the active slot still held (row stays in
    # an active status, NOT "failed") and NOT launch a duplicate.
    second = await service.dispatch_task(task, now=now, trigger="scheduled")
    assert len(launched) == 1, launched
    assert second["outcome"] == "conflict", second

    first_row_id = run_repo.created[0]["run_record_id"]
    assert run_repo.rows[first_row_id]["status"] == "running"


@pytest.mark.asyncio
async def test_manual_trigger_is_queued_when_global_budget_exhausted():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-budget", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-budget", status="enabled")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "overlap_policy": "enqueue"})
    task_repo = DummyTaskRepo([row])
    # active_count equals max_concurrent_runs → budget is exhausted
    run_repo = DummyRunRepo(active_count=3)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "queued"
    assert launched == []
    assert run_repo.created["status"] == "queued"


@pytest.mark.asyncio
async def test_manual_trigger_proceeds_when_global_budget_available():
    """Manual trigger must launch when active count is below max_concurrent_runs."""
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-ok", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-ok", status="enabled")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "overlap_policy": "enqueue"})
    task_repo = DummyTaskRepo([row])
    # active_count is 2, max_concurrent_runs is 3 → one slot left
    run_repo = DummyRunRepo(active_count=2)
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "launched"
    assert len(launched) == 1


# ---------------------------------------------------------------------------
# IM notices (issue #4254, RFC #6340 N1). The finalization observer stages one
# notice per occurrence in the transaction that records the outcome; the
# delivery worker sends it. These tests drive the real SQLite repositories.
# ---------------------------------------------------------------------------

NOTICE_NOW = datetime(2026, 10, 6, 8, tzinfo=UTC)
NOTICE_OWNER = "6c1f3d0e-8a8f-4a35-9a51-0d2f5d1b7c11"


class DummyNotificationRepo:
    """Records any enqueue attempt; the service must make none outside finalization."""

    def __init__(self):
        self.enqueued = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)

    async def enqueue_in_session(self, _session, **kwargs):
        self.enqueued.append(kwargs)


class DummyConnectionRepo:
    def __init__(self):
        self.reads = 0

    async def list_connections(self, owner_user_id):
        self.reads += 1
        return [{"provider": "wecom", "external_account_id": "someone", "status": "connected", "owner_user_id": owner_user_id}]


@pytest_asyncio.fixture
async def outbox(tmp_path):
    from types import SimpleNamespace

    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
    from deerflow.persistence.user.model import UserRow

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'notices.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    async with sf() as session:
        session.add(UserRow(id=NOTICE_OWNER, email="owner@example.com"))
        await session.commit()
    tasks, runs, deliveries = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf), NotificationDeliveryRepository(sf)
    service = ScheduledTaskService(task_repo=tasks, task_run_repo=runs, launch_run=None, poll_interval_seconds=60, lease_seconds=30, max_concurrent_runs=3, connection_repo=ChannelConnectionRepository(sf), notification_repo=deliveries)
    try:
        yield SimpleNamespace(sf=sf, tasks=tasks, runs=runs, deliveries=deliveries, service=service)
    finally:
        await close_engine()


async def _bind(env, provider="wecom", target="wecom-user", *, status="connected"):
    from deerflow.persistence.channel_connections.model import ChannelConnectionRow

    async with env.sf() as session:
        session.add(ChannelConnectionRow(id=f"binding-{provider}-{target}", owner_user_id=NOTICE_OWNER, provider=provider, status=status, external_account_id=target))
        await session.commit()


async def _set_locale(env, value):
    from sqlalchemy import delete

    from deerflow.persistence.user.model import UserPreferenceRow

    async with env.sf() as session:
        await session.execute(delete(UserPreferenceRow).where(UserPreferenceRow.user_id == NOTICE_OWNER, UserPreferenceRow.key == "locale"))
        if value is not None:
            session.add(UserPreferenceRow(user_id=NOTICE_OWNER, key="locale", value=value))
        await session.commit()


async def _task(env, task_id="task-a", *, origin_thread_id=None, once=False, **extra):
    task = await env.tasks.create(
        task_id=task_id,
        user_id=NOTICE_OWNER,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Check the release checklist",
        prompt="Check release-checklist.md.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=NOTICE_NOW,
        origin_thread_id=origin_thread_id,
        **extra,
    )
    if once:
        await env.tasks.update(task_id, user_id=NOTICE_OWNER, updates={"schedule_type": "once", "schedule_spec": {"run_at": NOTICE_NOW.isoformat()}})
    return task


async def _occurrence(env, task_id="task-a", suffix="1", *, trigger="scheduled", stop=False, reply="Report is ready", durable_status="running"):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow

    occurrence_id, run_id = f"task-run-{task_id}-{suffix}", f"run-{task_id}-{suffix}"
    await env.runs.create(run_record_id=occurrence_id, task_id=task_id, thread_id=f"thread-{task_id}-{suffix}", scheduled_for=NOTICE_NOW, trigger=trigger, status="running")
    await env.runs.update_status(occurrence_id, status="running", run_id=run_id, started_at=NOTICE_NOW)
    async with env.sf() as session:
        session.add(
            RunRow(
                run_id=run_id,
                thread_id=f"thread-{task_id}-{suffix}",
                user_id=NOTICE_OWNER,
                status=durable_status,
                last_ai_message=reply,
                metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": occurrence_id},
                created_at=NOTICE_NOW,
            )
        )
        if stop:
            (await session.get(ScheduledTaskRunRow, occurrence_id)).stop_requested_run_id = run_id
        await session.commit()
    return occurrence_id, run_id


async def _complete(env, occurrence_id, run_id, *, task_id="task-a", status="success", error=None, finished_at=NOTICE_NOW):
    return await env.tasks.complete_run(task_id, user_id=NOTICE_OWNER, task_run_id=occurrence_id, run_id=run_id, status=status, error=error, finished_at=finished_at)


async def _notices(env):
    from sqlalchemy import select

    from deerflow.persistence.notification_deliveries import NotificationDeliveryRow

    async with env.sf() as session:
        rows = (await session.execute(select(NotificationDeliveryRow).order_by(NotificationDeliveryRow.created_at, NotificationDeliveryRow.id))).scalars()
        return [{"event": row.event, "provider": row.provider, "target": row.target, "task_run_id": row.task_run_id, "run_id": row.run_id, "payload": row.payload_json} for row in rows]


async def _deliver_all(env, *, default_locale="en-US"):
    """Send every queued notice through the real worker with a fake WeCom channel; return the texts."""
    from app.scheduler.notification_delivery import NotificationDeliveryWorker
    from deerflow.persistence.run import RunRepository

    sent = []

    class Channel:
        is_running = True

        async def send_notification(self, *, target, text_markdown):
            sent.append(text_markdown)

    run_repo = RunRepository(env.sf)

    async def resolve_run_summary(run_id, user_id):
        row = await run_repo.get(run_id, user_id=user_id)
        return row.get("last_ai_message") if row else None

    channel = Channel()
    worker = NotificationDeliveryWorker(delivery_repo=env.deliveries, resolve_channel=lambda _provider: channel, resolve_run_summary=resolve_run_summary, default_locale=default_locale)
    await worker.run_once(now=datetime.now(UTC) + timedelta(days=1))
    return sent


@pytest.mark.asyncio
async def test_unsupported_provider_gets_no_outbox_row(outbox):
    await _task(outbox)
    await _bind(outbox, "feishu", "ou_feishu")
    await _bind(outbox, "wecom", "wecom-user")
    await _bind(outbox, "wecom", "revoked-user", status="revoked")
    occurrence_id, run_id = await _occurrence(outbox)
    assert await _complete(outbox, occurrence_id, run_id) is True
    assert [(row["event"], row["provider"], row["target"]) for row in await _notices(outbox)] == [("run_completed", "wecom", "wecom-user")]


@pytest.mark.asyncio
async def test_auto_pause_sends_one_merged_notice(outbox):
    await _task(outbox, goal_objective="every item is checked")
    await _bind(outbox)
    for suffix, code in (("1", "goal_not_met_yet"), ("2", "goal_not_met_yet"), ("3", "blocked:needs_user_input")):
        occurrence_id, run_id = await _occurrence(outbox, suffix=suffix, reply="Two items are still open")
        await _complete(outbox, occurrence_id, run_id, status="unmet", error=code)
    assert (await outbox.tasks.get("task-a", user_id=NOTICE_OWNER))["status"] == "paused"
    notices = await _notices(outbox)
    # Runs 1 and 2 each send their unmet notice; run 3 sends only the merged pause.
    assert [(row["event"], row["task_run_id"]) for row in notices] == [
        ("run_unmet", "task-run-task-a-1"),
        ("run_unmet", "task-run-task-a-2"),
        ("task_paused", "task-run-task-a-3"),
    ]
    assert notices[-1]["payload"]["latest_reason_code"] == "blocked:needs_user_input"
    text = (await _deliver_all(outbox))[-1]
    assert text.splitlines() == [
        "Scheduled task “Check the release checklist”",
        "Paused after 3 runs in a row missed the goal: it needs your input.",
        "Result: Two items are still open",
        "Open DeerFlow → Scheduled tasks for details.",
    ]


@pytest.mark.asyncio
async def test_agent_stop_sends_task_stopped_only(outbox):
    await _task(outbox, stop_condition="all items are ticked")
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, stop=True, reply="All 12 items are ticked")
    await _complete(outbox, occurrence_id, run_id)
    notices = await _notices(outbox)
    assert [row["event"] for row in notices] == ["task_stopped"]
    assert notices[0]["payload"]["stop_condition"] == "all items are ticked"
    assert (await _deliver_all(outbox))[0].splitlines()[1:3] == ["Paused by agent: its stop condition was met (all items are ticked).", "Result: All 12 items are ticked"]


@pytest.mark.asyncio
async def test_max_runs_finish_sends_task_finished_with_summary_enrichment(outbox):
    await _task(outbox, max_runs=1)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, reply="**Done:** the checklist is complete\nDetails…")
    await _complete(outbox, occurrence_id, run_id)
    notices = await _notices(outbox)
    assert [(row["event"], row["run_id"]) for row in notices] == [("task_finished", run_id)]
    assert (notices[0]["payload"]["reason_code"], notices[0]["payload"]["max_runs"], notices[0]["payload"]["run_status"]) == ("max_runs", 1, "success")
    (text,) = await _deliver_all(outbox)
    assert text.splitlines()[1:3] == ["Finished: its one automatic run is done.", "Result: Done: the checklist is complete"]


@pytest.mark.asyncio
async def test_max_runs_finish_after_failed_run_says_last_run_failed(outbox):
    await _task(outbox, max_runs=1)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, reply="partial work")
    await _complete(outbox, occurrence_id, run_id, status="failed", error="model provider timeout")
    notices = await _notices(outbox)
    assert [row["event"] for row in notices] == ["task_finished"]
    (text,) = await _deliver_all(outbox)
    assert text.splitlines()[1] == "Finished: its one automatic run is done. The last run failed."
    assert "partial work" not in text and "timeout" not in text


@pytest.mark.asyncio
async def test_manual_trigger_sends_no_run_notice(outbox):
    await _task(outbox)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, trigger="manual")
    assert await _complete(outbox, occurrence_id, run_id) is True
    assert await _notices(outbox) == []


@pytest.mark.asyncio
async def test_manual_trial_that_finishes_task_sends_task_finished(outbox):
    await _task(outbox, end_at=NOTICE_NOW + timedelta(minutes=1))
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, trigger="manual")
    await _complete(outbox, occurrence_id, run_id, finished_at=NOTICE_NOW + timedelta(minutes=2))
    assert (await outbox.tasks.get("task-a", user_id=NOTICE_OWNER))["status"] == "completed"
    notices = await _notices(outbox)
    assert [(row["event"], row["payload"]["reason_code"]) for row in notices] == [("task_finished", "end_at")]
    assert (await _deliver_all(outbox))[0].splitlines()[1] == "Finished: its end time has been reached."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trigger", "status", "expected"), [("scheduled", "success", ["run_completed"]), ("scheduled", "failed", ["run_failed"]), ("scheduled", "unmet", ["run_unmet"]), ("scheduled", "interrupted", []), ("manual", "success", [])]
)
async def test_once_task_sends_only_its_run_event(outbox, trigger, status, expected):
    await _task(outbox, once=True)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, trigger=trigger)
    await _complete(outbox, occurrence_id, run_id, status=status, error="goal_not_met_yet" if status == "unmet" else None)
    # A once task's own outcome is its notice; no separate task_finished.
    assert [row["event"] for row in await _notices(outbox)] == expected


@pytest.mark.asyncio
async def test_idle_finish_dedupe_key_is_deterministic_for_page_tasks(outbox):
    await _task(outbox, end_at=NOTICE_NOW + timedelta(hours=1))
    await _bind(outbox)
    later = NOTICE_NOW + timedelta(hours=2)
    assert await outbox.tasks.complete_if_ended("task-a", user_id=NOTICE_OWNER, now=later) is True
    await outbox.tasks.complete_if_ended("task-a", user_id=NOTICE_OWNER, now=later)
    notices = await _notices(outbox)
    assert [(row["event"], row["run_id"], row["payload"]["reason_code"]) for row in notices] == [("task_finished", None, "end_at")]
    key = notices[0]["task_run_id"]
    assert key.startswith("idle:") and len(key) <= 64
    from app.scheduler.service import _idle_notice_key
    from deerflow.utils.time import coerce_iso

    assert key == _idle_notice_key("task-a", f"end:{coerce_iso(NOTICE_NOW + timedelta(hours=1))}")
    (text,) = await _deliver_all(outbox)
    assert "Result:" not in text


@pytest.mark.asyncio
async def test_locale_from_preference_then_config_fallback(outbox):
    await _bind(outbox)
    for index, preference in enumerate(("zh-CN", None, "fr-FR", {"value": "zh-CN"})):
        await _set_locale(outbox, preference)
        task_id = f"task-{index}"
        await _task(outbox, task_id)
        occurrence_id, run_id = await _occurrence(outbox, task_id, reply="Done")
        await _complete(outbox, occurrence_id, run_id, task_id=task_id)
    assert [row["payload"]["locale"] for row in await _notices(outbox)] == ["zh-CN", None, None, None]
    texts = await _deliver_all(outbox, default_locale="en-US")
    assert [text.splitlines()[-1] for text in texts] == ["在 DeerFlow 的定时任务页查看详情。"] + ["Open DeerFlow → Scheduled tasks for details."] * 3


@pytest.mark.asyncio
async def test_locale_without_preference_follows_notification_locale(outbox):
    await _bind(outbox)
    await _task(outbox)
    occurrence_id, run_id = await _occurrence(outbox, reply="Done")
    await _complete(outbox, occurrence_id, run_id)
    (text,) = await _deliver_all(outbox, default_locale="zh-CN")
    assert text.splitlines() == ["定时任务“Check the release checklist”", "完成了一次运行。", "结果：Done", "在 DeerFlow 的定时任务页查看详情。"]


@pytest.mark.asyncio
async def test_recovered_success_notifies_exactly_once(outbox):
    await _task(outbox)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox, durable_status="success")
    # The completion hook never ran (crash); lease reconciliation finalizes it.
    assert await outbox.runs.reconcile_active_runs(error="lease lost", now=NOTICE_NOW) == 1
    assert await outbox.runs.reconcile_active_runs(error="lease lost", now=NOTICE_NOW) == 0
    await outbox.service.handle_run_completion(
        RunRecord(
            run_id=run_id,
            thread_id="thread-task-a-1",
            assistant_id="lead_agent",
            status=RunStatus.success,
            on_disconnect=DisconnectMode.continue_,
            metadata={"scheduled_task_id": "task-a", "scheduled_task_run_id": occurrence_id, "scheduled_trigger": "scheduled"},
            user_id=NOTICE_OWNER,
        )
    )
    assert [(row["event"], row["task_run_id"]) for row in await _notices(outbox)] == [("run_completed", occurrence_id)]


@pytest.mark.asyncio
async def test_detached_outbox_stops_the_enqueue(outbox):
    await _task(outbox)
    await _bind(outbox)
    occurrence_id, run_id = await _occurrence(outbox)
    await _complete(outbox, occurrence_id, run_id)
    outbox.service.detach_notification_outbox()
    occurrence_id, run_id = await _occurrence(outbox, suffix="2")
    await _complete(outbox, occurrence_id, run_id)
    assert [row["task_run_id"] for row in await _notices(outbox)] == ["task-run-task-a-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [True, False])
async def test_handle_run_completion_no_longer_enqueues_outside_transaction(completed):
    """Only the finalization observer enqueues; the completion hook just records the outcome."""

    class RecordingTaskRepo(DummyTaskRepo):
        reads = 0

        async def complete_run(self, task_id, **kwargs):
            await super().complete_run(task_id, **kwargs)
            return completed

        async def get(self, task_id, *, user_id):
            self.reads += 1
            return await super().get(task_id, user_id=user_id)

    task_repo = RecordingTaskRepo([_once_task_row()])
    notification_repo, connection_repo = DummyNotificationRepo(), DummyConnectionRepo()
    service = ScheduledTaskService(task_repo=task_repo, task_run_repo=DummyRunRepo(), launch_run=None, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3, connection_repo=connection_repo, notification_repo=notification_repo)

    for status in (RunStatus.success, RunStatus.error, RunStatus.interrupted):
        await service.handle_run_completion(_completion_record(status, error="boom" if status == RunStatus.error else None))

    assert [completion["status"] for _task_id, completion in task_repo.completions] == ["success", "failed", "interrupted"]
    assert notification_repo.enqueued == []
    assert connection_repo.reads == 0 and task_repo.reads == 0
    assert not hasattr(service, "_enqueue_run_notifications")


@pytest.mark.asyncio
async def test_trigger_while_a_scheduled_occurrence_is_queued_reports_the_existing_row():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-x", "thread_id": kwargs["thread_id"]}

    class QueuedRunRepo(DummyRunRepo):
        async def get_active_run(self, task_id):
            return {"id": "task-run-waiting", "task_id": task_id, "thread_id": "thread-waiting", "status": "queued", "trigger": "scheduled"}

    row = _once_task_row(task_id="task-waiting")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "status": "enabled"})
    run_repo = QueuedRunRepo()
    service = ScheduledTaskService(task_repo=DummyTaskRepo([row]), task_run_repo=run_repo, launch_run=fake_launch, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3)

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "queued"
    assert result["existing"] is True
    assert result["task_run_id"] == "task-run-waiting"
    assert result["thread_id"] == "thread-waiting"
    assert run_repo.created is None
    assert launched == []


@pytest.mark.asyncio
async def test_a_new_queued_trial_is_not_reported_as_existing():
    async def fake_launch(**kwargs):
        raise AssertionError("budget is exhausted; nothing launches")

    row = _once_task_row(task_id="task-budget")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "status": "enabled"})
    run_repo = DummyRunRepo(active_count=3)
    service = ScheduledTaskService(task_repo=DummyTaskRepo([row]), task_run_repo=run_repo, launch_run=fake_launch, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3)

    result = await service.dispatch_task(row, now=datetime.now(UTC), trigger="manual")

    assert result["outcome"] == "queued"
    assert result["existing"] is False
    assert run_repo.created is not None


@pytest.mark.asyncio
async def test_is_running_reflects_the_poller_task():
    service = ScheduledTaskService(task_repo=DummyTaskRepo([]), task_run_repo=DummyRunRepo(), launch_run=None, poll_interval_seconds=60, lease_seconds=120, max_concurrent_runs=1)
    assert service.is_running is False
    await service.start()
    try:
        assert service.is_running is True
    finally:
        await service.stop()
    assert service.is_running is False


class NumberedRunRepo(DummyRunRepo):
    def __init__(self, number):
        super().__init__()
        self.number = number
        self.number_calls = []

    async def run_number(self, task_run_id):
        self.number_calls.append(task_run_id)
        return self.number


def _provenance_task(**updates):
    return {
        "id": "task-prov",
        "user_id": "user-1",
        "thread_id": None,
        "context_mode": "fresh_thread_per_run",
        "assistant_id": "lead_agent",
        "title": "检查发布清单",
        "prompt": "检查 release-checklist.md，列出没勾的项",
        "stop_condition": "清单全部勾完",
        "standing_notes": ["用 develop 分支"],
        "schedule_type": "cron",
        "schedule_spec": {"cron": "0 9 * * 1-5"},
        "timezone": "Asia/Shanghai",
        "status": "enabled",
        **updates,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["scheduled", "manual"])
async def test_launch_passes_user_language_origin_and_run_thread_title(trigger):
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-prov", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo([_provenance_task()])
    run_repo = NumberedRunRepo(4)
    service = ScheduledTaskService(task_repo=task_repo, task_run_repo=run_repo, launch_run=fake_launch, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3, own_stop_available=True)
    now = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)

    await service.dispatch_task(task_repo.rows[0], now=now, trigger=trigger)

    (launch,) = launches
    origin = launch["origin"]
    task_run_id = run_repo.created["run_record_id"]
    assert origin == {
        "task_id": "task-prov",
        "task_run_id": task_run_id,
        "trigger": trigger,
        "run_number": 4 if trigger == "scheduled" else None,
        "scheduled_for": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "schedule_type": "cron",
        "task_title": "检查发布清单",
        "instructions": "检查 release-checklist.md，列出没勾的项",
        "stop_condition": "清单全部勾完",
        "standing_notes": ["用 develop 分支"],
    }
    assert run_repo.number_calls == ([task_run_id] if trigger == "scheduled" else [])
    # The launched text carries the host-written stop rule and notes block; the
    # origin keeps only the user's own words.
    assert launch["prompt"].startswith(origin["instructions"])
    assert "stop_scheduled_task" in launch["prompt"] and "<standing_notes>" in launch["prompt"]
    assert launch["title"] == "检查发布清单 · 10-07 09:00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "trigger", "expected"),
    [
        ({"schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}, "scheduled", "检查发布清单 · #4"),
        ({"schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}, "manual", "检查发布清单"),
        ({"schedule_type": "once", "schedule_spec": {"run_at": "2026-10-07T01:00:00+00:00"}, "timezone": "UTC"}, "scheduled", "检查发布清单 · #4"),
        ({"schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "Asia/Shanghai"}, "scheduled", "检查发布清单 · 10-07 09:00"),
        ({"schedule_type": "cron", "schedule_spec": {"cron": "0 1 * * *"}, "timezone": "UTC"}, "scheduled", "检查发布清单 · 10-07 01:00"),
    ],
    ids=["interval-placeholder", "interval-placeholder-trial", "once-offset-placeholder", "interval-real-zone", "cron-real-utc"],
)
async def test_run_thread_title_never_shows_a_placeholder_utc_time(updates, trigger, expected):
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-prov", "thread_id": kwargs["thread_id"]}

    task_repo = DummyTaskRepo([_provenance_task(**updates)])
    service = ScheduledTaskService(task_repo=task_repo, task_run_repo=NumberedRunRepo(4), launch_run=fake_launch, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3, own_stop_available=True)
    await service.dispatch_task(task_repo.rows[0], now=datetime(2026, 10, 7, 1, 0, tzinfo=UTC), trigger=trigger)
    (launch,) = launches
    assert launch["title"] == expected
    assert launch["origin"]["schedule_type"] == updates["schedule_type"]


@pytest.mark.asyncio
async def test_reuse_thread_launch_has_no_title_and_survives_a_missing_run_number():
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        return {"run_id": "run-prov", "thread_id": kwargs["thread_id"]}

    class BrokenNumberRepo(DummyRunRepo):
        async def run_number(self, task_run_id):
            raise RuntimeError("database unavailable")

    task_repo = DummyTaskRepo([_provenance_task(context_mode="reuse_thread", thread_id="thread-1", stop_condition=None, standing_notes=None)])
    service = ScheduledTaskService(task_repo=task_repo, task_run_repo=BrokenNumberRepo(), launch_run=fake_launch, poll_interval_seconds=5, lease_seconds=120, max_concurrent_runs=3)

    result = await service.dispatch_task(task_repo.rows[0], now=datetime(2026, 10, 7, 1, 0, tzinfo=UTC), trigger="scheduled")

    assert result["outcome"] == "launched"
    (launch,) = launches
    assert launch["title"] is None
    assert launch["origin"]["run_number"] is None
    assert (launch["origin"]["stop_condition"], launch["origin"]["standing_notes"]) == (None, [])
