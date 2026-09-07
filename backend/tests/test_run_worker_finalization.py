"""Worker finalization wires terminal-record eviction into the RunManager.

Issue #5009 called out that the older ``RunManager.cleanup()`` tests did not
cover the normal worker-finalization path. This pins the replacement wiring:
after ``run_agent`` finishes a run, it must call ``RunManager.schedule_cleanup``
for that run id so store-backed managers evict the terminal record. Deleting or
relocating the ``run_manager.schedule_cleanup(run_id)`` call in ``worker.py``
fails this test.

The two cancellation scenarios — the completion hook being cancelled and the
preflight MCP task projection being cancelled — are pinned here as well: the
outer teardown guard must still schedule eviction on those paths.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager, RunRecord, RunStartOutcome
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _FakeAgent:
    """Minimal LangGraph-like graph that completes without producing chunks."""

    def __init__(self) -> None:
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes: list[str] = []
        self.interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        return
        yield  # pragma: no cover (makes this an async generator)


class _SpyRunManager:
    """Run manager stub that records ``schedule_cleanup`` invocations."""

    def __init__(self) -> None:
        self.direct_cleanup_calls: list[tuple[str, dict]] = []
        self.scheduled_cleanup_calls: list[tuple[str, dict]] = []

    async def try_start(self, _run_id: str) -> RunStartOutcome:
        return RunStartOutcome.started

    async def wait_for_prior_finalizing(self, *_args, **_kwargs) -> None:
        return None

    async def has_later_run(self, *_args, **_kwargs) -> bool:
        return False

    async def has_later_started_run(self, *_args, **_kwargs) -> bool:
        return False

    async def set_status(self, *_args, **_kwargs) -> None:
        return None

    async def set_status_if_not_cancelled(self, *_args, **_kwargs) -> None:
        await self.set_status(*_args, **_kwargs)
        return None

    async def update_model_name(self, *_args, **_kwargs) -> None:
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        return None

    async def cleanup(self, run_id: str, **kwargs) -> None:
        self.direct_cleanup_calls.append((run_id, kwargs))
        return None

    def schedule_cleanup(self, run_id: str, **kwargs):
        self.scheduled_cleanup_calls.append((run_id, kwargs))
        return None


class _FakeBridge:
    def __init__(self, *, fail_publish_end: bool = False) -> None:
        self.fail_publish_end = fail_publish_end

    async def publish(self, _run_id, event, payload) -> None:
        return None

    async def publish_end(self, _run_id) -> None:
        if self.fail_publish_end:
            raise RuntimeError("publish_end failed")
        return None

    async def cleanup(self, _run_id, *, delay: int = 0) -> None:
        return None


@pytest.mark.asyncio
async def test_run_agent_finalization_schedules_eviction():
    """A completed run schedules terminal-record eviction on finalization."""
    run_manager = _SpyRunManager()
    record = RunRecord(
        run_id="run-finalize",
        thread_id="thread-finalize",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        run_manager,
        record,
        ctx=ctx,
        agent_factory=lambda config: _FakeAgent(),
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-finalize"}},
    )
    await asyncio.sleep(0)

    scheduled_ids = [run_id for run_id, _kwargs in run_manager.scheduled_cleanup_calls]
    assert scheduled_ids == ["run-finalize"], f"run_agent finalization must schedule eviction for the run exactly once; got {run_manager.scheduled_cleanup_calls!r}"
    assert run_manager.direct_cleanup_calls == []


@pytest.mark.asyncio
async def test_run_agent_finalization_schedules_eviction_when_publish_end_fails():
    """Outer cleanup must schedule eviction even when terminal publication fails."""
    run_manager = _SpyRunManager()
    record = RunRecord(
        run_id="run-publish-end-fails",
        thread_id="thread-finalize",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    with pytest.raises(RuntimeError, match="publish_end failed"):
        await run_agent(
            _FakeBridge(fail_publish_end=True),
            run_manager,
            record,
            ctx=ctx,
            agent_factory=lambda config: _FakeAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": "thread-finalize"}},
        )
    await asyncio.sleep(0)

    scheduled_ids = [run_id for run_id, _kwargs in run_manager.scheduled_cleanup_calls]
    assert scheduled_ids == ["run-publish-end-fails"]
    assert run_manager.direct_cleanup_calls == []


@pytest.mark.asyncio
async def test_run_agent_finalization_schedules_eviction_when_completion_hook_is_cancelled(monkeypatch):
    """Eviction is still scheduled when the completion hook is cancelled."""
    import deerflow.runtime.runs.worker as worker_module
    from deerflow.runtime.journal import RunJournal

    class CleanupTrackingRunManager(RunManager):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_calls: list[tuple[str, float]] = []

        def schedule_cleanup(self, run_id: str, *, delay: float = 300) -> None:
            self.cleanup_calls.append((run_id, delay))

    completion_hook_entered = asyncio.Event()

    async def block_completion(_record) -> None:
        completion_hook_entered.set()
        await asyncio.Event().wait()

    run_manager = CleanupTrackingRunManager()
    record = await run_manager.create("thread-terminal-completion-cancelled")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    schedule_collection = MagicMock()
    monkeypatch.setattr(worker_module, "_schedule_terminal_cycle_collection", schedule_collection)
    captured: dict[str, Any] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, stream_mode, subgraphs
            callbacks = config.get("callbacks") or []
            captured["journal"] = next(callback for callback in callbacks if isinstance(callback, RunJournal))
            yield {"messages": []}

    config: dict[str, Any] = {}
    run_task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                event_store=MemoryRunEventStore(),
                on_run_completed=block_completion,
            ),
            agent_factory=lambda **_kwargs: DummyAgent(),
            graph_input={},
            config=config,
        )
    )
    await asyncio.wait_for(completion_hook_entered.wait(), timeout=1)
    run_task.cancel("completion hook interrupted")
    with pytest.raises(asyncio.CancelledError, match="completion hook interrupted"):
        await run_task
    await asyncio.sleep(0)

    journal = captured["journal"]
    assert "__pregel_runtime" not in config["configurable"]
    assert journal not in config["callbacks"]
    assert journal._closed is True
    assert journal._store is None
    assert record.finalizing is False
    bridge.publish_end.assert_awaited_once_with(record.run_id)
    bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
    assert run_manager.cleanup_calls == [(record.run_id, 300)]
    schedule_collection.assert_called_once_with()


@pytest.mark.asyncio
async def test_run_agent_finalization_schedules_eviction_when_mcp_task_projection_is_cancelled():
    """Eviction is still scheduled when the preflight MCP projection is cancelled."""

    class CleanupTrackingRunManager(RunManager):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_calls: list[tuple[str, float]] = []

        def schedule_cleanup(self, run_id: str, *, delay: float = 300) -> None:
            self.cleanup_calls.append((run_id, delay))

    projection_started = asyncio.Event()

    class BlockingTaskRepository:
        async def list_by_thread(self, thread_id, *, user_id, limit):
            del thread_id, user_id, limit
            projection_started.set()
            await asyncio.Event().wait()

    run_manager = CleanupTrackingRunManager()
    record = await run_manager.create("thread-mcp-projection-cancelled", user_id="alice")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    agent_factory = MagicMock(side_effect=AssertionError("cancelled preflight built the agent"))
    run_task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                event_store=MemoryRunEventStore(),
                mcp_task_repo=BlockingTaskRepository(),
            ),
            agent_factory=agent_factory,
            graph_input={},
            config={},
        )
    )
    await asyncio.wait_for(projection_started.wait(), timeout=1)

    run_task.cancel("MCP projection interrupted")
    await run_task
    await asyncio.sleep(0)

    agent_factory.assert_not_called()
    assert record.status == RunStatus.interrupted
    assert record.finalizing is False
    bridge.publish_end.assert_awaited_once_with(record.run_id)
    bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
    assert run_manager.cleanup_calls == [(record.run_id, 300)]
