"""Tool-call assistant turns must not become final-response memory inputs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_from_dict, messages_to_dict
from langchain_openai.chat_models.base import _convert_dict_to_message

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import filter_messages_for_memory as filter_deermem
from deerflow.agents.memory.backends.mem0.client import Mem0Client
from deerflow.agents.memory.backends.mem0.mem0_manager import Mem0Manager
from deerflow.agents.memory.backends.mem0.message_filtering import filter_messages_for_memory as filter_mem0

_ATTEMPT_TEXT = "I will save the nightly production deployment preference."
_USER_TEXT = "Inspect the deployment settings before changing anything."
_FINAL_TEXT = "The settings were inspected; no deployment preference was saved."


def _assistant_attempt(kind: str) -> AIMessage:
    if kind == "parsed":
        return AIMessage(content=_ATTEMPT_TEXT, tool_calls=[{"name": "memory_add", "args": {}, "id": "call-1"}])
    if kind == "invalid":
        return AIMessage(content=_ATTEMPT_TEXT, invalid_tool_calls=[{"name": "memory_add", "args": "{broken", "id": "call-1"}])
    if kind == "legacy":
        return _convert_dict_to_message({"role": "assistant", "content": _ATTEMPT_TEXT, "function_call": {"name": "memory_add", "arguments": "{}"}})
    raw = [{"id": "call-1", "type": "function", "function": {"name": "memory_add", "arguments": "{broken"}}]
    if kind == "raw":
        # Provider-raw fallback with neither structured view (e.g. an older checkpoint).
        return AIMessage(content=_ATTEMPT_TEXT).model_copy(update={"additional_kwargs": {"tool_calls": raw}})
    message = _convert_dict_to_message({"role": "assistant", "content": _ATTEMPT_TEXT, "tool_calls": raw})
    assert isinstance(message, AIMessage)
    assert not message.tool_calls and message.invalid_tool_calls
    # Exercise the message serialization used when persisting/reloading history.
    return messages_from_dict(messages_to_dict([message]))[0]


@pytest.mark.parametrize("filter_messages", [filter_deermem, filter_mem0], ids=["deermem", "mem0"])
@pytest.mark.parametrize("kind", ["parsed", "invalid", "provider-invalid", "raw", "legacy"])
def test_filter_excludes_all_tool_call_views_without_mutating_history(filter_messages, kind: str) -> None:
    attempt = _assistant_attempt(kind)
    messages = [HumanMessage(content=_USER_TEXT), attempt, ToolMessage(content="Not executed", tool_call_id="call-1", status="error"), AIMessage(content=_FINAL_TEXT)]
    original = messages_to_dict(messages)

    kept = filter_messages(messages)

    assert kept == [messages[0], messages[-1]]
    assert kept[0] is messages[0] and kept[1] is messages[-1]
    assert messages_to_dict(messages) == original


@pytest.mark.parametrize("filter_messages", [filter_deermem, filter_mem0], ids=["deermem", "mem0"])
@pytest.mark.parametrize("kwargs", [{}, {"tool_calls": []}, {"function_call": None}, {"tool_calls": [], "function_call": {}}])
def test_empty_call_views_keep_final_response(filter_messages, kwargs: dict) -> None:
    final = AIMessage(content=[{"type": "text", "text": _FINAL_TEXT}], additional_kwargs=kwargs)
    assert filter_messages([final]) == [final]


@pytest.mark.parametrize("filter_messages", [filter_deermem, filter_mem0], ids=["deermem", "mem0"])
def test_invalid_attempt_does_not_consume_upload_ack_filter(filter_messages) -> None:
    upload = HumanMessage(content="<current_uploads>\nsettings.yaml\n</current_uploads>")
    attempt = _assistant_attempt("provider-invalid")
    ack = AIMessage(content="I see the uploaded settings.")
    user = HumanMessage(content=_USER_TEXT)
    final = AIMessage(content=_FINAL_TEXT)
    assert filter_messages([upload, attempt, ack, user, final]) == [user, final]


@pytest.mark.parametrize("method", ["add", "add_nowait"])
@pytest.mark.parametrize("include_final", [False, True])
def test_deermem_queue_contains_only_user_and_final_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, include_final: bool) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    # Keep the real queue deterministic; do not launch background extraction.
    monkeypatch.setattr(manager._queue, "_schedule_timer", lambda *args, **kwargs: None)
    messages = [HumanMessage(content=_USER_TEXT), _assistant_attempt("provider-invalid")]
    if include_final:
        messages.append(AIMessage(content=_FINAL_TEXT))
    original = messages_to_dict(messages)
    try:
        getattr(manager, method)("thread-1", messages, user_id="alice", agent_name="deployment-agent")
        contexts = manager._queue._items
        if include_final:
            assert len(contexts) == 1
            context = contexts[0]
            assert context.messages == [messages[0], messages[-1]]
            assert (context.thread_id, context.user_id, context.agent_name) == ("thread-1", "alice", "deployment-agent")
        else:
            # An attempted call is not the assistant reply required for extraction.
            assert contexts == []
        assert messages_to_dict(messages) == original
    finally:
        manager.cancel_by_agent("deployment-agent", user_id="alice")
        manager.close()


@pytest.mark.parametrize("method", ["add", "aadd"])
@pytest.mark.parametrize("include_final", [False, True])
def test_mem0_http_payload_excludes_invalid_attempt(monkeypatch: pytest.MonkeyPatch, method: str, include_final: bool) -> None:
    monkeypatch.setenv("MEM0_API_KEY", "offline-test-key")
    payloads: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/v3/memories/add/"
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "PENDING"})

    manager = Mem0Manager(backend_config={"startup_policy": "tolerate"})
    manager.close()
    manager._client = Mem0Client(base_url="https://mem0.test", api_key="offline-test-key", transport=httpx.MockTransport(record))
    messages = [HumanMessage(content=_USER_TEXT), _assistant_attempt("provider-invalid")]
    if include_final:
        messages.append(AIMessage(content=_FINAL_TEXT))
    original = messages_to_dict(messages)
    try:
        result = getattr(manager, method)("thread-1", messages, user_id="alice", agent_name="deployment-agent")
        if method == "aadd":
            asyncio.run(result)
        expected = [{"role": "user", "content": _USER_TEXT}]
        if include_final:
            expected.append({"role": "assistant", "content": _FINAL_TEXT})
        assert payloads == [{"messages": expected, "user_id": "alice", "agent_id": "deployment-agent", "run_id": "thread-1"}]
        assert messages_to_dict(messages) == original
    finally:
        manager.close()
