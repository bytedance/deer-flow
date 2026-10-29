"""Manual compaction must refuse a thread paused at a static breakpoint.

A thread interrupted via ``interrupt_before=["tools"]`` still owns a pending
tool task: the Send for the tools node sits in the checkpoint's
``__pregel_tasks`` channel. Manual compaction writes the new checkpoint head
through the state-mutation graph, which schedules no tasks and does not carry
that pending Send across — a resumed run then finishes ``success`` without
ever executing the tool or producing an answer. Until compaction can preserve
the pending position, ``POST /api/threads/{id}/compact`` must fail closed
with 409 instead of silently dropping the pending execution.

The graph, checkpointer, static-interrupt mechanism, compaction route and
state accessor are all real; only the external model service is faked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from app.gateway.auth.models import User
from app.gateway.routers import threads
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.runtime import RunManager, context_compaction
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

THREAD_ID = "thread-compact-interrupted"
TOOL_CALL_ID = "call_probe_1"
FINAL_ANSWER = "probe observed"


class _ScriptedToolModel(FakeMessagesListChatModel):
    """State-aware fake lead model: plain answer on turn 1, one tool call on
    turn 2, final answer once a ToolMessage exists."""

    invocations: int = 0

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Runnable:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.invocations += 1
        if any(isinstance(m, ToolMessage) for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=FINAL_ANSWER, id="a-final"))])
        if sum(1 for m in messages if isinstance(m, HumanMessage)) >= 2:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            id="a-call",
                            tool_calls=[{"name": "probe_tool", "args": {"query": "probe-v1"}, "id": TOOL_CALL_ID, "type": "tool_call"}],
                        )
                    )
                ]
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="turn one answer", id="a1"))])


def _build_agent_graph(mode: str, checkpointer: Any, tool_calls: list[str]):
    @tool
    def probe_tool(query: str) -> str:
        """Record the invocation and return a fixed result."""
        tool_calls.append(query)
        return f"probe result: {query}"

    return create_agent(
        model=_ScriptedToolModel(responses=[]),
        tools=[probe_tool],
        state_schema=get_thread_state_schema(mode),
        checkpointer=checkpointer,
    )


@pytest.fixture
def _summarization_app_config():
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "summarization": {"enabled": True},
            }
        )
    )
    yield
    reset_app_config()


@pytest.fixture
def _fake_summary_model(monkeypatch: pytest.MonkeyPatch):
    def fake_create_chat_model(*args: Any, **kwargs: Any) -> FakeMessagesListChatModel:
        return FakeMessagesListChatModel(responses=[AIMessage(content="Summary of prior turns.")])

    monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.create_chat_model", fake_create_chat_model)


def _make_compact_app(mode: str, checkpointer: Any) -> Any:
    user = User(email="compact-guard@example.com", password_hash="x", system_role="user", id="3f1c2a10-7b8e-4d2a-9c1f-5e6a7b8c9d0e")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.store = InMemoryStore()
    app.state.checkpointer = checkpointer
    app.state.checkpoint_channel_mode = mode
    app.state.run_manager = RunManager()
    app.include_router(threads.router)
    return app


def _config(mode: str) -> dict[str, Any]:
    config: dict[str, Any] = {"configurable": {"thread_id": THREAD_ID}}
    inject_checkpoint_mode(config, mode)
    return config


def _run_two_turns_to_static_pause(graph: Any, config: dict[str, Any]) -> None:
    """Turn 1 completes; turn 2 pauses statically before the tools node."""
    graph.invoke({"messages": [HumanMessage(content="hello", id="h1")]}, config)
    graph.interrupt_before_nodes = ["tools"]
    try:
        graph.invoke({"messages": [HumanMessage(content="please probe", id="h2")]}, config)
    finally:
        graph.interrupt_before_nodes = None


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_compact_rejects_thread_paused_before_tools(mode: str, _summarization_app_config, _fake_summary_model):
    """A statically interrupted thread owns a pending tool task; compaction must
    fail closed (409) and leave the pending execution intact."""
    checkpointer = InMemorySaver()
    tool_calls: list[str] = []
    graph = _build_agent_graph(mode, checkpointer, tool_calls)
    config = _config(mode)
    _run_two_turns_to_static_pause(graph, config)

    paused = graph.get_state(config)
    assert list(paused.next) == ["tools"], f"expected pending tools task, got {paused.next!r}"
    assert tool_calls == []
    paused_checkpoint_id = paused.config["configurable"]["checkpoint_id"]
    paused_task_ids = [task.id for task in paused.tasks]
    assert paused_task_ids, "expected the paused tools task in the snapshot"

    app = _make_compact_app(mode, checkpointer)
    with TestClient(app) as client:
        response = client.post(f"/api/threads/{THREAD_ID}/compact", json={"force": True, "keep": {"type": "messages", "value": 1}})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Thread has pending execution. Resume the interrupted run before compacting."

    # The rejected compaction wrote nothing: head checkpoint, pending position
    # and pending task identity are exactly as before the attempt.
    after_reject = graph.get_state(config)
    assert after_reject.config["configurable"]["checkpoint_id"] == paused_checkpoint_id
    assert list(after_reject.next) == ["tools"]
    assert [task.id for task in after_reject.tasks] == paused_task_ids

    # The thread is still resumable: the pending tool executes exactly once and
    # the model then produces the final answer.
    graph.invoke(Command(resume="go"), config)
    assert tool_calls == ["probe-v1"]
    final_messages = graph.get_state(config).values["messages"]
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == TOOL_CALL_ID for m in final_messages)
    assert any(isinstance(m, AIMessage) and m.content == FINAL_ANSWER for m in final_messages)


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_compact_rejects_unavailable_checkpoint(mode: str, monkeypatch, _summarization_app_config, _fake_summary_model):
    """A valid snapshot alone cannot prove the raw checkpoint has no pending work."""
    checkpointer = InMemorySaver()
    graph = _build_agent_graph(mode, checkpointer, [])
    config = _config(mode)
    graph.invoke({"messages": [HumanMessage(content="hello", id="h1")]}, config)
    graph.invoke({"messages": [HumanMessage(content="again", id="h2")]}, config)
    before = graph.get_state(config)
    checkpoint_ids = [item.config["configurable"]["checkpoint_id"] for item in checkpointer.list(config)]

    missing_tuple = AsyncMock(return_value=None)
    monkeypatch.setattr(CheckpointStateAccessor, "aget_tuple", missing_tuple)
    create_middleware = MagicMock(wraps=context_compaction._create_compaction_middleware)
    monkeypatch.setattr(context_compaction, "_create_compaction_middleware", create_middleware)
    write_checkpoint = AsyncMock(wraps=checkpointer.aput)
    monkeypatch.setattr(checkpointer, "aput", write_checkpoint)

    app = _make_compact_app(mode, checkpointer)
    with TestClient(app) as client:
        response = client.post(f"/api/threads/{THREAD_ID}/compact", json={"force": True, "keep": {"type": "messages", "value": 1}})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Thread checkpoint is unavailable. Cannot verify pending execution before compacting."
    missing_tuple.assert_awaited_once()
    create_middleware.assert_not_called()
    write_checkpoint.assert_not_awaited()
    assert graph.get_state(config) == before
    assert [item.config["configurable"]["checkpoint_id"] for item in checkpointer.list(config)] == checkpoint_ids


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_compact_still_accepts_idle_completed_thread(mode: str, _summarization_app_config, _fake_summary_model):
    """The guard must not overreach: a thread with no pending tasks compacts."""
    checkpointer = InMemorySaver()
    tool_calls: list[str] = []
    graph = _build_agent_graph(mode, checkpointer, tool_calls)
    config = _config(mode)
    graph.invoke({"messages": [HumanMessage(content="hello", id="h1")]}, config)
    graph.invoke({"messages": [HumanMessage(content="again", id="h2")]}, config)

    idle = graph.get_state(config)
    assert list(idle.next) == []

    app = _make_compact_app(mode, checkpointer)
    with TestClient(app) as client:
        response = client.post(f"/api/threads/{THREAD_ID}/compact", json={"force": True, "keep": {"type": "messages", "value": 1}})
    assert response.status_code == 200, response.text
    assert response.json()["compacted"] is True
