"""Task lifecycle extension notifications and outcome classification."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    ExtensionData,
    TaskInfo,
    TaskOutcome,
)
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.extensions.notify import (
    lead_task_id,
    lead_task_outcome,
    notify_task_start,
    notify_task_stop,
    subagent_task_outcome,
)
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    async def on_task_start(self, app_store, task_store, info):
        self.events.append(("start", info.task_id, info.kind))

    async def on_task_stop(self, app_store, task_store, info, outcome):
        self.events.append(("stop", info.task_id, outcome.value))


def _extensions(*contributors):
    registry = ExtensionRegistry()
    for index, contributor in enumerate(contributors):
        with registry.attributed_to(f"ext{index}:install"):
            registry.task_lifecycle(contributor)
    return registry.build()


def _info(task_id: str = "task-1", kind: str = "lead") -> TaskInfo:
    return TaskInfo(task_id=task_id, run_id="run-1", thread_id="thread-1", kind=kind)


def test_task_identity_and_outcome_classification_are_explicit():
    assert lead_task_id("run-abc") == "run-abc"
    assert lead_task_outcome(aborted=True, succeeded=True) is TaskOutcome.ABORTED
    assert lead_task_outcome(aborted=False, succeeded=True) is TaskOutcome.COMPLETED
    assert lead_task_outcome(aborted=False, succeeded=False) is TaskOutcome.FAILED
    assert subagent_task_outcome(cancelled=True, succeeded=True) is TaskOutcome.ABORTED
    assert subagent_task_outcome(cancelled=False, succeeded=True) is TaskOutcome.COMPLETED
    assert subagent_task_outcome(cancelled=False, succeeded=False) is TaskOutcome.FAILED


@pytest.mark.asyncio
async def test_start_and_stop_reach_contributors_in_order():
    first = _Recorder()
    second = _Recorder()
    extensions = _extensions(first, second)
    store = ExtensionData("task-1")

    await notify_task_start(extensions, store, _info())
    await notify_task_stop(extensions, store, _info(), TaskOutcome.COMPLETED)

    assert first.events == [("start", "task-1", "lead"), ("stop", "task-1", "completed")]
    assert second.events == first.events


@pytest.mark.asyncio
async def test_one_malformed_or_failing_contributor_does_not_stop_the_rest():
    class _WrongShape:
        def on_task_start(self, app_store, task_store, info):
            raise RuntimeError("sync boom")

    survivor = _Recorder()
    await notify_task_start(
        _extensions(_WrongShape(), survivor),
        ExtensionData("task-1"),
        _info(),
    )

    assert survivor.events == [("start", "task-1", "lead")]


@pytest.mark.asyncio
async def test_notification_timeout_is_one_shared_budget():
    reached: list[str] = []

    class _Hang:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            reached.append("hang")
            await asyncio.sleep(10)

    class _Starved:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            reached.append("starved")

    loop = asyncio.get_running_loop()
    started = loop.time()
    await notify_task_stop(
        _extensions(_Hang(), _Starved()),
        ExtensionData("task-1"),
        _info(),
        TaskOutcome.COMPLETED,
        timeout=0.02,
    )

    assert reached == ["hang"]
    assert loop.time() - started < 1


@pytest.mark.asyncio
async def test_budget_exhaustion_mid_hook_logs_a_warning_not_a_traceback(caplog):
    # Spending the shared budget mid-hook is the same expected operational
    # condition as the pre-hook skip, not a hook failure.
    class _Hang:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            await asyncio.sleep(10)

    with caplog.at_level(logging.WARNING, logger="deerflow.extensions.notify"):
        await notify_task_stop(
            _extensions(_Hang()),
            ExtensionData("task-1"),
            _info(),
            TaskOutcome.COMPLETED,
            timeout=0.02,
        )

    records = [record for record in caplog.records if record.name == "deerflow.extensions.notify"]
    assert [record.levelno for record in records] == [logging.WARNING]
    assert "timed out" in records[0].getMessage()
    assert "task-1" in records[0].getMessage()
    assert records[0].exc_info is None


@pytest.mark.asyncio
async def test_contributor_timeout_error_before_budget_is_a_hook_failure(caplog):
    # A TimeoutError the contributor raises on its own is not budget
    # exhaustion; it stays classified as a hook failure.
    class _TimedOut:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            raise TimeoutError("the contributor's own downstream call timed out")

    with caplog.at_level(logging.WARNING, logger="deerflow.extensions.notify"):
        await notify_task_stop(
            _extensions(_TimedOut()),
            ExtensionData("task-1"),
            _info(),
            TaskOutcome.COMPLETED,
            timeout=30,
        )
        # And with no notification budget at all.
        await notify_task_stop(
            _extensions(_TimedOut()),
            ExtensionData("task-1"),
            _info(),
            TaskOutcome.COMPLETED,
        )

    records = [record for record in caplog.records if record.name == "deerflow.extensions.notify"]
    assert [record.levelno for record in records] == [logging.ERROR, logging.ERROR]
    assert all("failed" in record.getMessage() for record in records)


class _RunRecorder(_Recorder):
    def __init__(self) -> None:
        super().__init__()
        self.start_infos: list[TaskInfo] = []
        self.start_stores: list[ExtensionData] = []

    async def on_task_start(self, app_store, task_store, info):
        self.start_infos.append(info)
        self.start_stores.append(task_store)
        await super().on_task_start(app_store, task_store, info)


class _OkAgent:
    def __init__(self) -> None:
        self.runtime_context = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        self.runtime_context = (config or {}).get("context")
        yield {"messages": []}


class _BoomAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        raise RuntimeError("agent exploded")
        yield  # pragma: no cover


def _bridge():
    return SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_run_agent_uses_the_run_bound_snapshot_for_lifecycle_and_task_store():
    recorder = _RunRecorder()
    extensions = _extensions(recorder)
    manager = RunManager()
    record = await manager.create("thread-ext", assistant_id="custom-agent")
    agent = _OkAgent()

    await run_agent(
        _bridge(),
        manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver(), extensions=extensions),
        agent_factory=lambda *, config: agent,
        graph_input={},
        config={},
    )

    assert record.status is RunStatus.success
    assert recorder.events == [
        ("start", record.run_id, "lead"),
        ("stop", record.run_id, "completed"),
    ]
    assert recorder.start_infos[0].agent_name == "custom-agent"
    assert agent.runtime_context[EXTENSION_TASK_STORE_KEY] is recorder.start_stores[0]


@pytest.mark.asyncio
async def test_run_agent_reports_failed_and_skips_runs_that_never_started():
    recorder = _RunRecorder()
    extensions = _extensions(recorder)
    manager = RunManager()

    failed = await manager.create("thread-failed")
    await run_agent(
        _bridge(),
        manager,
        failed,
        ctx=RunContext(checkpointer=InMemorySaver(), extensions=extensions),
        agent_factory=lambda *, config: _BoomAgent(),
        graph_input={},
        config={},
    )
    assert failed.status is RunStatus.error
    assert recorder.events[-1] == ("stop", failed.run_id, "failed")

    skipped = await manager.create("thread-skipped")
    await manager.cancel(skipped.run_id)
    before = list(recorder.events)
    await run_agent(
        _bridge(),
        manager,
        skipped,
        ctx=RunContext(checkpointer=InMemorySaver(), extensions=extensions),
        agent_factory=lambda *, config: _OkAgent(),
        graph_input={},
        config={},
    )
    assert recorder.events == before


@pytest.mark.asyncio
async def test_lead_stop_runs_after_completion_hook_and_before_stream_end():
    events: list[str] = []
    manager = RunManager()
    record = await manager.create("thread-order")
    bridge = _bridge()
    bridge.publish_end.side_effect = lambda run_id: events.append("stream-end")

    class _OrderingRecorder(_RunRecorder):
        async def on_task_stop(self, app_store, task_store, info, outcome):
            assert record.finalizing is True
            assert bridge.publish_end.await_count == 0
            events.append("task-stop")
            await super().on_task_stop(
                app_store,
                task_store,
                info,
                outcome,
            )

    async def _on_completed(_record):
        events.append("run-completed")

    class _CancelledAgent:
        async def astream(
            self,
            graph_input,
            config=None,
            stream_mode=None,
            subgraphs=False,
        ):
            raise asyncio.CancelledError()
            yield  # pragma: no cover

    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(
            checkpointer=InMemorySaver(),
            extensions=_extensions(_OrderingRecorder()),
            on_run_completed=_on_completed,
        ),
        agent_factory=lambda *, config: _CancelledAgent(),
        graph_input={},
        config={},
    )

    assert events == ["run-completed", "task-stop", "stream-end"]
    assert record.finalizing is False


@pytest.mark.asyncio
async def test_lead_stop_interrupt_is_deferred_until_final_cleanup():
    class _StopInterrupt(BaseException):
        pass

    class _InterruptingRecorder(_RunRecorder):
        async def on_task_stop(self, app_store, task_store, info, outcome):
            await super().on_task_stop(
                app_store,
                task_store,
                info,
                outcome,
            )
            raise _StopInterrupt("shutdown")

    manager = RunManager()
    record = await manager.create("thread-interrupt")
    bridge = _bridge()

    with pytest.raises(_StopInterrupt, match="shutdown"):
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=InMemorySaver(),
                extensions=_extensions(_InterruptingRecorder()),
            ),
            agent_factory=lambda *, config: _OkAgent(),
            graph_input={},
            config={},
        )

    assert record.finalizing is False
    bridge.publish_end.assert_awaited_once_with(record.run_id)


@pytest.mark.asyncio
async def test_contributor_raising_cancellederror_cannot_interrupt_run_cleanup():
    # Fail-open is decided by origin, not base class: a contributor that lets a
    # CancelledError escape must not skip its successors, and must not reach the
    # worker's deferred-interrupt path, which would end an otherwise successful
    # run as cancelled.
    class _Rogue:
        async def on_task_stop(self, app_store, task_store, info, outcome):
            raise asyncio.CancelledError()

    survivor = _RunRecorder()
    manager = RunManager()
    record = await manager.create("thread-rogue-stop")
    bridge = _bridge()

    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(
            checkpointer=InMemorySaver(),
            extensions=_extensions(_Rogue(), survivor),
        ),
        agent_factory=lambda *, config: _OkAgent(),
        graph_input={},
        config={},
    )

    assert record.status is RunStatus.success
    assert survivor.events[-1] == ("stop", record.run_id, "completed")
    assert record.finalizing is False
    bridge.publish_end.assert_awaited_once_with(record.run_id)


@pytest.mark.asyncio
async def test_lead_stop_cancellation_is_deferred_rather_than_swallowed():
    # CancelledError derives from BaseException, so the non-fatal `except
    # Exception` guard around the stop notification must not absorb it. The
    # stimulus has to be a genuine cancellation of the run task — a contributor
    # raising CancelledError is contained as an extension failure instead.
    entered = asyncio.Event()

    class _SlowRecorder(_RunRecorder):
        async def on_task_stop(self, app_store, task_store, info, outcome):
            await super().on_task_stop(
                app_store,
                task_store,
                info,
                outcome,
            )
            entered.set()
            await asyncio.sleep(10)

    manager = RunManager()
    record = await manager.create("thread-cancel-stop")
    bridge = _bridge()

    task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=InMemorySaver(),
                extensions=_extensions(_SlowRecorder()),
            ),
            agent_factory=lambda *, config: _OkAgent(),
            graph_input={},
            config={},
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert record.finalizing is False
    bridge.publish_end.assert_awaited_once_with(record.run_id)
