"""Tests for thread-level token usage and context-window usage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.gateway import context_usage
from app.gateway.context_usage import _read_context_usage_breakdown
from app.gateway.routers import thread_runs
from deerflow.agents.middlewares.context_usage_middleware import CONTEXT_USAGE_KEY


def _aggregate_result() -> dict:
    return {
        "total_tokens": 150,
        "total_input_tokens": 90,
        "total_output_tokens": 60,
        "total_runs": 2,
        "by_model": {"unknown": {"tokens": 150, "runs": 2}},
        "by_caller": {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        },
    }


def _make_run_store(*, model_name: str | None = None) -> MagicMock:
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    runs = [{"model_name": model_name}] if model_name else []
    run_store.list_by_thread = AsyncMock(return_value=runs)
    return run_store


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


def test_thread_token_usage_returns_stable_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    build_context_usage = AsyncMock(return_value=None)
    monkeypatch.setattr(thread_runs, "build_context_usage", build_context_usage)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        **_aggregate_result(),
        "context_usage": None,
    }
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", user_id=None)
    build_context_usage.assert_awaited_once()


def test_thread_token_usage_can_include_active_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    build_context_usage = AsyncMock(return_value=None)
    monkeypatch.setattr(thread_runs, "build_context_usage", build_context_usage)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True, user_id=None)


def test_thread_token_usage_serializes_context_percentage(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    monkeypatch.setattr(
        thread_runs,
        "build_context_usage",
        AsyncMock(
            return_value={
                "token_count": 350,
                "max_context_tokens": 1000,
                "percentage": 35.0,
            }
        ),
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json()["context_usage"] == {
        "token_count": 350,
        "max_context_tokens": 1000,
        "percentage": 35.0,
        "breakdown": None,
    }


def test_thread_token_usage_serializes_context_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    breakdown = {
        "total_tokens": 420,
        "percentage": 42.0,
        "remaining_tokens": 580,
        "system_prompt_tokens": 100,
        "builtin_tools_tokens": 40,
        "mcp_tools_tokens": 20,
        "skill_body_tokens": 30,
        "memory_tokens": 10,
        "task_state_tokens": 5,
        "other_injection_tokens": 15,
        "conversation_tokens": 150,
        "tool_result_tokens": 50,
        "model_name": "thread-model",
        "context_window": 1000,
        "captured_at": "2026-11-12T00:00:00+00:00",
    }
    monkeypatch.setattr(
        thread_runs,
        "build_context_usage",
        AsyncMock(return_value={"token_count": 350, "max_context_tokens": 1000, "percentage": 35.0, "breakdown": breakdown}),
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json()["context_usage"]["breakdown"] == breakdown


def test_build_context_usage_payload_computes_percentage() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=1000) == {
        "token_count": 350,
        "max_context_tokens": 1000,
        "percentage": 35.0,
        "breakdown": None,
    }


def test_build_context_usage_payload_handles_unknown_capacity() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=None) == {
        "token_count": 350,
        "max_context_tokens": None,
        "percentage": None,
        "breakdown": None,
    }


@pytest.mark.asyncio
async def test_resolve_thread_model_prefers_latest_run() -> None:
    run_store = _make_run_store(model_name="thread-model")
    app_config = SimpleNamespace(models=[SimpleNamespace(name="fallback-model")])

    assert await context_usage._resolve_thread_model_name(run_store, "thread-1", app_config) == "thread-model"


@pytest.mark.asyncio
async def test_resolve_thread_model_falls_back_to_first_configured_model() -> None:
    run_store = _make_run_store()
    app_config = SimpleNamespace(models=[SimpleNamespace(name="fallback-model")])

    assert await context_usage._resolve_thread_model_name(run_store, "thread-1", app_config) == "fallback-model"


@pytest.mark.asyncio
async def test_build_context_usage_counts_materialized_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [SimpleNamespace(content="hello")]
    snapshot = SimpleNamespace(values={"messages": messages})
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(accessor, {"configurable": {"thread_id": "thread-1"}})),
    )
    model_config = SimpleNamespace(context_window=1000)
    app_config = SimpleNamespace(
        models=[SimpleNamespace(name="fallback-model")],
        get_model_config=lambda name: model_config if name == "thread-model" else None,
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: app_config)
    monkeypatch.setattr(context_usage, "_count_messages_approximately", lambda value: 250 if value == messages else 0)

    result = await context_usage.build_context_usage(
        request=SimpleNamespace(app=SimpleNamespace()),
        thread_id="thread-1",
        run_store=_make_run_store(model_name="thread-model"),
    )

    assert result == {
        "token_count": 250,
        "max_context_tokens": 1000,
        "percentage": 25.0,
        "breakdown": None,
    }


def _snapshot_message(**counts) -> AIMessage:
    from deerflow.agents.middlewares.context_usage_middleware import CONTEXT_USAGE_KEY

    snapshot = {
        "system_prompt_tokens": 100,
        "builtin_tools_tokens": 40,
        "mcp_tools_tokens": 20,
        "skill_body_tokens": 30,
        "memory_tokens": 10,
        "task_state_tokens": 5,
        "other_injection_tokens": 15,
        "conversation_tokens": 150,
        "tool_result_tokens": 50,
        "model_name": "thread-model",
        "context_window": 1000,
        "captured_at": "2026-11-12T00:00:00+00:00",
        **counts,
    }
    return AIMessage(content="done", id="ai-1", additional_kwargs={CONTEXT_USAGE_KEY: snapshot})


@pytest.mark.asyncio
async def test_build_context_usage_reads_the_last_stamped_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import HumanMessage

    older = _snapshot_message(conversation_tokens=1)
    newer = _snapshot_message(conversation_tokens=2)
    messages = [HumanMessage(content="hi"), older, newer]
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(values={"messages": messages}))), {})),
    )
    model_config = SimpleNamespace(context_window=1000)
    monkeypatch.setattr(
        context_usage,
        "get_config",
        lambda: SimpleNamespace(models=[SimpleNamespace(name="fallback-model")], get_model_config=lambda name: model_config),
    )
    monkeypatch.setattr(context_usage, "_count_messages_approximately", lambda value: 250)

    result = await context_usage.build_context_usage(request=SimpleNamespace(app=SimpleNamespace()), thread_id="thread-1", run_store=_make_run_store(model_name="thread-model"))

    assert result["token_count"] == 250
    assert result["breakdown"]["total_tokens"] == 272
    assert result["breakdown"]["percentage"] == 27.2
    assert result["breakdown"]["remaining_tokens"] == 728
    assert result["breakdown"]["conversation_tokens"] == 2
    assert result["breakdown"]["model_name"] == "thread-model"


@pytest.mark.asyncio
async def test_build_context_usage_breakdown_is_null_without_a_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import AIMessage, HumanMessage

    messages = [HumanMessage(content="hi"), AIMessage(content="plain", id="ai-1")]
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(values={"messages": messages}))), {})),
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace(models=[], get_model_config=lambda name: None))
    monkeypatch.setattr(context_usage, "_count_messages_approximately", lambda value: 10)

    result = await context_usage.build_context_usage(request=SimpleNamespace(app=SimpleNamespace()), thread_id="thread-1", run_store=_make_run_store())

    assert result["token_count"] == 10
    assert result["breakdown"] is None


@pytest.mark.asyncio
async def test_build_context_usage_skips_a_malformed_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import AIMessage

    from deerflow.agents.middlewares.context_usage_middleware import CONTEXT_USAGE_KEY

    forged = AIMessage(content="done", id="ai-1", additional_kwargs={CONTEXT_USAGE_KEY: {"conversation_tokens": -5}})
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(values={"messages": [forged]}))), {})),
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace(models=[], get_model_config=lambda name: None))
    monkeypatch.setattr(context_usage, "_count_messages_approximately", lambda value: 10)

    result = await context_usage.build_context_usage(request=SimpleNamespace(app=SimpleNamespace()), thread_id="thread-1", run_store=_make_run_store())

    assert result["breakdown"] is None


@pytest.mark.asyncio
async def test_build_context_usage_returns_none_when_checkpoint_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(side_effect=RuntimeError("checkpoint unavailable")),
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace())

    result = await context_usage.build_context_usage(
        request=SimpleNamespace(app=SimpleNamespace()),
        thread_id="thread-1",
        run_store=_make_run_store(),
    )

    assert result is None


def _stamped_ai(*, tokens: int = 10, window: int = 100) -> AIMessage:
    return AIMessage(
        content="answer",
        additional_kwargs={
            CONTEXT_USAGE_KEY: {
                "conversation_tokens": tokens,
                "context_window": window,
                "model_name": "thread-model",
                "captured_at": "2026-11-13T00:00:00+00:00",
            }
        },
    )


def test_read_breakdown_returns_the_newest_stamped_response() -> None:
    messages = [
        HumanMessage(content="q1"),
        _stamped_ai(tokens=10, window=100),
        HumanMessage(content="q2"),
        _stamped_ai(tokens=20, window=200),
    ]

    payload = _read_context_usage_breakdown(messages)

    assert payload is not None
    assert payload["total_tokens"] == 20
    assert payload["context_window"] == 200


def test_read_breakdown_keeps_the_last_request_across_a_new_user_turn() -> None:
    messages = [HumanMessage(content="q"), _stamped_ai(tokens=10), HumanMessage(content="next")]

    assert _read_context_usage_breakdown(messages) is not None


def test_read_breakdown_skips_a_snapshot_the_context_has_grown_past() -> None:
    messages = [
        HumanMessage(content="q"),
        _stamped_ai(),
        ToolMessage(content="result", tool_call_id="call-1"),
    ]

    assert _read_context_usage_breakdown(messages) is None
