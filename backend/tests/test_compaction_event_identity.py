"""A compaction event names the task, run and thread it happened in.

The host already holds the live task store when summarization runs: the summary
system call is observed with it. A compaction observer that cannot name its task
can only correlate a compaction with the run that produced it by matching hashes
across sessions, which is unreliable, so the host hands the observer the store it
already has and copies the seeded ``TaskInfo`` identity onto the event.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, CompactionEvent, ExtensionData, TaskInfo
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.extensions import notify
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.runtime import context_compaction
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _CompactionRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[ExtensionData, CompactionEvent]] = []
        self._arrived = asyncio.Event()

    async def on_context_compacted(self, app_store, task_store, event):
        self.calls.append((task_store, event))
        self._arrived.set()

    async def received(self) -> list[tuple[ExtensionData, CompactionEvent]]:
        # Dispatch is fire-and-forget onto the notify loop, so the observer may
        # still be pending when the compaction call returns.
        await asyncio.wait_for(self._arrived.wait(), 5)
        return self.calls


class _LifecycleRecorder:
    def __init__(self) -> None:
        self.infos: list[TaskInfo] = []

    async def on_task_start(self, app_store, task_store, info):
        self.infos.append(info)

    async def on_task_stop(self, app_store, task_store, info, outcome):
        return None


def _extensions(observer, *, lifecycle=None):
    registry = ExtensionRegistry()
    with registry.attributed_to("identity:install"):
        registry.context_compaction_observer(observer)
        if lifecycle is not None:
            registry.task_lifecycle(lifecycle)
    return registry.build()


def _messages() -> list:
    return [
        HumanMessage(content="user-1"),
        AIMessage(content="assistant-1"),
        HumanMessage(content="user-2"),
        AIMessage(content="assistant-2"),
    ]


def _middleware(extensions) -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed summary"))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        extensions=extensions,
    )


def _identity(event: CompactionEvent) -> tuple[str | None, str | None, str | None]:
    return event.task_id, event.run_id, event.thread_id


# --- The contract stays additive -------------------------------------------


def test_an_event_built_the_old_way_still_constructs_without_identity():
    keyword = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1",),
        output_content_hash="h2",
        compacted_message_count=1,
        kept_message_count=1,
    )
    positional = CompactionEvent("summarization", "1", ("h1",), "h2", 1, 1)

    assert keyword == positional
    assert _identity(keyword) == (None, None, None)


# --- Dispatch ----------------------------------------------------------------


class TestNotifyHandsOverTheLiveStore:
    @pytest.mark.asyncio
    async def test_a_live_store_reaches_the_observer_and_names_the_event(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        store = ExtensionData("run-1")
        store.set(TaskInfo(task_id="run-1", run_id="run-1", thread_id="thread-1", kind="lead"))

        notify.notify_context_compacted(CompactionEvent("summarization", "1", (), "h", 0, 0), extensions=_extensions(observer), task_store=store)

        [(received_store, event)] = await observer.received()
        assert received_store is store
        assert _identity(event) == ("run-1", "run-1", "thread-1")

    @pytest.mark.asyncio
    async def test_a_store_without_task_info_is_handed_over_without_identity(self, monkeypatch):
        # A subagent with no parent run allocates a store but never seeds TaskInfo.
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        store = ExtensionData("sub-1")

        notify.notify_context_compacted(CompactionEvent("summarization", "1", (), "h", 0, 0), extensions=_extensions(observer), task_store=store)

        [(received_store, event)] = await observer.received()
        assert received_store is store
        assert _identity(event) == (None, None, None)

    @pytest.mark.asyncio
    async def test_no_store_falls_back_to_detached(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()

        notify.notify_context_compacted(CompactionEvent("summarization", "1", (), "h", 0, 0), extensions=_extensions(observer))

        [(received_store, event)] = await observer.received()
        assert received_store.scope_id == "detached"
        assert _identity(event) == (None, None, None)


# --- End to end through the hosts that allocate the store -----------------


class _CompactingLeadAgent:
    """Stands in for the lead graph: runs the real summarization middleware once
    against the runtime context ``run_agent`` hands the graph."""

    def __init__(self, middleware: DeerFlowSummarizationMiddleware) -> None:
        self.middleware = middleware
        self.task_store: ExtensionData | None = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        context = (config or {}).get("context")
        self.task_store = context.get(EXTENSION_TASK_STORE_KEY)
        assert await self.middleware.abefore_model({"messages": _messages()}, SimpleNamespace(context=context)) is not None
        yield {"messages": []}


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


async def _run_lead(extensions, agent):
    manager = RunManager()
    record = await manager.create("thread-identity", assistant_id="custom-agent")
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
    return record


class TestLeadRunCompaction:
    @pytest.mark.asyncio
    async def test_async_compaction_names_the_run_it_happened_in(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        lifecycle = _LifecycleRecorder()
        extensions = _extensions(observer, lifecycle=lifecycle)
        agent = _CompactingLeadAgent(_middleware(extensions))

        record = await _run_lead(extensions, agent)

        [(store, event)] = await observer.received()
        [info] = lifecycle.infos
        assert store is agent.task_store
        assert store.scope_id == info.task_id == record.run_id
        assert store.get(TaskInfo) == info
        assert _identity(event) == (info.task_id, info.run_id, info.thread_id) == (record.run_id, record.run_id, "thread-identity")

    @pytest.mark.asyncio
    async def test_identity_does_not_depend_on_a_lifecycle_contributor(self, monkeypatch):
        """Registering a compaction observer alone allocates the store; the host
        must not drop the identity just because no lifecycle contributor asked."""
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        extensions = _extensions(observer)
        assert extensions.needs_task_store and not extensions.has_task_lifecycle
        agent = _CompactingLeadAgent(_middleware(extensions))

        record = await _run_lead(extensions, agent)

        [(store, event)] = await observer.received()
        assert store is agent.task_store
        assert store.scope_id == record.run_id
        assert store.get(TaskInfo) == TaskInfo(
            task_id=record.run_id,
            run_id=record.run_id,
            thread_id="thread-identity",
            kind="lead",
            agent_name="custom-agent",
        )
        assert _identity(event) == (record.run_id, record.run_id, "thread-identity")


class TestSyncCompaction:
    @pytest.mark.asyncio
    async def test_sync_compaction_carries_the_live_task_identity(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        store = ExtensionData("run-sync")
        info = TaskInfo(task_id="run-sync", run_id="run-sync", thread_id="thread-sync", kind="lead")
        store.set(info)
        runtime = SimpleNamespace(context={"thread_id": "thread-sync", EXTENSION_TASK_STORE_KEY: store})
        middleware = _middleware(_extensions(observer))

        # The synchronous graph path runs before_model off the serving loop.
        result = await asyncio.to_thread(middleware.before_model, {"messages": _messages()}, runtime)

        assert result is not None
        [(received_store, event)] = await observer.received()
        assert received_store is store
        assert _identity(event) == (info.task_id, info.run_id, info.thread_id)


class _Accessor:
    def __init__(self, values: dict) -> None:
        self.snapshot = SimpleNamespace(
            values=values,
            config={"configurable": {"thread_id": "thread-manual", "checkpoint_id": "ckpt-old", "checkpoint_ns": ""}},
            metadata={"step": 4},
        )

    async def aget(self, _config):
        return self.snapshot

    async def aget_tuple(self, _config):
        return SimpleNamespace(checkpoint={"channel_values": dict(self.snapshot.values)})

    async def aupdate(self, config, values, *, as_node=None):
        return {"configurable": {"thread_id": "thread-manual", "checkpoint_ns": "", "checkpoint_id": "ckpt-compacted"}}


class TestManualCompaction:
    @pytest.mark.asyncio
    async def test_manual_compact_outside_any_run_falls_back_to_a_detached_store(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify_loop", asyncio.get_running_loop())
        observer = _CompactionRecorder()
        middleware = _middleware(_extensions(observer))
        monkeypatch.setattr(context_compaction, "_create_compaction_middleware", lambda **_kwargs: middleware)

        result = await context_compaction.compact_thread_context(_Accessor({"messages": _messages()}), "thread-manual", app_config=SimpleNamespace())

        assert result.compacted
        [(store, event)] = await observer.received()
        assert store.scope_id == "detached"
        assert store.get(TaskInfo) is None
        assert _identity(event) == (None, None, None)
