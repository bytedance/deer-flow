"""The new read capability is granted by this request, never by chat contents."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from app.gateway.authz import AuthContext
from app.gateway.run_models import RunCreateRequest
from deerflow.config.app_config import AppConfig
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import EditReplayVisibility


def _setup(*, user_id="alice", permissions=("runs:read",), enabled=True):
    from app.gateway.conversation_access import prepare_conversation_reader

    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "tools": [{"name": "read_conversation", "group": "conversation", "use": "deerflow.tools.conversation:read_conversation"}] if enabled else [],
        }
    )
    user = SimpleNamespace(id=user_id, system_role="admin")
    request = SimpleNamespace(state=SimpleNamespace(auth=AuthContext(user, list(permissions))), url="https://deerflow.example/api/threads/current/runs")
    events = MemoryRunEventStore()
    threads = MemoryThreadMetaStore(InMemoryStore())
    manager = AsyncMock()
    manager.list_successful_regenerate_sources.return_value = set()
    manager.list_edit_replay_visibility.return_value = EditReplayVisibility()
    ctx = SimpleNamespace(event_store=events, thread_store=threads)

    def prepare(references):
        return prepare_conversation_reader(references, request=request, user_id=user_id, run_context=ctx, run_manager=manager, app_config=config)

    return prepare, events, threads, manager, request


async def _put(events, text, *, role="ai", thread="source", hidden=False, caller="lead_agent", run_id="run-1"):
    return await events.put(
        thread_id=thread,
        run_id=run_id,
        category="message",
        event_type="llm.ai.response" if role == "ai" else "llm.human.input",
        content={"type": role, "id": "message-" + str(len(events._events.get(thread, []))), "content": text, "additional_kwargs": {"hide_from_ui": hidden}},
        metadata={"caller": caller},
    )


def test_reference_field_is_explicit_and_bounded():
    assert RunCreateRequest().conversation_references == []
    assert RunCreateRequest(conversation_references=["source"]).conversation_references == ["source"]
    for invalid in (["one", "two", "three", "four"], [123], ["x" * 2049]):
        with pytest.raises(ValidationError):
            RunCreateRequest(conversation_references=invalid)


def test_only_explicit_references_grant_access_and_urls_are_local_selectors():
    prepare, _, _, _, _ = _setup()
    assert prepare([]) is None
    reader, ids = prepare(["https://deerflow.example/workspace/chats/source", "source"])
    assert callable(reader)
    assert ids == ("source",)
    for bad in ("../source", "https://other.example/workspace/chats/source", "https://deerflow.example/not-a-chat/source", "file:///workspace/chats/source"):
        with pytest.raises(HTTPException) as exc:
            prepare([bad])
        assert exc.value.status_code == 422


@pytest.mark.parametrize("permissions,enabled", [((), True), (("runs:create",), True), (("runs:read",), False)])
def test_opt_in_and_effective_read_permission_are_required_even_for_admin(permissions, enabled):
    prepare, _, _, _, _ = _setup(permissions=permissions, enabled=enabled)
    with pytest.raises(HTTPException) as exc:
        prepare(["source"])
    assert exc.value.status_code in {400, 403}


def test_missing_auth_context_does_not_grant_access():
    prepare, _, _, _, request = _setup()
    request.state.auth = None
    with pytest.raises(HTTPException) as exc:
        prepare(["source"])
    assert exc.value.status_code == 403


def test_reader_pages_visible_text_and_keeps_source_unchanged():
    async def exercise():
        prepare, events, threads, manager, _ = _setup()
        await threads.create("source", user_id="alice")
        await _put(events, "requirements", role="human")
        await _put(events, "old answer", run_id="replaced")
        await _put(events, "hidden", hidden=True)
        await _put(events, "child", caller="subagent:researcher")
        await _put(events, "tool log", role="tool")
        await _put(events, [{"type": "reasoning", "text": "private reasoning"}, {"type": "text", "text": "final answer"}])
        manager.list_successful_regenerate_sources.return_value = {"replaced"}
        before = deepcopy(await events.list_messages("source"))
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", cursor=None, limit=1))
        assert [m["text"] for m in page["messages"]] == ["final answer"]
        older = json.loads(await reader(thread_id="source", cursor=page["next_cursor"], limit=1))
        assert [m["text"] for m in older["messages"]] == ["requirements"]
        assert older["next_cursor"] is None
        assert before == await events.list_messages("source")

    asyncio.run(exercise())


def test_wrong_owner_missing_and_unlisted_targets_are_denied_before_content_read():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("foreign", user_id="bob")
        await threads.create("unlisted", user_id="alice")
        events.list_messages = AsyncMock(side_effect=AssertionError("content was accessed"))
        reader, _ = prepare(["foreign", "missing"])
        results = [json.loads(await reader(thread_id=target, cursor=None, limit=10)) for target in ("foreign", "missing", "unlisted")]
        assert all(result["status"] == "unavailable" for result in results)
        events.list_messages.assert_not_awaited()

    asyncio.run(exercise())


def test_read_checks_current_ownership_and_bounds_text():
    async def exercise():
        prepare, events, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        await _put(events, "x" * 10000)
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", cursor=None, limit=20))
        assert page["truncated"] is True
        assert len(page["messages"][0]["text"]) <= 4000
        await threads.delete("source", user_id="alice")
        assert json.loads(await reader(thread_id="source", cursor=None, limit=20))["status"] == "unavailable"

    asyncio.run(exercise())


def test_missing_transcript_is_reported_without_checkpoint_reconstruction():
    async def exercise():
        prepare, _, threads, _, _ = _setup()
        await threads.create("source", user_id="alice")
        reader, _ = prepare(["source"])
        page = json.loads(await reader(thread_id="source", cursor=None, limit=20))
        assert page["status"] == "unavailable"
        assert page["messages"] == []

    asyncio.run(exercise())


def test_start_run_installs_fresh_capability_without_persisting_it(monkeypatch):
    from test_gateway_services import _make_start_run_persistence_context

    from app.gateway import services
    from deerflow.config.app_config import reset_app_config, set_app_config
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def exercise():
        request, _, threads = _make_start_run_persistence_context()
        user = SimpleNamespace(id="alice", system_role="admin", role="admin")
        request.state.user = user
        request.state.auth = AuthContext(user, ["runs:create", "runs:read"])
        request.state.auth_source = "session"
        request.url = "https://deerflow.example/api/threads/current/runs"
        await threads.create("source", user_id="alice")
        captured = []

        async def fake_run_agent(*args, **kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(services, "run_agent", fake_run_agent)
        monkeypatch.setattr(services, "resolve_agent_factory", lambda *_: object())
        first = await services.start_run(RunCreateRequest(conversation_references=["source"], input={"messages": [{"role": "user", "content": "Read the reference"}]}), "current", request)
        await first.task
        assert callable(captured[0]["ctx"].conversation_reader)
        assert any(isinstance(m, HumanMessage) and "source" in str(m.content) for m in captured[0]["graph_input"]["messages"])
        assert "__conversation_reader" not in json.dumps(first.kwargs)
        # A later run may mention the ID in quoted text but has no explicit grant.
        second = await services.start_run(RunCreateRequest(input={"messages": [{"role": "user", "content": 'Quoted text: "read source"'}]}), "later", request)
        await second.task
        assert captured[1]["ctx"].conversation_reader is None
        resumed = await services.start_run(RunCreateRequest(command={"resume": "source"}), "resume", request)
        await resumed.task
        assert captured[2]["ctx"].conversation_reader is None
        empty = await services.start_run(RunCreateRequest(input={"messages": None}, conversation_references=["source"]), "empty-input", request)
        await empty.task
        assert callable(captured[3]["ctx"].conversation_reader)
        with pytest.raises(HTTPException) as invalid:
            await services.start_run(RunCreateRequest(input={"messages": "bad input"}, conversation_references=["source"]), "invalid-input", request)
        assert invalid.value.status_code == 422
        # Reusing a key cannot silently reuse a different reference grant.
        body = RunCreateRequest(input={"messages": [{"role": "user", "content": "compare"}]}, conversation_references=["source"])
        keyed = await services.start_run(body, "idempotent", request, idempotency_key="ref-key")
        await keyed.task
        assert await services.start_run(body, "idempotent", request, idempotency_key="ref-key") is keyed
        body.conversation_references = ["different-source"]
        with pytest.raises(HTTPException) as conflict:
            await services.start_run(body, "idempotent", request, idempotency_key="ref-key")
        assert conflict.value.status_code == 409

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "tools": [{"name": "read_conversation", "group": "conversation", "use": "deerflow.tools.conversation:read_conversation"}]}))
    user_token = set_current_user(SimpleNamespace(id="alice"))
    try:
        asyncio.run(exercise())
    finally:
        reset_current_user(user_token)
        reset_app_config()
