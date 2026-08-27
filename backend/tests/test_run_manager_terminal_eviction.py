"""Regression tests for bytedance/deer-flow#5009.

``RunManager.cleanup`` existed but had no production caller, so every terminal
run stayed strongly referenced in ``_runs`` / ``_runs_by_thread`` for the
lifetime of the Gateway process. These tests pin the new contract: workers
schedule a delayed eviction for terminal runs when a durable ``RunStore``
backs historical reads, and memory-only managers keep today's semantics.

The hardening cases pin the PR-review follow-ups on top of #5009:

- a rehydrated *terminal* idempotent reuse must not re-enter the in-memory
  registries (no eviction is scheduled for it, so it would be retained for
  the process lifetime);
- removal is gated on a verified durable terminal row, with one repair
  cycle and deliberate retention when the store cannot confirm terminal
  state;
- the worker schedules post-terminal cleanup even when ``publish_end``
  raises.
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


async def _forget_local_record(manager: RunManager, run_id: str, thread_id: str) -> None:
    """Drop the local registries entry so the next admission rehydrates from the store."""
    async with manager._lock:
        manager._runs.pop(run_id, None)
        manager._unindex_run_locked(run_id, thread_id)


class TestIdempotentReuseDoesNotReindexTerminalRecords:
    """Terminal records rehydrated by idempotent retries must not leak in memory."""

    @pytest.mark.asyncio
    async def test_terminal_reuse_returns_record_without_reindexing(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create_or_reject("thread-idem-terminal", user_id="user-a", idempotency_key="idem-term-1")
        await manager.set_status(record.run_id, RunStatus.success)
        await _forget_local_record(manager, record.run_id, "thread-idem-terminal")

        reused = await manager.create_or_reject("thread-idem-terminal", user_id="user-a", idempotency_key="idem-term-1")

        assert reused.run_id == record.run_id
        assert reused.idempotency_reused is True
        assert reused.status == RunStatus.success
        # No eviction is ever scheduled for a reused response (the Gateway
        # returns immediately), so indexing a terminal record here would pin
        # it for the process lifetime. History stays reachable via the store.
        assert record.run_id not in manager._runs
        assert manager._runs_by_thread.get("thread-idem-terminal") is None

        hydrated = await manager.get(record.run_id)
        assert hydrated is not None
        assert hydrated.status == RunStatus.success
        assert hydrated.store_only is True

    @pytest.mark.asyncio
    async def test_inflight_reuse_still_indexed_for_tracking(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        await store.put(
            "run-peer-inflight",
            thread_id="thread-idem-inflight",
            assistant_id=None,
            status="running",
            operation_kind="run",
            multitask_strategy="reject",
            metadata={},
            kwargs={},
            created_at="2026-01-01T00:00:00+00:00",
            user_id="user-a",
            owner_worker_id="worker-peer",
            lease_expires_at="2099-01-01T00:00:00+00:00",
            idempotency_key="idem-inflight-1",
        )

        reused = await manager.create_or_reject("thread-idem-inflight", user_id="user-a", idempotency_key="idem-inflight-1")

        # A cross-worker inflight row still needs same-process tracking.
        assert reused.idempotency_reused is True
        assert reused.status == RunStatus.running
        assert "run-peer-inflight" in manager._runs


class _GatedStore(MemoryRunStore):
    """Memory store whose reads can be made to fail, simulating an outage."""

    def __init__(self):
        super().__init__()
        self.fail_get = False

    async def get(self, run_id, *args, **kwargs):
        if self.fail_get:
            raise RuntimeError("store unavailable")
        return await super().get(run_id, *args, **kwargs)


class TestEvictionGatedOnVerifiedDurableTerminalState:
    """cleanup must not remove the local record without durable proof."""

    @pytest.mark.asyncio
    async def test_nonterminal_store_row_blocks_eviction_until_verified(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-gate")
        await manager.set_status(record.run_id, RunStatus.success)
        # Simulate a failed terminal persistence: only memory knows the truth.
        store._runs[record.run_id]["status"] = "pending"

        task = manager.schedule_terminal_eviction(record.run_id, delay=0.01)
        assert task is not None
        await asyncio.sleep(0.08)

        # All bounded verification attempts failed → deliberate retention.
        assert record.run_id in manager._runs
        assert store._runs[record.run_id]["status"] == "pending"

        # Once the store recovers the terminal fact, a fresh eviction passes.
        store._runs[record.run_id]["status"] = "success"
        await manager.cleanup(record.run_id, delay=0)
        assert record.run_id not in manager._runs

    @pytest.mark.asyncio
    async def test_store_read_failure_retains_record(self):
        store = _GatedStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-outage")
        await manager.set_status(record.run_id, RunStatus.success)

        store.fail_get = True
        try:
            await manager.cleanup(record.run_id, delay=0, verify_attempts=1)
        finally:
            store.fail_get = False

        assert record.run_id in manager._runs
        assert await manager.get(record.run_id) is not None

    @pytest.mark.asyncio
    async def test_missing_durable_row_is_repaired_then_evicted(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-repair")
        await manager.set_status(record.run_id, RunStatus.success)
        del store._runs[record.run_id]  # simulate lost initial persistence

        await manager.cleanup(record.run_id, delay=0)

        # The authoritative local snapshot repaired the missing row first...
        repaired = store._runs[record.run_id]
        assert repaired["status"] == "success"
        # ...so the verified removal is safe.
        assert record.run_id not in manager._runs

    @pytest.mark.asyncio
    async def test_ownership_lost_record_is_never_repaired(self):
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-peer")
        await manager.set_status(record.run_id, RunStatus.success)
        record.ownership_lost = True  # a peer owns this run's durable fate now
        del store._runs[record.run_id]

        await manager.cleanup(record.run_id, delay=0, verify_attempts=1)

        # No repair upsert could resurrect state under someone else's lease,
        # and without verification the local record is retained.
        assert record.run_id not in store._runs
        assert record.run_id in manager._runs

    @pytest.mark.asyncio
    async def test_thin_terminal_row_is_repaired_from_local_snapshot_before_eviction(self):
        """A terminal row missing the completion payload must not lose it (#5011 follow-up).

        ``set_status`` and ``update_run_completion`` are independent persistence
        paths: when only the status write lands, the row is terminal yet thinner
        than the local record — and eviction would drop token usage, message
        counts, and the convenience fields forever.
        """
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-thin")
        await manager.set_status(record.run_id, RunStatus.success)
        # Enrich only the local record, as the worker would have via
        # update_run_completion had that store write failed silently.
        record.total_tokens = 1234
        record.total_output_tokens = 500
        record.message_count = 7
        record.last_ai_message = "final answer"

        await manager.cleanup(record.run_id, delay=0)

        assert record.run_id not in manager._runs
        repaired = store._runs[record.run_id]
        assert repaired["total_tokens"] == 1234
        assert repaired["total_output_tokens"] == 500
        assert repaired["message_count"] == 7
        assert repaired["last_ai_message"] == "final answer"

    @pytest.mark.asyncio
    async def test_unrepairable_completion_gap_retains_record(self):
        """When the completion columns cannot be fixed, eviction is withheld."""

        class NoCompletionStore(MemoryRunStore):
            async def update_run_completion(self, run_id, *, status, **kwargs):
                raise RuntimeError("completion write down")

        broken = NoCompletionStore()
        manager = RunManager(store=broken)
        record = await manager.create("thread-eviction-unrepairable")
        await manager.set_status(record.run_id, RunStatus.success)
        record.total_tokens = 99

        await manager.cleanup(record.run_id, delay=0, verify_attempts=1)

        assert record.run_id in manager._runs
        assert "total_tokens" not in broken._runs[record.run_id]

    @pytest.mark.asyncio
    async def test_agreeing_completion_snapshot_evicts_normally(self):
        """Rows already carrying the full snapshot need no extra retention."""
        store = MemoryRunStore()
        manager = RunManager(store=store)
        record = await manager.create("thread-eviction-full")
        await manager.set_status(record.run_id, RunStatus.success)
        record.total_tokens = 10
        await manager.update_run_completion(
            record.run_id,
            status=RunStatus.success.value,
            total_input_tokens=4,
            total_output_tokens=6,
            total_tokens=10,
        )

        await manager.cleanup(record.run_id, delay=0)

        assert record.run_id not in manager._runs
        assert store._runs[record.run_id]["total_tokens"] == 10


class TestWorkerSchedulesEvictionWhenPublishEndFails:
    """A failing END marker must still schedule post-terminal cleanup."""

    @staticmethod
    def _failing_bridge() -> SimpleNamespace:
        return SimpleNamespace(
            publish=AsyncMock(),
            publish_end=AsyncMock(side_effect=RuntimeError("redis down")),
            cleanup=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_publish_end_failure_still_schedules_cleanup_and_eviction(self):
        store = MemoryRunStore()
        run_manager = RunManager(store=store)
        record = await run_manager.create("thread-publish-end-failure")

        evictions: list[tuple[str, dict]] = []
        run_manager.schedule_terminal_eviction = lambda run_id, **kwargs: evictions.append((run_id, kwargs))  # type: ignore[method-assign]

        bridge = self._failing_bridge()
        with pytest.raises(RuntimeError, match="redis down"):
            await run_agent(
                bridge,
                run_manager,
                record,
                ctx=RunContext(checkpointer=None),
                agent_factory=MagicMock(),
                graph_input={"messages": []},
                config={"configurable": {"thread_id": record.thread_id}},
                stream_modes=["events"],
            )
        await asyncio.sleep(0)

        # The original publish-end exception keeps propagating, but both
        # post-terminal schedulers ran inside the finally block.
        assert record.status == RunStatus.error
        assert evictions == [(record.run_id, {})]
        bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
