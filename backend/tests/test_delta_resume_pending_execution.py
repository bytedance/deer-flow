"""Historical delta resume must not erase a paused tool task (#7438)."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, _linearize_delta_checkpoint_resume, run_agent

pytestmark = pytest.mark.anyio
THREAD_ID = "pending-delta-resume"
FINAL_ANSWER = "Probe completed."


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def offline_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


@pytest.fixture(params=["memory", "sqlite"])
async def checkpointer(request, tmp_path):
    if request.param == "memory":
        yield InMemorySaver()
    else:
        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
            await saver.setup()
            yield saver


class _ProbeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content=FINAL_ANSWER, id="final")
        elif sum(isinstance(message, HumanMessage) for message in messages) >= 2:
            answer = AIMessage(content="", id="call", tool_calls=[{"name": "probe", "args": {}, "id": "probe-call", "type": "tool_call"}])
        else:
            answer = AIMessage(content="First answer.", id="first-answer")
        return ChatResult(generations=[ChatGeneration(message=answer)])


def _config(mode, checkpoint_id=None):
    config = {"configurable": {"thread_id": THREAD_ID, "checkpoint_ns": ""}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    inject_checkpoint_mode(config, mode)
    return config


async def _worker(graph, saver, manager, mode, config, graph_input, **kwargs):
    record = await manager.create(THREAD_ID)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(checkpointer=saver, checkpoint_channel_mode=mode),
        agent_factory=lambda **_kwargs: graph,
        graph_input=graph_input,
        config=config,
        stream_modes=["values"],
        **kwargs,
    )
    return record


async def _paused_worker(saver, mode):
    calls = []

    @tool
    def probe() -> str:
        """Record a harmless probe execution."""
        calls.append("probe")
        return "Probe result."

    graph = create_agent(_ProbeModel(responses=[]), tools=[probe], state_schema=get_thread_state_schema(mode), checkpointer=saver)
    config = _config(mode)
    await graph.ainvoke({"messages": [HumanMessage(content="hello", id="h1")]}, config)
    manager = RunManager()
    record = await _worker(graph, saver, manager, mode, config, {"messages": [HumanMessage(content="please probe", id="h2")]}, interrupt_before=["tools"])
    assert record.status == RunStatus.success
    graph.interrupt_before_nodes = None

    # Normal Worker finalization makes the paused checkpoint historical.
    head_tuple = await saver.aget_tuple(config)
    assert "runtime_run_duration" in head_tuple.metadata["writes"]
    selected = await graph.aget_state(head_tuple.parent_config)
    head = await graph.aget_state(config)
    assert selected.config["configurable"]["checkpoint_id"] != head.config["configurable"]["checkpoint_id"]
    assert selected.next == head.next == ("tools",)
    assert calls == []
    return graph, manager, calls, selected, head


@pytest.mark.parametrize("head_completed", [False, True])
async def test_historical_delta_resume_rejects_before_mutating_pending_work(checkpointer, head_completed):
    graph, _, calls, selected, head = await _paused_worker(checkpointer, "delta")
    if head_completed:
        await graph.ainvoke(Command(resume="continue"), _config("delta"))
        head = await graph.aget_state(_config("delta"))
        selected = await graph.aget_state(selected.config)
        assert head.next == ()
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])
    before_config = copy.deepcopy(config)
    before_checkpoints = [item.config async for item in checkpointer.alist(_config("delta"))]
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="delta")

    with pytest.raises(RuntimeError, match="pending execution.*latest checkpoint"):
        await _linearize_delta_checkpoint_resume(accessor=accessor, checkpointer=checkpointer, config=config, thread_id=THREAD_ID, run_id="rejected-resume")

    assert config == before_config
    assert await graph.aget_state(_config("delta")) == head
    assert await graph.aget_state(selected.config) == selected
    assert [item.config async for item in checkpointer.alist(_config("delta"))] == before_checkpoints
    if not head_completed:
        result = await graph.ainvoke(Command(resume="continue"), _config("delta"))
        assert result["messages"][-1].content == FINAL_ANSWER
    assert calls == ["probe"]


async def test_unavailable_selected_checkpoint_rejects_without_rewriting(checkpointer, monkeypatch):
    graph, _, calls, selected, head = await _paused_worker(checkpointer, "delta")
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="delta")
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])
    before_config = copy.deepcopy(config)
    before_checkpoints = [item.config async for item in checkpointer.alist(_config("delta"))]
    missing = AsyncMock(return_value=None)
    monkeypatch.setattr(accessor, "aget_tuple", missing)

    with pytest.raises(RuntimeError, match="could not inspect pending execution"):
        await _linearize_delta_checkpoint_resume(accessor=accessor, checkpointer=checkpointer, config=config, thread_id=THREAD_ID, run_id="missing-checkpoint")

    assert missing.await_args.args[0]["configurable"]["checkpoint_id"] == selected.config["configurable"]["checkpoint_id"]
    assert config == before_config
    assert await graph.aget_state(_config("delta")) == head
    assert [item.config async for item in checkpointer.alist(_config("delta"))] == before_checkpoints
    result = await graph.ainvoke(Command(resume="continue"), _config("delta"))
    assert calls == ["probe"]
    assert result["messages"][-1].content == FINAL_ANSWER


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("selector", ["head", "latest-id", "paused-id"])
async def test_worker_does_not_report_success_after_discarding_pending_tools(checkpointer, mode, selector):
    graph, manager, calls, selected, head = await _paused_worker(checkpointer, mode)
    checkpoint_id = None if selector == "head" else (head if selector == "latest-id" else selected).config["configurable"]["checkpoint_id"]
    record = await _worker(graph, checkpointer, manager, mode, _config(mode, checkpoint_id), Command(resume="continue"))

    if mode == "delta" and selector == "paused-id":
        assert record.status == RunStatus.error
        assert "pending execution" in record.error
        assert "latest checkpoint" in record.error
        assert calls == []
        after = await graph.aget_state(_config(mode))
        assert after.values == head.values
        assert after.next == ("tools",)
        # The rejected resume's normal finalization may write duration metadata,
        # but the latest execution position remains usable without the selector.
        record = await _worker(graph, checkpointer, manager, mode, _config(mode), Command(resume="continue"))

    assert record.status == RunStatus.success
    assert calls == ["probe"]
    messages = (await graph.aget_state(_config(mode))).values["messages"]
    assert any(isinstance(message, ToolMessage) and message.tool_call_id == "probe-call" for message in messages)
    assert messages[-1].content == FINAL_ANSWER
