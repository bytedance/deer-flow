"""Regression tests for bytedance/deer-flow#5009.

``RunManager.cleanup`` existed but had no production caller, so every terminal
run stayed strongly referenced in ``_runs`` / ``_runs_by_thread`` for the
lifetime of the Gateway process. These tests pin the new contract: workers
schedule a delayed eviction for terminal runs when a durable ``RunStore``
backs historical reads, and memory-only managers keep today's semantics.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


async def _terminal_run(manager: RunManager, thread_id: str = "thread-eviction") -> str:
    """Create a run and drive it to a terminal status through the public API."""
    record = await manager.create(thread_id)
    await manager.set_status(record.run_id, RunStatus.success)
    return record.run_id


class TestScheduleTerminalEviction:
    """RunManager.schedule_terminal_eviction contract."""

    @pytest.mark.asyncio
    async def test_memory_only_mode_never_schedules_eviction(self):
        manager = RunManager(store=None)
        run_id = await _terminal_run(manager)

        task = manager.schedule_terminal_eviction(run_id)

        assert task is None
        assert run_id in manager._runs

    @pytest.mark.asyncio
    async def test_durable_store_evicts_terminal_run_after_grace(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction")
        thread_id = record.thread_id
        await manager.set_status(record.run_id, RunStatus.success)

        task = manager.schedule_terminal_eviction(record.run_id, delay=0.01)
        assert task is not None
        await asyncio.sleep(0.05)

        # Evicted from both registries...
        assert record.run_id not in manager._runs
        assert manager._runs_by_thread.get(thread_id) is None
        # ...while history stays readable through the store fallback.
        hydrated = await manager.get(record.run_id)
        assert hydrated is not None
        assert hydrated.status == RunStatus.success
        assert hydrated.store_only is True

    @pytest.mark.asyncio
    async def test_evicted_record_removed_from_thread_listing_fallback_merges_store_rows(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-listing")
        await manager.set_status(record.run_id, RunStatus.success)

        task = manager.schedule_terminal_eviction(record.run_id, delay=0.01)
        assert task is not None
        await asyncio.sleep(0.05)

        listed = await manager.list_by_thread(record.thread_id)
        assert [entry.run_id for entry in listed] == [record.run_id]
        assert all(entry.store_only for entry in listed)

    @pytest.mark.asyncio
    async def test_pending_eviction_task_is_strongly_referenced_then_discarded(self):
        manager = RunManager(store=MemoryRunStore())
        run_id = await _terminal_run(manager)

        task = manager.schedule_terminal_eviction(run_id, delay=3600)
        assert task is not None
        # While the grace sleep is pending the reference set keeps it alive so
        # a GC pass cannot destroy the task mid-delay.
        assert manager._eviction_tasks == {task}

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert not manager._eviction_tasks


class TestWorkerSchedulesTerminalEviction:
    """run_agent schedules the eviction next to the stream-bridge cleanup."""

    @staticmethod
    def _bridge() -> SimpleNamespace:
        return SimpleNamespace(
            publish=AsyncMock(),
            publish_end=AsyncMock(),
            cleanup=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_schedules_eviction_for_terminal_run_when_store_backed(self):
        store = MemoryRunStore()
        run_manager = RunManager(store=store)
        record = await run_manager.create("thread-worker-eviction")

        calls: list[tuple[str, dict]] = []
        run_manager.schedule_terminal_eviction = lambda run_id, **kwargs: calls.append((run_id, kwargs))  # type: ignore[method-assign]

        await run_agent(
            self._bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=MagicMock(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
            stream_modes=["events"],
        )
        await asyncio.sleep(0)

        assert record.status == RunStatus.error
        assert calls == [(record.run_id, {})]

    @pytest.mark.asyncio
    async def test_memory_only_worker_does_not_schedule_eviction(self):
        run_manager = RunManager()
        record = await run_manager.create("thread-worker-no-eviction")

        # Wrap (don't replace) the real method so this pins both that the
        # worker calls it on every terminal path AND that memory-only managers
        # resolve it to a no-op.
        real_method = RunManager.schedule_terminal_eviction
        results: list[object] = []

        def spy(run_id: str, **kwargs):
            result = real_method(run_manager, run_id, **kwargs)
            results.append(result)
            return result

        run_manager.schedule_terminal_eviction = spy  # type: ignore[method-assign]

        await run_agent(
            self._bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=MagicMock(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
            stream_modes=["events"],
        )
        await asyncio.sleep(0)

        assert record.status == RunStatus.error
        assert results == [None]
        assert not run_manager._eviction_tasks
