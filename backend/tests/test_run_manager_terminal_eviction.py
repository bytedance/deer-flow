"""Regression tests for bounded terminal ``RunManager`` retention (#5009)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.runs.manager import PersistenceRetryPolicy, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


class RecoveringRunStore(MemoryRunStore):
    """Store whose terminal writes can be held failed until a test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_terminal_writes = False
        self.read_while_stale = asyncio.Event()

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        if self.fail_terminal_writes:
            raise RuntimeError("simulated terminal status outage")
        return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    async def update_run_completion(self, run_id, *, status, **kwargs):
        if self.fail_terminal_writes:
            raise RuntimeError("simulated completion outage")
        return await super().update_run_completion(run_id, status=status, **kwargs)

    async def get(self, run_id, *, user_id=None):
        row = await super().get(run_id, user_id=user_id)
        if row is not None and row.get("status") in {RunStatus.pending.value, RunStatus.running.value}:
            self.read_while_stale.set()
        return row


async def _terminal_run(manager: RunManager, thread_id: str = "thread-eviction") -> str:
    record = await manager.create(thread_id)
    await manager.set_status(record.run_id, RunStatus.success)
    return record.run_id


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
async def test_eviction_waits_for_terminal_persistence_and_retries_after_recovery():
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
