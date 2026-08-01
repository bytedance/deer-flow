from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.runtime import ConflictError, RunStatus
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode


class DummyTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False
        self.updated = None
        self.cancelled_stuck_once = None

    async def cancel_stuck_once_tasks(self, *, error):
        self.cancelled_stuck_once = error
        return 0

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def update_after_launch(self, *args, **kwargs):
        self.updated = (args, kwargs)

    async def get(self, task_id: str, *, user_id: str):
        row = next((item for item in self.rows if item["id"] == task_id and item["user_id"] == user_id), None)
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

    async def count_active_runs(self):
        return self.active_count

    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self.updated.append((run_record_id, kwargs))

    async def has_active_runs(self, task_id):
        return self.active

    async def mark_stale_active_runs(self, *, error):
        self.stale_marked = error
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
async def test_scheduled_overlap_conflict_is_recorded_as_skip():
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
                "overlap_policy": "skip",
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

    assert result["outcome"] == "skipped"
    assert run_repo.updated[-1][1]["status"] == "skipped"
    assert task_repo.updated[1]["status"] == "enabled"


@pytest.mark.asyncio
async def test_manual_overlap_conflict_returns_conflict():
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
                "overlap_policy": "skip",
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

    assert result["outcome"] == "conflict"
    assert run_repo.updated[-1][1]["status"] == "failed"


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
async def test_handle_run_completion_persists_success():
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

    assert run_repo.updated[-1][0] == "task-run-6"
    assert run_repo.updated[-1][1]["status"] == "success"
    assert task_repo.rows[0]["last_error"] is None


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
        "prompt": "Summarize thread",
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
        "timezone": "UTC",
        "status": status,
    }


def _completion_record(status, *, task_id="task-once", error=None):
    return RunRecord(
        run_id="run-x",
        thread_id="thread-x",
        assistant_id="lead_agent",
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata={
            "scheduled_task_id": task_id,
            "scheduled_task_run_id": "task-run-x",
        },
        user_id="user-1",
        error=error,
    )


@pytest.mark.asyncio
async def test_once_task_completes_only_via_completion_hook():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.success))

    assert run_repo.updated[-1][1]["status"] == "success"
    assert task_repo.rows[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_once_task_failed_run_marks_task_failed():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.error, error="boom"))

    assert run_repo.updated[-1][1]["status"] == "failed"
    assert run_repo.updated[-1][1]["error"] == "boom"
    assert task_repo.rows[0]["status"] == "failed"
    assert task_repo.rows[0]["last_error"] == "boom"


@pytest.mark.asyncio
async def test_interrupted_run_is_distinct_and_cancels_once_task():
    task_repo = DummyTaskRepo([_once_task_row()])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.interrupted))

    run_update = run_repo.updated[-1][1]
    assert run_update["status"] == "interrupted"
    assert run_update["error"] == "run was interrupted before completion"
    assert task_repo.rows[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_interrupted_cron_run_keeps_task_enabled():
    row = _once_task_row(task_id="task-cron")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "status": "enabled"})
    task_repo = DummyTaskRepo([row])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.handle_run_completion(_completion_record(RunStatus.interrupted, task_id="task-cron"))

    assert run_repo.updated[-1][1]["status"] == "interrupted"
    assert task_repo.rows[0]["status"] == "enabled"


@pytest.mark.asyncio
async def test_skip_policy_applies_to_fresh_thread_runs():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-9", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-9")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "running", "overlap_policy": "skip"})
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

    assert result["outcome"] == "skipped"
    assert launched == []
    # The skip tombstone is created directly as terminal "skipped" (not the
    # transient "queued" the launch path uses): a queued row is active and would
    # itself trip the uq_scheduled_task_run_active partial unique index against
    # the pre-existing run still holding the task's single active slot.
    assert run_repo.created["status"] == "skipped"
    assert run_repo.updated[-1][1]["status"] == "skipped"
    assert task_repo.updated[1]["status"] == "enabled"
    assert task_repo.updated[1]["increment_run_count"] is False


@pytest.mark.asyncio
async def test_startup_sweep_reconciles_stale_runs_and_stuck_once_tasks():
    task_repo = DummyTaskRepo([])
    run_repo = DummyRunRepo()
    service = _make_service(task_repo, run_repo)

    await service.start()
    await service.stop()

    assert run_repo.stale_marked is not None
    assert task_repo.cancelled_stuck_once == run_repo.stale_marked


@pytest.mark.asyncio
async def test_manual_trigger_with_active_run_returns_conflict_without_launching():
    launched = []

    async def fake_launch(**kwargs):
        launched.append(kwargs)
        return {"run_id": "run-x", "thread_id": kwargs["thread_id"]}

    row = _once_task_row(task_id="task-manual-busy")
    row.update({"schedule_type": "cron", "schedule_spec": {"cron": "* * * * *"}, "status": "enabled", "overlap_policy": "skip"})
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
async def test_run_once_claims_only_into_remaining_global_budget():
    claim_limits = []

    class BudgetTaskRepo(DummyTaskRepo):
        async def claim_due_tasks(self, **kwargs):
            claim_limits.append(kwargs["limit"])
            return []

    task_repo = BudgetTaskRepo([])
    run_repo = DummyRunRepo(active_count=2)
    service = _make_service(task_repo, run_repo)

    await service.run_once(now=datetime.now(UTC))
    assert claim_limits == [1]

    run_repo.active_count = 3
    await service.run_once(now=datetime.now(UTC))
    # Budget exhausted: no claim at all this cycle.
    assert claim_limits == [1]


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

    _ACTIVE = {"queued", "running"}

    def __init__(self, *, fail_first_update: bool = False) -> None:
        self.created: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.rows: dict[str, dict] = {}
        self._fail_first_update = fail_first_update
        self._first_update_raised = False

    async def count_active_runs(self) -> int:
        return sum(1 for row in self.rows.values() if row["status"] in self._ACTIVE)

    async def create(self, **kwargs) -> dict:
        self.created.append(kwargs)
        self.rows[kwargs["run_record_id"]] = {
            "task_id": kwargs["task_id"],
            "status": kwargs["status"],
            "run_id": None,
        }
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id: str, **kwargs) -> None:
        self.updates.append((run_record_id, kwargs))
        if self._fail_first_update and not self._first_update_raised:
            # The launch-path queued->running write fails once, AFTER
            # _launch_run has already returned a live run_id.
            self._first_update_raised = True
            raise RuntimeError("simulated transient DB error on queued->running write")
        row = self.rows.get(run_record_id)
        if row is None:
            return
        if "status" in kwargs:
            row["status"] = kwargs["status"]
        if kwargs.get("run_id") is not None:
            row["run_id"] = kwargs["run_id"]

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
                "overlap_policy": "skip",
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
    assert second["outcome"] in {"skipped", "conflict"}, second

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
                "overlap_policy": "skip",
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
                "overlap_policy": "skip",
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
    assert second["outcome"] in {"skipped", "conflict"}, second

    first_row_id = run_repo.created[0]["run_record_id"]
    assert run_repo.rows[first_row_id]["status"] == "running"
