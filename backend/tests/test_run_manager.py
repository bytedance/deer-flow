"""Tests for RunManager."""

import asyncio
import re

import pytest

from deerflow.runtime import RunManager, RunStatus

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


@pytest.fixture
def manager() -> RunManager:
    return RunManager()


@pytest.mark.anyio
async def test_create_and_get(manager: RunManager):
    """Created run should be retrievable with new fields."""
    record = await manager.create(
        "thread-1",
        "lead_agent",
        metadata={"key": "val"},
        kwargs={"input": {}},
        multitask_strategy="reject",
    )
    assert record.status == RunStatus.pending
    assert record.thread_id == "thread-1"
    assert record.assistant_id == "lead_agent"
    assert record.metadata == {"key": "val"}
    assert record.kwargs == {"input": {}}
    assert record.multitask_strategy == "reject"
    assert ISO_RE.match(record.created_at)
    assert ISO_RE.match(record.updated_at)

    fetched = manager.get(record.run_id)
    assert fetched is record


@pytest.mark.anyio
async def test_status_transitions(manager: RunManager):
    """Status should transition pending -> running -> success."""
    record = await manager.create("thread-1")
    assert record.status == RunStatus.pending

    await manager.set_status(record.run_id, RunStatus.running)
    assert record.status == RunStatus.running
    assert ISO_RE.match(record.updated_at)

    await manager.set_status(record.run_id, RunStatus.success)
    assert record.status == RunStatus.success


@pytest.mark.anyio
async def test_cancel(manager: RunManager):
    """Cancel should set abort_event and transition to cancelling.

    Final state (interrupted/error) is set by the worker after cleanup;
    see #2505 for the rollback-serialization rationale.
    """
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    cancelled = await manager.cancel(record.run_id)
    assert cancelled is True
    assert record.abort_event.is_set()
    assert record.status == RunStatus.cancelling


@pytest.mark.anyio
async def test_cancel_not_inflight(manager: RunManager):
    """Cancelling a completed run should return False."""
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.success)

    cancelled = await manager.cancel(record.run_id)
    assert cancelled is False


@pytest.mark.anyio
async def test_list_by_thread(manager: RunManager):
    """Same thread should return multiple runs, newest first."""
    r1 = await manager.create("thread-1")
    r2 = await manager.create("thread-1")
    await manager.create("thread-2")

    runs = await manager.list_by_thread("thread-1")
    assert len(runs) == 2
    assert runs[0].run_id == r2.run_id
    assert runs[1].run_id == r1.run_id


@pytest.mark.anyio
async def test_list_by_thread_is_stable_when_timestamps_tie(manager: RunManager, monkeypatch: pytest.MonkeyPatch):
    """Newest-first ordering should not depend on timestamp precision."""
    monkeypatch.setattr("deerflow.runtime.runs.manager._now_iso", lambda: "2026-01-01T00:00:00+00:00")

    r1 = await manager.create("thread-1")
    r2 = await manager.create("thread-1")

    runs = await manager.list_by_thread("thread-1")
    assert [run.run_id for run in runs] == [r2.run_id, r1.run_id]


@pytest.mark.anyio
async def test_has_inflight(manager: RunManager):
    """has_inflight should be True when a run is pending or running."""
    record = await manager.create("thread-1")
    assert await manager.has_inflight("thread-1") is True

    await manager.set_status(record.run_id, RunStatus.success)
    assert await manager.has_inflight("thread-1") is False


@pytest.mark.anyio
async def test_cleanup(manager: RunManager):
    """After cleanup, the run should be gone."""
    record = await manager.create("thread-1")
    run_id = record.run_id

    await manager.cleanup(run_id, delay=0)
    assert manager.get(run_id) is None


@pytest.mark.anyio
async def test_set_status_with_error(manager: RunManager):
    """Error message should be stored on the record."""
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.error, error="Something went wrong")
    assert record.status == RunStatus.error
    assert record.error == "Something went wrong"


@pytest.mark.anyio
async def test_get_nonexistent(manager: RunManager):
    """Getting a nonexistent run should return None."""
    assert manager.get("does-not-exist") is None


@pytest.mark.anyio
async def test_create_defaults(manager: RunManager):
    """Create with no optional args should use defaults."""
    record = await manager.create("thread-1")
    assert record.metadata == {}
    assert record.kwargs == {}
    assert record.multitask_strategy == "reject"
    assert record.assistant_id is None


# --- #2505: rollback-serialization regression tests ---


@pytest.mark.anyio
async def test_has_inflight_includes_cancelling_and_rolling_back(manager: RunManager):
    """Cancelling/rolling_back must count as inflight so a new run waits."""
    a = await manager.create("thread-1")
    await manager.set_status(a.run_id, RunStatus.cancelling)
    assert await manager.has_inflight("thread-1") is True

    await manager.set_status(a.run_id, RunStatus.rolling_back)
    assert await manager.has_inflight("thread-1") is True

    await manager.set_status(a.run_id, RunStatus.interrupted)
    assert await manager.has_inflight("thread-1") is False


@pytest.mark.anyio
async def test_create_or_reject_awaits_cancelled_workers_before_creating(manager: RunManager):
    """Interrupt/rollback strategies must wait for the old worker to finish.

    Before #2505 was fixed, create_or_reject would mark the inflight run
    as ``interrupted`` and immediately insert the new run, leaving the old
    worker free to write rollback state on top of the new run. The fix
    awaits the worker's task before insertion so the new run is serialized
    after cleanup.
    """
    # Old run with a still-running worker task.
    old = await manager.create("thread-1", multitask_strategy="rollback")
    await manager.set_status(old.run_id, RunStatus.running)

    finished_in_correct_order: list[str] = []

    async def fake_worker() -> None:
        try:
            # The cancel signal hits before this completes naturally.
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # Simulate rollback cleanup: takes time, sets status during.
            await manager.set_status(old.run_id, RunStatus.rolling_back)
            await asyncio.sleep(0.05)
            await manager.set_status(old.run_id, RunStatus.interrupted)
            finished_in_correct_order.append("worker_done")
            raise

    old.task = asyncio.create_task(fake_worker())
    # Yield once so the task starts.
    await asyncio.sleep(0)

    # Kick off create_or_reject. It must wait for the worker.
    new_run = await manager.create_or_reject(
        "thread-1",
        multitask_strategy="rollback",
    )
    finished_in_correct_order.append("new_created")

    # Worker finished BEFORE the new run was created.
    assert finished_in_correct_order == ["worker_done", "new_created"]
    assert old.status == RunStatus.interrupted
    assert new_run.status == RunStatus.pending
    assert new_run.thread_id == "thread-1"


@pytest.mark.anyio
async def test_create_or_reject_skips_already_cancelling_runs(manager: RunManager):
    """Re-cancelling a cancelling run is a no-op for state, but still awaited.

    If two cancellations race in for the same run, the second one must
    not stomp on the first one's abort_action. We still wait on the task
    so the new run is serialized after cleanup either way.
    """
    old = await manager.create("thread-1", multitask_strategy="rollback")
    await manager.set_status(old.run_id, RunStatus.running)

    # First signaller: rollback action.
    cancelled = await manager.cancel(old.run_id, action="rollback")
    assert cancelled is True
    assert old.status == RunStatus.cancelling
    assert old.abort_action == "rollback"

    # Old has no real task; create_or_reject must still proceed and not
    # overwrite abort_action.
    new_run = await manager.create_or_reject(
        "thread-1",
        multitask_strategy="interrupt",
    )
    assert old.abort_action == "rollback"  # not stomped
    assert new_run.status == RunStatus.pending
