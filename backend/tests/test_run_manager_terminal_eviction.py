"""Regression tests for bounded terminal ``RunManager`` retention (#5009)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.runs.manager import PersistenceRetryPolicy, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import (
    _BACKGROUND_TERMINAL_TASKS,
    RunContext,
    _spawn_background_terminal_task,
    run_agent,
)


class RecoveringRunStore(MemoryRunStore):
    """Store whose terminal writes can be held failed until a test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_terminal_writes = False
        self.status_write_calls = 0
        self.completion_write_calls = 0
        self.get_calls = 0
        self.read_while_stale = asyncio.Event()

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        self.status_write_calls += 1
        if self.fail_terminal_writes:
            raise RuntimeError("simulated terminal status outage")
        return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    async def update_run_completion(self, run_id, *, status, **kwargs):
        self.completion_write_calls += 1
        if self.fail_terminal_writes:
            raise RuntimeError("simulated completion outage")
        return await super().update_run_completion(run_id, status=status, **kwargs)

    async def get(self, run_id, *, user_id=None):
        self.get_calls += 1
        row = await super().get(run_id, user_id=user_id)
        if row is not None and row.get("status") in {RunStatus.pending.value, RunStatus.running.value}:
            self.read_while_stale.set()
        return row


class StatusWriteFailingRunStore(MemoryRunStore):
    """Store where terminal status writes fail but completion writes succeed."""

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        raise RuntimeError("simulated status-only outage")


async def _terminal_run(manager: RunManager, thread_id: str = "thread-eviction") -> str:
    record = await manager.create(thread_id)
    await manager.set_status(record.run_id, RunStatus.success)
    return record.run_id


async def _forget_local_record(manager: RunManager, run_id: str, thread_id: str) -> None:
    """Drop a local entry so the next idempotent admission hydrates it."""
    async with manager._lock:
        manager._runs.pop(run_id, None)
        manager._unindex_run_locked(run_id, thread_id)


@pytest.mark.asyncio
async def test_memory_only_manager_preserves_terminal_history():
    manager = RunManager()
    run_id = await _terminal_run(manager)

    assert manager.schedule_terminal_eviction(run_id, delay=0) is None
    assert run_id in manager._runs


@pytest.mark.asyncio
async def test_terminal_eviction_prunes_both_indexes_and_hydrates_from_store():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)
    thread_id = manager._runs[run_id].thread_id

    task = manager.schedule_terminal_eviction(run_id, delay=0)
    assert task is not None
    await task

    assert run_id not in manager._runs
    assert thread_id not in manager._runs_by_thread
    hydrated = await manager.get(run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_terminal_idempotent_reuse_stays_store_only():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject(
        "thread-idempotent-terminal",
        user_id="user-a",
        idempotency_key="idempotency-terminal-1",
    )
    await manager.set_status(record.run_id, RunStatus.success)
    await _forget_local_record(manager, record.run_id, record.thread_id)

    reused = await manager.create_or_reject(
        record.thread_id,
        user_id="user-a",
        idempotency_key="idempotency-terminal-1",
    )

    assert reused.run_id == record.run_id
    assert reused.idempotency_reused is True
    assert reused.status == RunStatus.success
    assert reused.store_only is True
    assert record.run_id not in manager._runs
    assert record.thread_id not in manager._runs_by_thread

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_inflight_idempotent_reuse_is_still_locally_indexed():
    store = MemoryRunStore()
    await store.put(
        "run-peer-inflight",
        thread_id="thread-idempotent-inflight",
        user_id="user-a",
        status=RunStatus.running.value,
        operation_kind="run",
        multitask_strategy="reject",
        metadata={},
        kwargs={},
        owner_worker_id="worker-peer",
        lease_expires_at="2099-01-01T00:00:00+00:00",
        idempotency_key="idempotency-inflight-1",
    )
    manager = RunManager(store=store)

    reused = await manager.create_or_reject(
        "thread-idempotent-inflight",
        user_id="user-a",
        idempotency_key="idempotency-inflight-1",
    )

    assert reused.idempotency_reused is True
    assert reused.status == RunStatus.running
    assert manager._runs[reused.run_id] is reused
    assert list(manager._runs_by_thread[reused.thread_id]) == [reused.run_id]


@pytest.mark.asyncio
async def test_terminal_eviction_skips_redundant_writes_when_store_snapshot_matches():
    store = RecoveringRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread-already-durable")
    await manager.set_status(record.run_id, RunStatus.success)
    completion_payload = manager._completion_payload(record)
    completion_payload["total_tokens"] = 42
    await manager.update_run_completion(record.run_id, **completion_payload)
    status_writes = store.status_write_calls
    completion_writes = store.completion_write_calls
    reads = store.get_calls

    task = manager.schedule_terminal_eviction(record.run_id, delay=0)
    assert task is not None
    await task

    assert store.status_write_calls == status_writes
    assert store.completion_write_calls == completion_writes
    assert store.get_calls == reads + 1
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_eviction_waits_for_terminal_persistence_and_retries_after_recovery(caplog):
    caplog.set_level("DEBUG", logger="deerflow.runtime.runs.manager")
    store = RecoveringRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=1, initial_delay=0),
    )
    record = await manager.create("thread-persistence-recovery")
    store.fail_terminal_writes = True
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="worker failed",
        stop_reason="tool_capped",
    )
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=42,
    )

    task = manager.schedule_terminal_eviction(record.run_id, delay=0, retry_delay=0.01)
    assert task is not None
    await asyncio.wait_for(store.read_while_stale.wait(), timeout=1)
    assert record.run_id in manager._runs
    assert "retained pending durable terminal state" in caplog.text

    store.fail_terminal_writes = False
    await asyncio.wait_for(task, timeout=1)

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.error
    assert hydrated.error == "worker failed"
    assert hydrated.stop_reason == "tool_capped"
    assert hydrated.total_tokens == 42
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_eviction_repairs_stop_reason_when_only_status_write_failed():
    store = StatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=1, initial_delay=0),
    )
    record = await manager.create("thread-stop-reason-repair")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        stop_reason="token_capped",
    )

    # This mirrors worker finalization: the completion write can make status
    # terminal even though the earlier status write (carrying stop_reason)
    # failed. Eviction must repair the missing reason before dropping local
    # state.
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=42,
    )
    stored_before_eviction = await store.get(record.run_id)
    assert stored_before_eviction is not None
    assert stored_before_eviction["status"] == RunStatus.error.value
    assert stored_before_eviction["stop_reason"] is None

    task = manager.schedule_terminal_eviction(record.run_id, delay=0)
    assert task is not None
    await asyncio.wait_for(task, timeout=1)

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.stop_reason == "token_capped"
    assert hydrated.total_tokens == 42
    assert hydrated.store_only is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.timeout, RunStatus.interrupted])
async def test_terminal_eviction_waits_for_finalizing_barrier(status):
    manager = RunManager(store=MemoryRunStore())
    record = await manager.create(f"thread-finalizing-{status.value}")
    await manager.set_finalizing(record.run_id, True)
    await manager.set_status(record.run_id, status)

    task = manager.schedule_terminal_eviction(record.run_id, delay=0, retry_delay=0.01)
    assert task is not None
    await asyncio.sleep(0.03)

    assert record.run_id in manager._runs
    assert task.done() is False

    await manager.set_finalizing(record.run_id, False)
    await asyncio.wait_for(task, timeout=1)

    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_duplicate_eviction_schedules_share_one_task():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)

    first = manager.schedule_terminal_eviction(run_id, delay=3600)
    second = manager.schedule_terminal_eviction(run_id, delay=3600)

    assert first is not None
    assert second is first
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_evictions_and_rejects_new_ones():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)
    task = manager.schedule_terminal_eviction(run_id, delay=3600)
    assert task is not None

    await manager.shutdown(timeout=1)

    assert task.cancelled()
    assert manager._terminal_eviction_tasks == {}
    assert manager.schedule_terminal_eviction(run_id, delay=0) is None


@pytest.mark.asyncio
async def test_background_terminal_task_is_strongly_referenced_until_done():
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_cleanup() -> None:
        started.set()
        await release.wait()

    task = _spawn_background_terminal_task(delayed_cleanup())
    await asyncio.wait_for(started.wait(), timeout=1)

    assert task in _BACKGROUND_TERMINAL_TASKS

    release.set()
    await asyncio.wait_for(task, timeout=1)
    await asyncio.sleep(0)
    assert task not in _BACKGROUND_TERMINAL_TASKS


@pytest.mark.asyncio
async def test_background_terminal_task_failure_is_observed(caplog):
    caplog.set_level("WARNING", logger="deerflow.runtime.runs.worker")

    async def failed_cleanup() -> None:
        raise RuntimeError("cleanup failed")

    task = _spawn_background_terminal_task(failed_cleanup())
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert task not in _BACKGROUND_TERMINAL_TASKS
    assert "Background terminal task" in caplog.text
    assert "cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_worker_schedules_eviction_even_when_publish_end_fails():
    class EmptyAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            return
            yield  # pragma: no cover

    manager = RunManager(store=MemoryRunStore())
    record = await manager.create("thread-publish-end-failure")
    manager.schedule_terminal_eviction = MagicMock(return_value=None)  # type: ignore[method-assign]
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(side_effect=RuntimeError("stream unavailable")),
        cleanup=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="stream unavailable"):
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=lambda **_kwargs: EmptyAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )

    assert record.status == RunStatus.success
    manager.schedule_terminal_eviction.assert_called_once_with(record.run_id)
    await asyncio.sleep(0)
    bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
