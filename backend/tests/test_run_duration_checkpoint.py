import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from langgraph.checkpoint.memory import InMemorySaver

import deerflow.runtime.runs.worker as worker
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, _persist_run_duration, run_agent


class _YieldingSaver(InMemorySaver):
    async def aget_tuple(self, config):
        checkpoint_tuple = await super().aget_tuple(config)
        await asyncio.sleep(0)
        return checkpoint_tuple

    async def aput(self, config, checkpoint, metadata, new_versions):
        await asyncio.sleep(0)
        return await super().aput(config, checkpoint, metadata, new_versions)


class _AdvancingSaver(InMemorySaver):
    """Inject a title checkpoint between duration read and write."""

    def __init__(self) -> None:
        super().__init__()
        self._reads = 0

    async def aget_tuple(self, config):
        self._reads += 1
        checkpoint_tuple = await super().aget_tuple(config)
        if self._reads != 2 or checkpoint_tuple is None:
            return checkpoint_tuple

        checkpoint = copy.deepcopy(checkpoint_tuple.checkpoint)
        checkpoint["id"] = str(uuid6())
        channel_values = dict(checkpoint["channel_values"])
        channel_values["title"] = "Concurrent title"
        checkpoint["channel_values"] = channel_values
        channel_versions = dict(checkpoint["channel_versions"])
        channel_versions["title"] = 1
        checkpoint["channel_versions"] = channel_versions
        metadata = dict(checkpoint_tuple.metadata)
        metadata.update({"step": metadata["step"] + 1, "source": "update", "writes": {"title": "Concurrent title"}})
        await super().aput(checkpoint_tuple.config, checkpoint, metadata, {"title": 1})
        return await super().aget_tuple(config)


async def _put_checkpoint(
    checkpointer: InMemorySaver,
    *,
    thread_id: str,
    checkpoint_id: str,
    messages: list[object],
    step: int,
    parent_config: dict | None = None,
    inherited_metadata: dict | None = None,
) -> dict:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {"messages": messages}
    checkpoint["channel_versions"] = {"messages": step}
    config = parent_config or {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    metadata = dict(inherited_metadata or {})
    metadata.update({"step": step, "source": "loop", "writes": {"test": {"messages": messages}}, "parents": {}})
    return await checkpointer.aput(config, checkpoint, metadata, {"messages": step})


@pytest.mark.anyio
async def test_run_duration_survives_a_later_checkpoint() -> None:
    checkpointer = InMemorySaver()
    thread_id = "duration-survives"
    messages = [
        HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": "run-1"}),
        AIMessage(id="ai-1", content="Answer"),
    ]
    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id="00000000-0000-6000-8000-000000000001",
        messages=messages,
        step=1,
    )

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=7,
    )

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    duration_checkpoint = await checkpointer.aget_tuple(config)
    assert duration_checkpoint is not None
    persisted_messages = copy.deepcopy(duration_checkpoint.checkpoint["channel_values"]["messages"])
    assert duration_checkpoint.metadata["run_durations"] == {"run-1": 7}

    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id=str(uuid6()),
        messages=persisted_messages,
        step=3,
        parent_config=duration_checkpoint.config,
        inherited_metadata=duration_checkpoint.metadata,
    )

    latest = await checkpointer.aget_tuple(config)
    assert latest is not None
    assert latest.metadata["run_durations"] == {"run-1": 7}


@pytest.mark.anyio
async def test_run_duration_checkpoint_stores_duration_in_metadata_without_rewriting_messages() -> None:
    checkpointer = InMemorySaver()
    thread_id = "duration-metadata"
    messages = [
        HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": "run-1"}),
        AIMessage(id="ai-1", content="Answer"),
    ]
    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id="00000000-0000-6000-8000-000000000001",
        messages=messages,
        step=1,
    )

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=7,
    )

    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    assert latest.metadata["run_durations"] == {"run-1": 7}
    assert latest.checkpoint["channel_versions"]["messages"] == 1
    assert "turn_duration" not in latest.checkpoint["channel_values"]["messages"][1].additional_kwargs


@pytest.mark.anyio
async def test_run_duration_retries_after_intervening_title_checkpoint() -> None:
    checkpointer = _AdvancingSaver()
    thread_id = "duration-title-race"
    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id="00000000-0000-6000-8000-000000000001",
        messages=[
            HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": "run-1"}),
            AIMessage(id="ai-1", content="Answer"),
        ],
        step=1,
    )

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=7,
    )

    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    assert latest.checkpoint["channel_values"]["title"] == "Concurrent title"
    assert latest.metadata["run_durations"] == {"run-1": 7}


@pytest.mark.anyio
async def test_concurrent_run_duration_updates_preserve_both_turns() -> None:
    checkpointer = _YieldingSaver()
    thread_id = "duration-concurrent"
    messages = [
        HumanMessage(id="human-1", content="First", additional_kwargs={"run_id": "run-1"}),
        AIMessage(id="ai-1", content="First answer"),
        HumanMessage(id="human-2", content="Second", additional_kwargs={"run_id": "run-2"}),
        AIMessage(id="ai-2", content="Second answer"),
    ]
    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id="00000000-0000-6000-8000-000000000001",
        messages=messages,
        step=1,
    )

    await asyncio.gather(
        _persist_run_duration(
            checkpointer=checkpointer,
            thread_id=thread_id,
            run_id="run-1",
            duration_seconds=3,
        ),
        _persist_run_duration(
            checkpointer=checkpointer,
            thread_id=thread_id,
            run_id="run-2",
            duration_seconds=5,
        ),
    )

    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    assert latest.metadata["run_durations"] == {"run-1": 3, "run-2": 5}


@pytest.mark.anyio
async def test_run_duration_checkpoint_preserves_parent_lineage() -> None:
    checkpointer = InMemorySaver()
    thread_id = "duration-parent"
    parent_checkpoint_id = "00000000-0000-6000-8000-000000000001"
    await _put_checkpoint(
        checkpointer,
        thread_id=thread_id,
        checkpoint_id=parent_checkpoint_id,
        messages=[
            HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": "run-1"}),
            AIMessage(id="ai-1", content="Answer"),
        ],
        step=1,
    )

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=7,
    )

    history = [checkpoint async for checkpoint in checkpointer.alist({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})]
    assert len(history) == 2
    assert history[0].config["configurable"]["checkpoint_id"] != parent_checkpoint_id
    assert history[0].parent_config == {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": parent_checkpoint_id,
        }
    }


@pytest.mark.anyio
async def test_agent_stream_serializes_with_duration_checkpoint_write() -> None:
    checkpointer = _YieldingSaver()
    run_manager = RunManager()
    record = await run_manager.create("duration-stream-lock")
    await _put_checkpoint(
        checkpointer,
        thread_id=record.thread_id,
        checkpoint_id="00000000-0000-6000-8000-000000000001",
        messages=[
            HumanMessage(
                id="human-1",
                content="Question",
                additional_kwargs={"run_id": record.run_id},
            ),
            AIMessage(id="ai-1", content="Answer"),
        ],
        step=1,
    )
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    duration_task = None
    finished_during_stream = None

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            nonlocal duration_task, finished_during_stream
            duration_task = asyncio.create_task(
                _persist_run_duration(
                    checkpointer=checkpointer,
                    thread_id=record.thread_id,
                    run_id=record.run_id,
                    duration_seconds=9,
                )
            )
            try:
                await asyncio.wait_for(asyncio.shield(duration_task), timeout=0.05)
            except TimeoutError:
                finished_during_stream = False
            else:
                finished_during_stream = True
            yield {"messages": []}

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer),
        agent_factory=factory,
        graph_input={},
        config={},
    )
    assert duration_task is not None
    await duration_task

    assert finished_during_stream is False


@pytest.mark.anyio
async def test_agent_stream_allows_graph_goal_state_access() -> None:
    """A graph node may acquire the goal lock while a run is streaming."""
    checkpointer = InMemorySaver()
    run_manager = RunManager()
    record = await run_manager.create("duration-stream-goal-lock")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            async with goal_thread_lock(record.thread_id):
                yield {"messages": []}

    def factory(*, config):
        return DummyAgent()

    await asyncio.wait_for(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(checkpointer=checkpointer),
            agent_factory=factory,
            graph_input={},
            config={},
        ),
        timeout=0.05,
    )
    assert record.status.value == "success"


@pytest.mark.anyio
async def test_successful_subsecond_run_persists_zero_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    checkpointer = InMemorySaver()
    run_manager = RunManager()
    record = await run_manager.create("duration-zero")
    record.created_at = "2026-01-01T00:00:00+00:00"
    record.updated_at = record.created_at
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    persist_duration = AsyncMock()

    async def set_status(run_id, status, **kwargs):
        record.status = status

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    monkeypatch.setattr(run_manager, "set_status", set_status)
    monkeypatch.setattr(worker, "_persist_run_duration", persist_duration)

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )

    persist_duration.assert_awaited_once_with(
        checkpointer=checkpointer,
        thread_id=record.thread_id,
        run_id=record.run_id,
        duration_seconds=0,
    )
