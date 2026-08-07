"""Tests for request-local query-aware memory recall."""

from __future__ import annotations

import asyncio
import threading
from collections import Counter
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.memory.context import aload_memory_context, load_memory_context
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


def _app_config(*, injection: bool = True, session: bool = False, turn: bool = True):
    return SimpleNamespace(
        memory=SimpleNamespace(
            enabled=True,
            injection_enabled=injection,
            session_injection_enabled=session,
            turn_injection_enabled=turn,
            backend_config={},
        )
    )


def _request(messages, *, context: dict):
    runtime = SimpleNamespace(context=context)
    return ModelRequest(
        model=object(),
        messages=list(messages),
        state={"messages": list(messages)},
        runtime=runtime,
    )


class _FakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Runnable:  # type: ignore[override]
        return self


class _RecordModelInput(AgentMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[Any]] = []

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        self.calls.append(list(request.messages))
        return await handler(request)


def test_sync_memory_context_config_resolution_failure_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        "deerflow.config.memory_config.get_memory_config",
        Mock(side_effect=RuntimeError("config unavailable")),
    )

    assert load_memory_context() == ""


@pytest.mark.asyncio
async def test_async_memory_context_config_resolution_failure_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        "deerflow.config.memory_config.get_memory_config",
        Mock(side_effect=RuntimeError("config unavailable")),
    )

    assert await aload_memory_context() == ""


def test_sync_turn_recall_uses_sync_manager_context(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        get_context=Mock(return_value="<memory>\nsync recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(
        agent_name="research",
        app_config=_app_config(),
    )
    user_message = HumanMessage(content="sync question", id="current")
    request = _request(
        [user_message],
        context={"user_id": "alice", "thread_id": "thread-1"},
    )
    observed: list[ModelRequest] = []

    def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request, handler)

    manager.get_context.assert_called_once_with(
        "alice",
        agent_name="research",
        thread_id="thread-1",
        query="sync question",
    )
    assert [message.content for message in observed[0].messages] == [
        "<memory>\nsync recall\n</memory>",
        "sync question",
    ]


@pytest.mark.asyncio
async def test_async_turn_recall_uses_latest_real_user_and_reuses_one_result(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="<memory>\nturn recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(
        agent_name="research",
        app_config=_app_config(),
    )
    old_user = HumanMessage(content="old question", id="old")
    hidden = HumanMessage(
        content="framework context",
        id="hidden",
        additional_kwargs={"hide_from_ui": True},
    )
    current_user = HumanMessage(
        content=[{"type": "text", "text": "sanitized wrapper"}],
        id="current",
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "latest real question"},
    )
    request = _request(
        [old_user, AIMessage(content="answer"), hidden, current_user],
        context={"user_id": "alice", "thread_id": "thread-1"},
    )
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(request, handler)
    await middleware.awrap_model_call(request, handler)

    manager.aget_context.assert_awaited_once_with(
        "alice",
        agent_name="research",
        thread_id="thread-1",
        query="latest real question",
    )
    assert len(observed) == 2
    for model_request in observed:
        recalled_index = next(index for index, message in enumerate(model_request.messages) if message.content == "<memory>\nturn recall\n</memory>")
        assert model_request.messages[recalled_index + 1] is current_user
        assert model_request.messages[recalled_index].additional_kwargs["hide_from_ui"] is True
    assert request.state["messages"] == [old_user, AIMessage(content="answer"), hidden, current_user]
    assert request.messages == [old_user, AIMessage(content="answer"), hidden, current_user]


@pytest.mark.asyncio
async def test_empty_latest_real_user_message_does_not_recall_against_older_turn(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="must not be used"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())
    request = _request(
        [
            HumanMessage(content="older question", id="old"),
            AIMessage(content="answer"),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}], id="current"),
        ],
        context={"user_id": "alice", "thread_id": "thread-1"},
    )
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(request, handler)

    manager.aget_context.assert_not_awaited()
    assert observed[0] is request


@pytest.mark.asyncio
async def test_async_turn_recall_reuses_result_for_rematerialized_message_without_id(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="<memory>\nturn recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())
    context = {"user_id": "alice", "thread_id": "thread-1"}
    requests = [
        _request([HumanMessage(content="same question")], context=context),
        _request([HumanMessage(content="same question")], context=context),
    ]
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    for request in requests:
        await middleware.awrap_model_call(request, handler)

    manager.aget_context.assert_awaited_once()
    assert all(any(message.content == "<memory>\nturn recall\n</memory>" for message in request.messages) for request in observed)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "injection_enabled",
        "session_enabled",
        "turn_enabled",
        "expected_session_calls",
        "expected_turn_calls",
    ),
    [
        pytest.param(False, True, True, 0, 0, id="master-disabled"),
        pytest.param(True, True, False, 1, 0, id="session-only"),
        pytest.param(True, False, True, 0, 1, id="turn-only"),
        pytest.param(True, True, True, 1, 1, id="session-and-turn"),
    ],
)
async def test_session_and_turn_injection_controls(
    monkeypatch,
    injection_enabled: bool,
    session_enabled: bool,
    turn_enabled: bool,
    expected_session_calls: int,
    expected_turn_calls: int,
):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        get_context=Mock(return_value="session recall"),
        aget_context=AsyncMock(return_value="<memory>\nturn recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(
        app_config=_app_config(
            injection=injection_enabled,
            session=session_enabled,
            turn=turn_enabled,
        )
    )
    user_message = HumanMessage(content="question", id="current")
    runtime = SimpleNamespace(context={"user_id": "alice", "thread_id": "thread-1"})

    with patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "2026-08-07, Friday"
        state_update = middleware.before_agent(
            {"messages": [user_message]},
            runtime,
        )

    request = ModelRequest(
        model=object(),
        messages=[user_message],
        state={"messages": [user_message]},
        runtime=runtime,
    )
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(request, handler)

    assert manager.get_context.call_count == expected_session_calls
    assert manager.aget_context.await_count == expected_turn_calls
    if expected_session_calls:
        manager.get_context.assert_called_once_with(
            "alice",
            agent_name=None,
            thread_id="thread-1",
        )
        assert any("session recall" in str(message.content) for message in state_update["messages"])
    else:
        assert all("session recall" not in str(message.content) for message in state_update["messages"])
    if expected_turn_calls:
        assert any("turn recall" in str(message.content) for message in observed[0].messages)
    else:
        assert all("turn recall" not in str(message.content) for message in observed[0].messages)


def test_session_snapshot_does_not_add_thread_scope_to_capability_off_backend(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=False,
        get_context=Mock(return_value="session recall"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(
        app_config=_app_config(session=True, turn=False),
    )
    runtime = SimpleNamespace(context={"user_id": "alice", "thread_id": "thread-1"})

    with patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "2026-08-07, Friday"
        state_update = middleware.before_agent(
            {"messages": [HumanMessage(content="question", id="current")]},
            runtime,
        )

    manager.get_context.assert_called_once_with(
        "alice",
        agent_name=None,
    )
    assert any("session recall" in str(message.content) for message in state_update["messages"])


@pytest.mark.asyncio
async def test_turn_recall_is_absent_from_capture_input(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="<memory>\nprivate recall\n</memory>\n"),
        aadd=AsyncMock(),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_manager",
        lambda: manager,
    )
    app_config = _app_config()
    recall_middleware = DynamicContextMiddleware(
        agent_name="research",
        app_config=app_config,
    )
    capture_middleware = MemoryMiddleware(
        agent_name="research",
        memory_config=app_config.memory,
    )
    user_message = HumanMessage(content="question", id="current")
    request = _request(
        [user_message],
        context={"user_id": "alice", "thread_id": "thread-1"},
    )
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await recall_middleware.awrap_model_call(request, handler)
    await capture_middleware.aafter_agent(request.state, request.runtime)

    assert any(message.content == "<memory>\nprivate recall\n</memory>" for message in observed[0].messages)
    manager.aadd.assert_awaited_once()
    captured_messages = manager.aadd.await_args.args[1]
    assert captured_messages == [user_message]
    assert all("private recall" not in str(message.content) for message in captured_messages)


@pytest.mark.asyncio
async def test_turn_recall_is_absent_from_compiled_graph_state_and_checkpoint(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="<memory>\nprivate recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    recorder = _RecordModelInput()
    agent = create_agent(
        model=_FakeModel(responses=[AIMessage(content="answer")]),
        tools=[],
        middleware=[
            DynamicContextMiddleware(app_config=_app_config(session=False, turn=True)),
            recorder,
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "checkpoint-thread"}}
    context = {"user_id": "alice", "thread_id": "checkpoint-thread"}

    final = await agent.ainvoke(
        {"messages": [HumanMessage(content="question", id="current")]},
        config,
        context=context,
    )
    checkpoint = await agent.aget_state(config)

    assert any(message.content == "<memory>\nprivate recall\n</memory>" for message in recorder.calls[0])
    for messages in (final["messages"], checkpoint.values["messages"]):
        assert all("private recall" not in str(message.content) for message in messages)
        assert all(not message.additional_kwargs.get("dynamic_turn_memory") for message in messages)


@pytest.mark.asyncio
async def test_capability_off_backend_receives_no_query_call(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=False,
        aget_context=AsyncMock(return_value="must not be used"),
    )
    event_loop_thread = threading.current_thread()
    lookup_threads: list[threading.Thread] = []

    def get_manager():
        lookup_threads.append(threading.current_thread())
        return manager

    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", get_manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())
    request = _request(
        [HumanMessage(content="question", id="current")],
        context={"user_id": "alice", "thread_id": "thread-1"},
    )
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(request, handler)

    manager.aget_context.assert_not_awaited()
    assert len(lookup_threads) == 1
    assert lookup_threads[0] is not event_loop_thread
    assert observed[0] is request


@pytest.mark.asyncio
async def test_concurrent_runs_keep_recall_cache_isolated(monkeypatch):
    calls: Counter[str] = Counter()

    async def get_context(user_id, *, agent_name=None, thread_id=None, query=None):
        del agent_name
        calls[query] += 1
        await asyncio.sleep(0)
        return f"<memory>\n{user_id}:{thread_id}:{query}\n</memory>\n"

    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=get_context,
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())

    async def run(user_id: str, thread_id: str, query: str) -> list[str]:
        request = _request(
            [HumanMessage(content=query, id=f"{thread_id}-message")],
            context={"user_id": user_id, "thread_id": thread_id},
        )
        observed: list[str] = []

        async def handler(model_request: ModelRequest) -> ModelResponse:
            observed.extend(str(message.content) for message in model_request.messages)
            return ModelResponse(result=[AIMessage(content="ok")])

        await middleware.awrap_model_call(request, handler)
        await middleware.awrap_model_call(request, handler)
        return observed

    alice_messages, bob_messages = await asyncio.gather(
        run("alice", "thread-a", "question-a"),
        run("bob", "thread-b", "question-b"),
    )

    assert calls == Counter({"question-a": 1, "question-b": 1})
    assert any("alice:thread-a:question-a" in content for content in alice_messages)
    assert all("bob:thread-b" not in content for content in alice_messages)
    assert any("bob:thread-b:question-b" in content for content in bob_messages)
    assert all("alice:thread-a" not in content for content in bob_messages)
