"""Tests for thread-level token usage and context-window usage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway import context_usage
from app.gateway.routers import thread_runs


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
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1")
    build_context_usage.assert_awaited_once()


def test_thread_token_usage_can_include_active_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    build_context_usage = AsyncMock(return_value=None)
    monkeypatch.setattr(thread_runs, "build_context_usage", build_context_usage)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


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
    }


def test_build_context_usage_payload_computes_percentage() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=1000) == {
        "token_count": 350,
        "max_context_tokens": 1000,
        "percentage": 35.0,
    }


def test_build_context_usage_payload_handles_unknown_capacity() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=None) == {
        "token_count": 350,
        "max_context_tokens": None,
        "percentage": None,
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
    }


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
