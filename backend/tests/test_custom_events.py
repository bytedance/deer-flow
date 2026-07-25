from __future__ import annotations

import asyncio
import importlib
from enum import Enum
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.config import get_stream_writer
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Interrupt

from deerflow.subagents.config import SubagentConfig
from deerflow.utils import custom_events as custom_events_module
from deerflow.utils.custom_events import aemit_custom_event, emit_custom_event

task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


class _State(TypedDict):
    value: int


def _compile_graph(node):
    builder = StateGraph(_State)
    builder.add_node("emit", node)
    builder.add_edge(START, "emit")
    builder.add_edge("emit", END)
    return builder.compile()


def _sync_node(state: _State) -> _State:
    payload = {"type": "sync_probe", "value": state["value"]}
    emit_custom_event(payload, writer=get_stream_writer())
    return state


async def _async_node(state: _State) -> _State:
    payload = {"type": "async_probe", "value": state["value"]}
    await aemit_custom_event(payload, writer=get_stream_writer())
    return state


async def _custom_events(graph) -> list[dict]:
    return [chunk async for chunk in graph.astream({"value": 7}, stream_mode="custom")]


async def _astream_events(graph) -> list[dict]:
    return [event async for event in graph.astream_events({"value": 7}, version="v2") if event["event"] == "on_custom_event"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("node", "event_name"),
    [
        (_sync_node, "sync_probe"),
        (_async_node, "async_probe"),
    ],
)
async def test_custom_event_is_emitted_once_to_each_streaming_api(node, event_name):
    graph = _compile_graph(node)

    custom_chunks = await _custom_events(graph)
    callback_events = await _astream_events(graph)

    expected = {"type": event_name, "value": 7}
    assert custom_chunks == [expected]
    assert len(callback_events) == 1
    assert callback_events[0]["name"] == event_name
    assert callback_events[0]["data"] == expected


class _TaskCallingModel(BaseChatModel):
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-task-caller"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "task-call-1",
                        "name": "task",
                        "args": {
                            "description": "validate streaming",
                            "prompt": "run the delegated task",
                            "subagent_type": "general-purpose",
                        },
                    }
                ],
                response_metadata={"finish_reason": "tool_calls"},
            )
        else:
            message = AIMessage(content="done", response_metadata={"finish_reason": "stop"})
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.anyio
async def test_real_task_tool_events_reach_astream_events(monkeypatch):
    """Exercise the real ToolNode/runtime callback context used by task_tool."""

    class _SubagentStatus(Enum):
        COMPLETED = "completed"

    config = SubagentConfig(
        name="general-purpose",
        description="General helper",
        system_prompt="Test prompt",
        model="test-model",
        timeout_seconds=10,
    )
    completed = SimpleNamespace(
        status=_SubagentStatus.COMPLETED,
        ai_messages=[],
        result="delegated result",
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
    )

    class _Executor:
        def __init__(self, **_kwargs):
            pass

        def execute_async(self, _prompt, task_id=None):
            return task_id

    monkeypatch.setattr(task_tool_module, "SubagentStatus", _SubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", _Executor)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: completed)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _task_id: None)
    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    agent = create_agent(
        model=_TaskCallingModel(),
        tools=[task_tool_module.task_tool],
        context_schema=dict,
    )
    events = [
        event
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content="delegate this")]},
            version="v2",
            context={"thread_id": "task-stream-thread"},
        )
        if event["event"] == "on_custom_event"
    ]

    assert [event["name"] for event in events] == ["task_started", "task_completed"]
    assert [event["data"]["type"] for event in events] == ["task_started", "task_completed"]
    assert all(event["data"]["task_id"] == "task-call-1" for event in events)
    assert events[0]["data"]["description"] == "validate streaming"
    assert events[1]["data"]["result"] == "delegated result"


def test_sync_dispatch_failure_does_not_break_writer(monkeypatch):
    payload = {"type": "sync_probe", "value": 1}
    written: list[dict] = []

    def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("callback failed")

    monkeypatch.setattr(custom_events_module, "dispatch_custom_event", fail_dispatch)

    emit_custom_event(payload, writer=written.append)

    assert written == [payload]


def test_sync_dispatch_without_parent_run_does_not_break_writer():
    payload = {"type": "sync_probe", "value": 1}
    written: list[dict] = []

    emit_custom_event(payload, writer=written.append)

    assert written == [payload]


@pytest.mark.anyio
async def test_async_dispatch_failure_does_not_break_writer(monkeypatch):
    payload = {"type": "async_probe", "value": 1}
    written: list[dict] = []

    async def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("callback failed")

    monkeypatch.setattr(custom_events_module, "adispatch_custom_event", fail_dispatch)

    await aemit_custom_event(payload, writer=written.append)

    assert written == [payload]


@pytest.mark.anyio
async def test_async_dispatch_without_parent_run_does_not_break_writer():
    payload = {"type": "async_probe", "value": 1}
    written: list[dict] = []

    await aemit_custom_event(payload, writer=written.append)

    assert written == [payload]


def test_missing_event_type_preserves_writer_and_skips_dispatch(monkeypatch):
    payload = {"value": 1}
    written: list[dict] = []
    dispatched: list[tuple] = []

    monkeypatch.setattr(custom_events_module, "dispatch_custom_event", lambda *args, **kwargs: dispatched.append((args, kwargs)))

    emit_custom_event(payload, writer=written.append)

    assert written == [payload]
    assert dispatched == []


def test_writer_failure_propagates_before_dispatch(monkeypatch):
    dispatched: list[tuple] = []

    def fail_writer(_payload):
        raise RuntimeError("writer failed")

    monkeypatch.setattr(custom_events_module, "dispatch_custom_event", lambda *args, **kwargs: dispatched.append((args, kwargs)))

    with pytest.raises(RuntimeError, match="writer failed"):
        emit_custom_event({"type": "sync_probe"}, writer=fail_writer)

    assert dispatched == []


@pytest.mark.anyio
async def test_async_writer_failure_propagates_before_dispatch(monkeypatch):
    dispatched: list[tuple] = []

    def fail_writer(_payload):
        raise RuntimeError("writer failed")

    async def record_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(custom_events_module, "adispatch_custom_event", record_dispatch)

    with pytest.raises(RuntimeError, match="writer failed"):
        await aemit_custom_event({"type": "async_probe"}, writer=fail_writer)

    assert dispatched == []


@pytest.mark.anyio
async def test_async_cancellation_is_not_swallowed(monkeypatch):
    async def cancel_dispatch(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(custom_events_module, "adispatch_custom_event", cancel_dispatch)

    with pytest.raises(asyncio.CancelledError):
        await aemit_custom_event({"type": "async_probe"}, writer=lambda _payload: None)


@pytest.mark.parametrize("async_dispatch", [False, True])
def test_langgraph_control_flow_is_not_swallowed(monkeypatch, async_dispatch):
    control_flow = GraphInterrupt((Interrupt(value="pause"),))

    if async_dispatch:

        async def interrupt_dispatch(*_args, **_kwargs):
            raise control_flow

        monkeypatch.setattr(custom_events_module, "adispatch_custom_event", interrupt_dispatch)

        with pytest.raises(GraphInterrupt) as raised:
            asyncio.run(aemit_custom_event({"type": "async_probe"}, writer=lambda _payload: None))
    else:

        def interrupt_dispatch(*_args, **_kwargs):
            raise control_flow

        monkeypatch.setattr(custom_events_module, "dispatch_custom_event", interrupt_dispatch)

        with pytest.raises(GraphInterrupt) as raised:
            emit_custom_event({"type": "sync_probe"}, writer=lambda _payload: None)

    assert raised.value is control_flow
