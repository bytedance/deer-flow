"""Honcho capture excludes framework context while preserving human answers."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict
from langgraph.runtime import Runtime

from deerflow.agents.memory import manager as memory_manager
from deerflow.agents.memory.backends.honcho import honcho_manager
from deerflow.agents.memory.backends.honcho.client import HonchoClient
from deerflow.agents.memory.manager import _host_default_should_keep_hidden_message
from deerflow.agents.middlewares import memory_middleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
from deerflow.config.memory_config import MemoryConfig


@pytest.fixture
def capture(monkeypatch):
    requests = []
    managers = []

    def record(request):
        requests.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(honcho_manager, "HonchoClient", lambda config: HonchoClient(config, transport=httpx.MockTransport(record)))

    def create(hook=_host_default_should_keep_hidden_message, mode="middleware"):
        manager = honcho_manager.HonchoMemoryManager.from_config(
            {"base_url": "http://honcho.test", "workspace_overrides": {"alice": "test-workspace"}, "user_peer_overrides": {"alice": "user-peer"}},
            mode=mode,
            should_keep_hidden_message=hook,
        )
        managers.append(manager)
        return manager

    yield create, requests
    for manager in managers:
        manager.close()


def _write(manager, method, messages):
    result = getattr(manager, method)("thread-1", messages, user_id="alice")
    if method == "aadd":
        asyncio.run(result)


def _reminder():
    update = TodoMiddleware().before_model({"todos": [{"content": "Check deployment", "status": "pending"}], "messages": []}, Runtime(context={}))
    assert update is not None
    return update["messages"][0]


def _answer(kind):
    payload = {"version": 1, "kind": "human_input_response", "source": "ask_clarification", "request_id": "request-1", "response_kind": kind, "value": "Use staging"}
    if kind == "option":
        payload["option_id"] = "staging"
    return HumanMessage("Use staging", additional_kwargs={"hide_from_ui": True, "human_input_response": payload})


@pytest.mark.parametrize("method", ["add", "aadd", "add_nowait"])
@pytest.mark.parametrize("mode", ["middleware", "tool"])
def test_http_capture_excludes_reminder_and_preserves_human_answers(capture, method, mode):
    create, requests = capture
    manager = create(mode=mode)
    messages = [HumanMessage("I prefer Python."), _reminder(), _answer("text"), _answer("option"), AIMessage("Understood.")]
    original = messages_to_dict(messages)

    _write(manager, method, messages)

    writes = [json.loads(request.content) for request in requests if request.url.path.endswith("/messages")]
    assert writes == [
        {
            "messages": [
                {"peer_id": "user-peer", "content": "I prefer Python."},
                {"peer_id": "user-peer", "content": "Use staging"},
                {"peer_id": "user-peer", "content": "Use staging"},
                {"peer_id": "deerflow", "content": "Understood."},
            ]
        }
    ]
    assert all(request.url.path.startswith("/v3/workspaces/test-workspace/") for request in requests)
    assert messages_to_dict(messages) == original


@pytest.mark.parametrize("method", ["add", "aadd", "add_nowait"])
@pytest.mark.parametrize("hook", [None, "not-callable", _host_default_should_keep_hidden_message])
def test_framework_only_batch_makes_no_http_requests(capture, method, hook):
    create, requests = capture
    _write(create(hook=hook), method, [_reminder()])
    assert requests == []


@pytest.mark.parametrize("kind", ["missing-value", "missing-option-id", "unknown-kind"])
def test_malformed_hidden_clarification_is_not_written(capture, kind):
    create, requests = capture
    answer = _answer("option")
    payload = answer.additional_kwargs["human_input_response"]
    if kind == "missing-value":
        payload["value"] = " "
    elif kind == "missing-option-id":
        payload.pop("option_id")
    else:
        payload["response_kind"] = "other"
    _write(create(), "add", [answer])
    assert requests == []


def test_host_hook_controls_hidden_human_admission(capture):
    create, requests = capture
    seen = []

    def keep(metadata):
        seen.append(metadata)
        return metadata.get("keep_for_memory") is True

    messages = [
        HumanMessage("visible"),
        HumanMessage("keep", additional_kwargs={"hide_from_ui": True, "keep_for_memory": True}),
        _answer("text"),
        AIMessage("answer"),
    ]
    _write(create(hook=keep), "add", messages)
    writes = [json.loads(request.content) for request in requests if request.url.path.endswith("/messages")]
    assert [item["content"] for item in writes[0]["messages"]] == ["visible", "keep", "answer"]
    assert seen == [messages[1].additional_kwargs, messages[2].additional_kwargs]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_after_agent_does_not_write_persisted_todo_reminder(capture, monkeypatch, asynchronous):
    create, requests = capture
    manager = create()
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "alice"})
    state = {"messages": [HumanMessage("hello"), _reminder(), _answer("text"), AIMessage("hi")]}
    if asynchronous:
        asyncio.run(middleware.aafter_agent(state, runtime))
    else:
        middleware.after_agent(state, runtime)
    writes = [json.loads(request.content) for request in requests if request.url.path.endswith("/messages")]
    assert [item["content"] for item in writes[0]["messages"]] == ["hello", "Use staging", "hi"]


@pytest.mark.parametrize("method", ["add", "aadd", "add_nowait"])
def test_host_factory_preserves_clarification_but_drops_framework_context(capture, monkeypatch, method):
    _, requests = capture
    config = MemoryConfig(enabled=True, manager_class="honcho", backend_config={"base_url": "http://honcho.test"})
    monkeypatch.setattr(memory_manager, "get_memory_config", lambda: config)
    monkeypatch.setattr(memory_manager, "_memory_manager", None)
    monkeypatch.setattr(memory_manager, "_backends_cache", None)
    monkeypatch.setattr(memory_manager, "_memory_judge_signature", None)
    manager = memory_manager.get_memory_manager()
    try:
        _write(manager, method, [_reminder(), _answer("text"), _answer("option")])
        writes = [json.loads(request.content) for request in requests if request.url.path.endswith("/messages")]
        assert [item["content"] for item in writes[0]["messages"]] == ["Use staging", "Use staging"]
    finally:
        manager.close()


@pytest.mark.parametrize("method", ["add", "aadd", "add_nowait"])
@pytest.mark.parametrize("mode", ["middleware", "tool"])
def test_hidden_hook_failure_preserves_other_messages(capture, caplog, method, mode):
    create, requests = capture
    seen = []

    def keep(metadata):
        seen.append(metadata)
        if metadata.get("fail_filter"):
            raise RuntimeError("private-filter-error")
        return _host_default_should_keep_hidden_message(metadata)

    hidden = HumanMessage("private-hidden-content", additional_kwargs={"hide_from_ui": True, "fail_filter": True})
    messages = [HumanMessage("before"), hidden, HumanMessage("after"), _answer("text"), AIMessage("reply")]
    original = messages_to_dict(messages)

    _write(create(hook=keep, mode=mode), method, messages)

    writes = [json.loads(request.content) for request in requests if request.url.path.endswith("/messages")]
    assert writes == [
        {
            "messages": [
                {"peer_id": "user-peer", "content": "before"},
                {"peer_id": "user-peer", "content": "after"},
                {"peer_id": "user-peer", "content": "Use staging"},
                {"peer_id": "deerflow", "content": "reply"},
            ]
        }
    ]
    assert seen == [hidden.additional_kwargs, messages[3].additional_kwargs]
    assert messages_to_dict(messages) == original
    assert caplog.messages == ["honcho memory: hidden message filter failed; skipping hidden message"]
    assert "private-filter-error" not in caplog.text
    assert "private-hidden-content" not in caplog.text


@pytest.mark.parametrize("method", ["add", "aadd", "add_nowait"])
def test_only_failing_hidden_hook_makes_no_http_requests(capture, caplog, method):
    create, requests = capture

    def keep(metadata):
        raise RuntimeError("private-filter-error")

    _write(create(hook=keep), method, [_reminder()])

    assert requests == []
    assert caplog.messages == ["honcho memory: hidden message filter failed; skipping hidden message"]
    assert "private-filter-error" not in caplog.text
