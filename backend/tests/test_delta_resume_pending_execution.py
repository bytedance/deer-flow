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
from langgraph.graph import END, StateGraph
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


async def _worker(graph, saver, manager, mode, config, graph_input, *, metadata=None, **kwargs):
    record = await manager.create(THREAD_ID, metadata=metadata)
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


async def _paused_worker(saver, mode, *, branch_tasks=False):
    calls = []

    @tool
    def probe() -> str:
        """Record a harmless probe execution."""
        calls.append("probe")
        return "Probe result."

    model = _ProbeModel(responses=[])
    if branch_tasks:

        async def model_node(state):
            message = await model.ainvoke(state["messages"])
            if message.tool_calls:
                human = next(message for message in reversed(state["messages"]) if isinstance(message, HumanMessage))
                message = message.model_copy(update={"id": f"call-{human.id}"})
            return {"messages": [message]}

        async def tools_node(state):
            calls.append("probe")
            return {"messages": [ToolMessage(content="Probe result.", tool_call_id="probe-call", id="probe-result")]}

        builder = StateGraph(get_thread_state_schema(mode))
        builder.add_node("model", model_node)
        builder.add_node("tools", tools_node)
        builder.set_entry_point("model")
        builder.add_conditional_edges("model", lambda state: "tools" if state["messages"][-1].tool_calls else END)
        builder.add_edge("tools", "model")
        graph = builder.compile(checkpointer=saver)
    else:
        graph = create_agent(model, tools=[probe], state_schema=get_thread_state_schema(mode), checkpointer=saver)
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


async def _earlier_checkpoint_without_sends(graph, saver, selector):
    history = [snapshot async for snapshot in graph.aget_state_history(_config("delta"))]
    selected = next(
        snapshot
        for snapshot in history
        if any(message.id == "first-answer" for message in snapshot.values.get("messages", []))
        and not any(message.id == "h2" for message in snapshot.values.get("messages", []))
        and (snapshot.metadata.get("source") == "input" if selector == "input" else snapshot.next == ())
    )
    selected_tuple = await saver.aget_tuple(selected.config)
    assert not (selected_tuple.checkpoint.get("channel_values") or {}).get("__pregel_tasks")
    return await graph.aget_state(selected.config)


@pytest.mark.parametrize("selector", ["input", "completed"])
async def test_pending_head_rejects_earlier_selector_without_rewriting(checkpointer, selector):
    graph, _, calls, _, head = await _paused_worker(checkpointer, "delta")
    selected = await _earlier_checkpoint_without_sends(graph, checkpointer, selector)
    head_tuple = await checkpointer.aget_tuple(head.config)
    assert head_tuple.checkpoint["channel_values"]["__pregel_tasks"]
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])
    before_config = copy.deepcopy(config)
    before_checkpoints = [item.config async for item in checkpointer.alist(_config("delta"))]
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="delta")

    with pytest.raises(RuntimeError, match="pending execution.*latest checkpoint"):
        await _linearize_delta_checkpoint_resume(accessor=accessor, checkpointer=checkpointer, config=config, thread_id=THREAD_ID, run_id="pending-head")

    assert config == before_config
    assert await graph.aget_state(_config("delta")) == head
    assert await graph.aget_state(selected.config) == selected
    assert [item.config async for item in checkpointer.alist(_config("delta"))] == before_checkpoints
    result = await graph.ainvoke(Command(resume="continue"), _config("delta"))
    assert calls == ["probe"]
    assert result["messages"][-1].content == FINAL_ANSWER


@pytest.mark.parametrize("selector", ["input", "completed"])
@pytest.mark.parametrize("input_kind", ["resume", "fresh"])
@pytest.mark.parametrize("edit_replay", [False, True])
async def test_worker_preserves_pending_head_with_earlier_selector(checkpointer, selector, input_kind, edit_replay):
    graph, manager, calls, _, head = await _paused_worker(checkpointer, "delta")
    selected = await _earlier_checkpoint_without_sends(graph, checkpointer, selector)
    checkpoint_id = selected.config["configurable"]["checkpoint_id"]
    graph_input = Command(resume="continue") if input_kind == "resume" else {"messages": [HumanMessage(content="new request", id="h3")]}

    record = await _worker(graph, checkpointer, manager, "delta", _config("delta", checkpoint_id), graph_input, metadata={"replay_kind": "edit"} if edit_replay else None)

    assert record.status == RunStatus.error
    assert "pending execution" in record.error
    assert record.run_id in record.error
    assert checkpoint_id in record.error
    assert head.config["configurable"]["checkpoint_id"] in record.error
    assert calls == []
    after = await graph.aget_state(_config("delta"))
    assert after.values == head.values
    assert after.next == head.next == ("tools",)
    record = await _worker(graph, checkpointer, manager, "delta", _config("delta"), Command(resume="continue"))
    assert record.status == RunStatus.success
    assert calls == ["probe"]
    messages = (await graph.aget_state(_config("delta"))).values["messages"]
    assert any(isinstance(message, ToolMessage) and message.tool_call_id == "probe-call" for message in messages)
    assert messages[-1].content == FINAL_ANSWER


@pytest.mark.parametrize("edit_replay", [False, True])
async def test_rejected_resume_skips_rollback_when_cancellation_wins(checkpointer, monkeypatch, edit_replay):
    graph, manager, calls, _, head = await _paused_worker(checkpointer, "delta")
    selected = await _earlier_checkpoint_without_sends(graph, checkpointer, "completed")
    original_set_status = manager.set_status_if_not_cancelled

    async def cancellation_wins(run_id, status, **kwargs):
        # Model the terminal manager decision after a durable rollback request
        # wins admission; retain the real Worker, graph and checkpoint writes.
        if status == RunStatus.error and "pending execution" in (kwargs.get("error") or ""):
            return "rollback"
        return await original_set_status(run_id, status, **kwargs)

    monkeypatch.setattr(manager, "set_status_if_not_cancelled", cancellation_wins)
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])
    record = await _worker(graph, checkpointer, manager, "delta", config, Command(resume="continue"), metadata={"replay_kind": "edit"} if edit_replay else None)

    assert record.status == RunStatus.error
    assert record.error == "Rolled back by user"
    assert calls == []
    after = await graph.aget_state(_config("delta"))
    assert after.values == head.values
    assert after.next == ("tools",)
    record = await _worker(graph, checkpointer, manager, "delta", _config("delta"), Command(resume="continue"))
    assert record.status == RunStatus.success
    assert calls == ["probe"]
    assert (await graph.aget_state(_config("delta"))).values["messages"][-1].content == FINAL_ANSWER


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

    with pytest.raises(RuntimeError, match="pending execution.*latest checkpoint") as error:
        await _linearize_delta_checkpoint_resume(accessor=accessor, checkpointer=checkpointer, config=config, thread_id=THREAD_ID, run_id="rejected-resume")

    assert "rejected-resume" in str(error.value)
    assert selected.config["configurable"]["checkpoint_id"] in str(error.value)
    assert "new input from the latest checkpoint" in str(error.value)
    assert config == before_config
    assert await graph.aget_state(_config("delta")) == head
    assert await graph.aget_state(selected.config) == selected
    assert [item.config async for item in checkpointer.alist(_config("delta"))] == before_checkpoints
    if not head_completed:
        result = await graph.ainvoke(Command(resume="continue"), _config("delta"))
        assert result["messages"][-1].content == FINAL_ANSWER
    assert calls == ["probe"]


@pytest.mark.parametrize("missing_checkpoint", ["selected", "head"])
async def test_unavailable_checkpoint_rejects_without_rewriting(checkpointer, monkeypatch, missing_checkpoint):
    graph, _, calls, _, head = await _paused_worker(checkpointer, "delta")
    selected = await _earlier_checkpoint_without_sends(graph, checkpointer, "completed")
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="delta")
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])
    before_config = copy.deepcopy(config)
    before_checkpoints = [item.config async for item in checkpointer.alist(_config("delta"))]
    missing_id = (selected if missing_checkpoint == "selected" else head).config["configurable"]["checkpoint_id"]
    original_get_tuple = accessor.aget_tuple

    async def get_tuple(config):
        if config["configurable"].get("checkpoint_id") == missing_id:
            return None
        return await original_get_tuple(config)

    missing = AsyncMock(side_effect=get_tuple)
    monkeypatch.setattr(accessor, "aget_tuple", missing)

    with pytest.raises(RuntimeError, match="could not inspect pending execution"):
        await _linearize_delta_checkpoint_resume(accessor=accessor, checkpointer=checkpointer, config=config, thread_id=THREAD_ID, run_id="missing-checkpoint")

    assert missing.await_args.args[0]["configurable"]["checkpoint_id"] == missing_id
    assert config == before_config
    assert await graph.aget_state(_config("delta")) == head
    assert [item.config async for item in checkpointer.alist(_config("delta"))] == before_checkpoints
    result = await graph.ainvoke(Command(resume="continue"), _config("delta"))
    assert calls == ["probe"]
    assert result["messages"][-1].content == FINAL_ANSWER


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("selector", ["head", "latest-id", "paused-id"])
@pytest.mark.parametrize("edit_replay", [False, True])
async def test_worker_does_not_report_success_after_discarding_pending_tools(checkpointer, mode, selector, edit_replay):
    graph, manager, calls, selected, head = await _paused_worker(checkpointer, mode)
    checkpoint_id = None if selector == "head" else (head if selector == "latest-id" else selected).config["configurable"]["checkpoint_id"]
    record = await _worker(graph, checkpointer, manager, mode, _config(mode, checkpoint_id), Command(resume="continue"), metadata={"replay_kind": "edit"} if edit_replay else None)

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


@pytest.mark.parametrize("selector", ["paused", "input", "completed"])
@pytest.mark.parametrize("cleanup", ["ordinary", "edit", "rollback", "edit-rollback"])
async def test_worker_preserves_non_send_pending_nodes(checkpointer, monkeypatch, selector, cleanup):
    graph, manager, calls, paused, head = await _paused_worker(checkpointer, "delta", branch_tasks=True)
    selected = paused if selector == "paused" else await _earlier_checkpoint_without_sends(graph, checkpointer, selector)
    for snapshot in (selected, head):
        checkpoint_tuple = await checkpointer.aget_tuple(snapshot.config)
        assert not (checkpoint_tuple.checkpoint.get("channel_values") or {}).get("__pregel_tasks")
    assert selected.next == (("tools",) if selector == "paused" else ("__start__",) if selector == "input" else ())
    checkpoint_id = selected.config["configurable"]["checkpoint_id"]
    config = _config("delta", checkpoint_id)
    original_set_status = manager.set_status_if_not_cancelled
    if "rollback" in cleanup:

        async def cancellation_wins(run_id, status, **kwargs):
            # Inject the terminal decision, preserving the actual Worker cleanup.
            if status == RunStatus.error and "pending execution" in (kwargs.get("error") or ""):
                return "rollback"
            return await original_set_status(run_id, status, **kwargs)

        monkeypatch.setattr(manager, "set_status_if_not_cancelled", cancellation_wins)

    record = await _worker(graph, checkpointer, manager, "delta", config, Command(resume="continue"), metadata={"replay_kind": "edit"} if "edit" in cleanup else None)

    assert record.status == RunStatus.error
    if "rollback" in cleanup:
        assert record.error == "Rolled back by user"
    else:
        location = "selected" if selector == "paused" else "head"
        assert f"the {location} checkpoint" in record.error
        assert "pending execution" in record.error
        assert record.run_id in record.error
        assert checkpoint_id in record.error
        assert (selected if location == "selected" else head).config["configurable"]["checkpoint_id"] in record.error
    assert config["configurable"]["checkpoint_id"] == checkpoint_id
    assert calls == []
    after = await graph.aget_state(_config("delta"))
    assert after.values == head.values
    assert after.next == ("tools",)

    monkeypatch.setattr(manager, "set_status_if_not_cancelled", original_set_status)
    recovered = await _worker(graph, checkpointer, manager, "delta", _config("delta"), Command(resume="continue"))
    assert recovered.status == RunStatus.success
    assert calls == ["probe"]
    messages = (await graph.aget_state(_config("delta"))).values["messages"]
    assert any(isinstance(message, ToolMessage) and message.tool_call_id == "probe-call" for message in messages)
    assert messages[-1].content == FINAL_ANSWER


@pytest.mark.parametrize("selector", ["paused", "input", "completed"])
async def test_non_send_fresh_input_replay_still_regenerates(checkpointer, selector):
    graph, manager, calls, paused, head = await _paused_worker(checkpointer, "delta", branch_tasks=True)
    selected = paused if selector == "paused" else await _earlier_checkpoint_without_sends(graph, checkpointer, selector)
    for snapshot in (selected, head):
        checkpoint_tuple = await checkpointer.aget_tuple(snapshot.config)
        assert not (checkpoint_tuple.checkpoint.get("channel_values") or {}).get("__pregel_tasks")
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])

    record = await _worker(graph, checkpointer, manager, "delta", config, {"messages": [HumanMessage(content="new request", id="h3")]})

    assert record.status == RunStatus.success
    assert "checkpoint_id" not in config["configurable"]
    assert calls == ["probe"]
    messages = (await graph.aget_state(_config("delta"))).values["messages"]
    assert any(message.id == "h3" for message in messages)
    assert messages[-1].content == FINAL_ANSWER


@pytest.mark.parametrize("selector", ["input", "completed"])
async def test_non_send_resume_without_pending_nodes_still_linearizes(checkpointer, selector):
    graph, manager, calls, _, _ = await _paused_worker(checkpointer, "delta", branch_tasks=True)
    await graph.ainvoke(Command(resume="continue"), _config("delta"))
    head = await graph.aget_state(_config("delta"))
    assert head.next == ()
    selected = await _earlier_checkpoint_without_sends(graph, checkpointer, selector)
    assert selected.next == (("__start__",) if selector == "input" else ())
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])

    record = await _worker(graph, checkpointer, manager, "delta", config, Command(resume="continue"))

    assert record.status == RunStatus.success
    assert "checkpoint_id" not in config["configurable"]
    assert calls == ["probe"]
    after = await graph.aget_state(_config("delta"))
    assert [message.id for message in after.values["messages"]] == [message.id for message in selected.values["messages"]]


@pytest.mark.parametrize("edit_replay", [False, True])
async def test_non_send_selected_nodes_reject_after_head_completed(checkpointer, edit_replay):
    graph, manager, calls, selected, _ = await _paused_worker(checkpointer, "delta", branch_tasks=True)
    await graph.ainvoke(Command(resume="continue"), _config("delta"))
    head = await graph.aget_state(_config("delta"))
    assert head.next == ()
    selected = await graph.aget_state(selected.config)
    assert selected.next == ("tools",)
    selected_tuple = await checkpointer.aget_tuple(selected.config)
    assert not (selected_tuple.checkpoint.get("channel_values") or {}).get("__pregel_tasks")
    config = _config("delta", selected.config["configurable"]["checkpoint_id"])

    record = await _worker(graph, checkpointer, manager, "delta", config, Command(resume="continue"), metadata={"replay_kind": "edit"} if edit_replay else None)

    assert record.status == RunStatus.error
    assert "the selected checkpoint" in record.error
    assert "pending execution" in record.error
    assert config["configurable"]["checkpoint_id"] == selected.config["configurable"]["checkpoint_id"]
    assert calls == ["probe"]
    after = await graph.aget_state(_config("delta"))
    assert after.values == head.values
    assert after.next == ()
