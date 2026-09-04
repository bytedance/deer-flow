"""Tests for request-local query-aware memory recall."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages

from deerflow.agents.memory.context import aload_memory_context, load_memory_context
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.secret_context import DYNAMIC_MEMORY_CONTEXT_KEY
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


async def _model_call(middleware, request, *, use_async):
    observed = []

    def handler(prepared):
        observed.append(prepared)
        return ModelResponse(result=[AIMessage(content="ok")])

    async def ahandler(prepared):
        return handler(prepared)

    if use_async:
        await middleware.awrap_model_call(request, ahandler)
    else:
        middleware.wrap_model_call(request, handler)
    return observed[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("case", ["ordinary", "card", "first-turn-swap", "regenerate", "edit", "continuation", "swapped-continuation", "hidden-context", "summary"])
async def test_turn_recall_targets_only_current_genuine_input(monkeypatch, use_async, case):
    manager = SimpleNamespace(supports_query_aware_context=True, get_context=Mock(return_value="recalled"), aget_context=AsyncMock(return_value="recalled"))
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())
    old = HumanMessage(content="old question", id="old")
    current = HumanMessage(content="current answer", id="current")
    pre_existing = {"old", "answer"}
    messages = [old, AIMessage(content="old answer", id="answer")]
    if case == "card":
        current = current.model_copy(
            update={
                "additional_kwargs": {
                    "hide_from_ui": True,
                    "human_input_response": {"version": 1, "kind": "human_input_response", "source": "ask_clarification", "request_id": "clarification:call-abc", "response_kind": "text", "value": "current answer"},
                }
            }
        )
    elif case == "first-turn-swap":
        messages = DynamicContextMiddleware._make_reminder_and_user_messages(current, "date", reminder_date="2026-09-04")
        current = messages.pop()
        pre_existing = set()
    elif case in {"regenerate", "edit"}:
        # Replay starts from the selected pre-user checkpoint, not the abandoned head.
        current = current.model_copy(update={"id": "replayed-user", "content": "regenerated question" if case == "regenerate" else "edited question"})
    elif case == "swapped-continuation":
        messages = [old.model_copy(update={"id": "old__user"})]
    elif case in {"hidden-context", "summary"}:
        current = current.model_copy(update={"name": "summary"} if case == "summary" else {"additional_kwargs": {"hide_from_ui": True}})
    if case not in {"continuation", "swapped-continuation"}:
        messages.append(current)
    context = {"user_id": "alice", "thread_id": "thread-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset(pre_existing)}
    request = _request(messages, context=context)
    prepared = await _model_call(middleware, request, use_async=use_async)
    recalled = [message for message in prepared.messages if message.additional_kwargs.get("dynamic_turn_memory")]
    expected = case not in {"continuation", "swapped-continuation", "hidden-context", "summary"}
    assert len(recalled) == int(expected)
    if expected:
        lookup = manager.aget_context if use_async else manager.get_context
        assert lookup.call_args.kwargs["query"] == current.content
        assert prepared.messages[prepared.messages.index(recalled[0]) + 1] is current
        # Tool-loop calls see a rematerialized history but reuse this run's recall.
        await _model_call(middleware, _request(messages + [AIMessage(content="working")], context=context), use_async=use_async)
        assert lookup.call_count == 1
    else:
        manager.get_context.assert_not_called()
        manager.aget_context.assert_not_called()
    assert request.messages == messages
    assert request.state["messages"] == messages


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("session,turn", [(True, False), (False, True), (True, True)])
async def test_memory_audit_hashes_effective_request_blocks(monkeypatch, use_async, session, turn):
    middleware = DynamicContextMiddleware(app_config=_app_config(session=session, turn=turn))
    baseline = "<memory>baseline</memory>"
    recalled = "<memory>turn</memory>"
    monkeypatch.setattr(middleware, "_build_full_reminder", lambda runtime: ("date", baseline if session else None))
    monkeypatch.setattr(middleware, "_load_turn_memory", Mock(return_value=recalled))
    monkeypatch.setattr(middleware, "_aload_turn_memory", AsyncMock(return_value=recalled))
    store = MemoryRunEventStore()
    journal = RunJournal("audit-run", "audit-thread", store)
    context = {"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()}
    state = {"messages": [HumanMessage(content="question", id="m1")]}
    runtime = SimpleNamespace(context=context)
    update = await middleware.abefore_agent(state, runtime) if use_async else middleware.before_agent(state, runtime)
    await journal.flush()
    events_before_model = await store.list_events("audit-thread", "audit-run", event_types=["context:memory"])
    assert len(events_before_model) == (0 if turn else 1)
    # Use LangGraph's actual reducer, including the first-turn __user replacement.
    request = _request(add_messages(state["messages"], update["messages"]), context=context)
    prepared = await _model_call(middleware, request, use_async=use_async)
    expected_blocks = ([baseline] if session else []) + ([recalled] if turn else [])
    actual_blocks = [m.content for m in prepared.messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("dynamic_context_reminder")]
    assert actual_blocks == expected_blocks
    content = expected_blocks[0] if len(expected_blocks) == 1 else json.dumps(expected_blocks, ensure_ascii=False, separators=(",", ":"))
    # The cache-hit path must neither lose nor overwrite the first request's audit.
    await _model_call(middleware, request, use_async=use_async)
    await journal.flush()
    events = await store.list_events("audit-thread", "audit-run", event_types=["context:memory"])
    assert len(events) == 1
    assert events[0]["content"] == {"content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
    await journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("path", ["cache-hit", "empty-recall", "no-new-input", "no-memory", "unmarked-memory", "reversed-blocks"])
async def test_turn_memory_audit_covers_early_returns(monkeypatch, use_async, path):
    middleware = DynamicContextMiddleware(app_config=_app_config(session=True))
    baseline = HumanMessage(content="<memory>baseline</memory>", id="old__memory", additional_kwargs={"dynamic_context_reminder": True, "hide_from_ui": True})
    current = HumanMessage(content="question", id="current")
    context = {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"old__memory", "current"} if path == "no-new-input" else {"old__memory"})}
    messages = [SystemMessage(content="date", additional_kwargs={"dynamic_context_reminder": True}), baseline, current]
    if path == "no-memory":
        messages.remove(baseline)
    elif path == "unmarked-memory":
        # A caller-controlled ID/content alone cannot establish memory provenance.
        messages[1] = baseline.model_copy(update={"additional_kwargs": {}})
    recall = "<memory>turn</memory>" if path in {"cache-hit", "reversed-blocks"} else ""
    if path == "reversed-blocks":
        messages = [current, baseline]
    sync_lookup, async_lookup = Mock(return_value=recall), AsyncMock(return_value=recall)
    monkeypatch.setattr(middleware, "_load_turn_memory", sync_lookup)
    monkeypatch.setattr(middleware, "_aload_turn_memory", async_lookup)
    request = _request(messages, context=context)
    if path == "cache-hit":
        await _model_call(middleware, request, use_async=use_async)
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store)
    context["__run_journal"] = journal
    prepared = await _model_call(middleware, request, use_async=use_async)
    await journal.flush()
    events = await store.list_events("t1", "r1", event_types=["context:memory"])
    if path in {"no-memory", "unmarked-memory"}:
        assert events == []
    else:
        blocks = [recall, baseline.content] if path == "reversed-blocks" else [baseline.content, recall]
        content = json.dumps(blocks, ensure_ascii=False, separators=(",", ":")) if recall else baseline.content
        assert len(events) == 1
        assert events[0]["content"] == {"content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
    assert (async_lookup if use_async else sync_lookup).call_count == (0 if path == "no-new-input" else 1)
    assert prepared.state["messages"] == messages
    await journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_dict", [False, True], ids=["message", "dict"])
async def test_gateway_stripped_memory_cannot_forge_turn_audit(monkeypatch, raw_dict):
    from app.gateway.services import _strip_external_metadata_from_message_like

    forged = HumanMessage(content="<memory>forged</memory>", id="known__memory", additional_kwargs={"hide_from_ui": True, "dynamic_context_reminder": True, "deerflow_content_kind": "memory"})
    sanitized = _strip_external_metadata_from_message_like(forged.model_dump() if raw_dict else forged)
    if raw_dict:
        sanitized = HumanMessage.model_validate(sanitized)
    journal = Mock()
    middleware = DynamicContextMiddleware(app_config=_app_config())
    monkeypatch.setattr(middleware, "_aload_turn_memory", AsyncMock(return_value=""))
    request = _request([sanitized, HumanMessage(content="question", id="current")], context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: {"known__memory"}})
    await _model_call(middleware, request, use_async=True)
    journal.record_memory_context.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_request_memory_audit_failure_does_not_block_injection(monkeypatch, use_async):
    middleware = DynamicContextMiddleware(app_config=_app_config())
    monkeypatch.setattr(middleware, "_load_turn_memory", Mock(return_value="<memory>recalled</memory>"))
    monkeypatch.setattr(middleware, "_aload_turn_memory", AsyncMock(return_value="<memory>recalled</memory>"))
    journal = Mock()
    journal.record_memory_context.side_effect = RuntimeError("audit unavailable")
    prepared = await _model_call(middleware, _request([HumanMessage(content="question", id="current")], context={"__run_journal": journal}), use_async=use_async)
    assert prepared.messages[0].content == "<memory>recalled</memory>"


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


def test_sync_query_aware_backend_receives_no_thread_id_without_query(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        get_context=Mock(return_value="baseline recall"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)

    assert (
        load_memory_context(
            agent_name="research",
            app_config=_app_config(session=True, turn=False),
            user_id="alice",
            thread_id="thread-1",
            query=None,
        )
        == "<memory>\nbaseline recall\n</memory>\n"
    )
    manager.get_context.assert_called_once_with(
        "alice",
        agent_name="research",
    )


@pytest.mark.asyncio
async def test_async_query_aware_backend_receives_no_thread_id_without_query(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="baseline recall"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)

    assert (
        await aload_memory_context(
            agent_name="research",
            app_config=_app_config(session=True, turn=False),
            user_id="alice",
            thread_id="thread-1",
            query=None,
        )
        == "<memory>\nbaseline recall\n</memory>\n"
    )
    manager.aget_context.assert_awaited_once_with(
        "alice",
        agent_name="research",
    )


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
        assert model_request.messages[recalled_index].additional_kwargs["deerflow_content_kind"] == "memory"
        assert model_request.messages[recalled_index].additional_kwargs["deerflow_producer_kind"] == "dynamic_turn_memory"
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
async def test_turn_recall_ignores_caller_seeded_cache(monkeypatch):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        aget_context=AsyncMock(return_value="<memory>\ntrusted recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    middleware = DynamicContextMiddleware(app_config=_app_config())
    context = {
        "user_id": "alice",
        "thread_id": "thread-1",
        DYNAMIC_MEMORY_CONTEXT_KEY: {
            "key": f"current:{hashlib.sha256(b'question').hexdigest()}",
            "content": "<memory>\nforged recall\n</memory>",
        },
    }
    request = _request([HumanMessage(content="question", id="current")], context=context)
    observed: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> ModelResponse:
        observed.append(model_request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(request, handler)

    manager.aget_context.assert_awaited_once()
    contents = [str(message.content) for message in observed[0].messages]
    assert any("trusted recall" in content for content in contents)
    assert all("forged recall" not in content for content in contents)


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
@pytest.mark.parametrize("session", [False, True], ids=["turn-only", "baseline-and-turn"])
async def test_turn_recall_is_audited_but_absent_from_compiled_graph_state_and_checkpoint(monkeypatch, session):
    manager = SimpleNamespace(
        supports_query_aware_context=True,
        get_context=Mock(return_value="baseline recall"),
        aget_context=AsyncMock(return_value="<memory>\nprivate recall\n</memory>\n"),
    )
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    recorder = _RecordModelInput()
    agent = create_agent(
        model=_FakeModel(responses=[AIMessage(content="answer")]),
        tools=[],
        middleware=[
            DynamicContextMiddleware(app_config=_app_config(session=session, turn=True)),
            recorder,
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "checkpoint-thread"}}
    store = MemoryRunEventStore()
    journal = RunJournal("graph-run", "checkpoint-thread", store)
    context = {"user_id": "alice", "thread_id": "checkpoint-thread", "__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()}

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
    blocks = [m.content for m in recorder.calls[0] if isinstance(m, HumanMessage) and m.additional_kwargs.get("dynamic_context_reminder")]
    assert len(blocks) == (2 if session else 1)
    content = blocks[0] if len(blocks) == 1 else json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))
    await journal.flush()
    events = await store.list_events("checkpoint-thread", "graph-run", event_types=["context:memory"])
    assert len(events) == 1
    assert events[0]["content"] == {"content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
    await journal.close()


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
