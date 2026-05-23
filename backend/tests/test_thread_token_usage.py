"""Tests for thread-level token usage aggregation API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

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
    run_store.list_by_thread = AsyncMock(
        return_value=[{"model_name": model_name}] if model_name is not None else [],
    )
    return run_store


def _make_checkpoint_tuple(messages: list | None) -> SimpleNamespace | None:
    if messages is None:
        return None
    return SimpleNamespace(checkpoint={"channel_values": {"messages": messages}})


def _make_checkpointer(messages: list | None, *, raises: bool = False) -> MagicMock:
    checkpointer = MagicMock()
    if raises:
        checkpointer.aget_tuple = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        checkpointer.aget_tuple = AsyncMock(return_value=_make_checkpoint_tuple(messages))
    return checkpointer


def _make_app(
    run_store: MagicMock,
    *,
    checkpointer: MagicMock | None = None,
    models: list | None = None,
    monkeypatch=None,
):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    if checkpointer is not None:
        app.state.checkpointer = checkpointer
    if models is not None:
        if monkeypatch is None:
            raise RuntimeError("monkeypatch fixture is required when models are provided")
        fake_config = SimpleNamespace(
            models=models,
            get_model_config=lambda name: next((m for m in models if m.name == name), None),
        )
        monkeypatch.setattr(thread_runs, "get_config", lambda: fake_config)
    return app


def test_thread_token_usage_returns_stable_shape():
    """Baseline shape — no checkpointer / config, ``context_usage`` is omitted."""
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
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
        "context_usage": None,
    }
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1")


def test_thread_token_usage_can_include_active_runs():
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 175,
            "total_input_tokens": 120,
            "total_output_tokens": 55,
            "total_runs": 3,
            "by_model": {"unknown": {"tokens": 175, "runs": 3}},
            "by_caller": {
                "lead_agent": 145,
                "subagent": 25,
                "middleware": 5,
            },
        },
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    assert response.json()["total_tokens"] == 175
    assert response.json()["total_runs"] == 3
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


def test_context_usage_with_run_model_and_context_window(monkeypatch):
    """When the latest run has a model_name and that model has context_window, percentage is computed."""
    run_store = _make_run_store(model_name="gpt-4o")
    checkpointer = _make_checkpointer([{"type": "human", "content": "hello world"}])
    models = [
        SimpleNamespace(name="gpt-4o", context_window=1000),
        SimpleNamespace(name="other", context_window=2000),
    ]
    app = _make_app(run_store, checkpointer=checkpointer, models=models, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    payload = response.json()
    context = payload["context_usage"]
    assert context is not None
    assert context["max_context_tokens"] == 1000
    assert context["token_count"] > 0
    assert context["token_count"] <= 1000
    expected_pct = round(context["token_count"] / 1000 * 100, 1)
    assert context["percentage"] == expected_pct


def test_context_usage_falls_back_to_first_model_when_run_has_no_model(monkeypatch):
    """If the latest run lacks a model_name, fall back to models[0]."""
    run_store = _make_run_store(model_name=None)
    checkpointer = _make_checkpointer([{"type": "human", "content": "hi"}])
    models = [SimpleNamespace(name="default-model", context_window=500)]
    app = _make_app(run_store, checkpointer=checkpointer, models=models, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    context = response.json()["context_usage"]
    assert context is not None
    assert context["max_context_tokens"] == 500
    assert context["token_count"] > 0


def test_context_usage_percentage_is_none_when_model_has_no_context_window(monkeypatch):
    """Model without ``context_window`` -> percentage and max are None, count is still reported."""
    run_store = _make_run_store(model_name="gpt-4o")
    checkpointer = _make_checkpointer([{"type": "human", "content": "hello"}])
    models = [SimpleNamespace(name="gpt-4o", context_window=None)]
    app = _make_app(run_store, checkpointer=checkpointer, models=models, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    context = response.json()["context_usage"]
    assert context == {
        "token_count": context["token_count"],
        "max_context_tokens": None,
        "percentage": None,
    }
    assert context["token_count"] > 0


def test_context_usage_with_no_checkpoint_reports_zero_tokens(monkeypatch):
    """Brand-new thread with no checkpoint yet still gets a (zero) reading."""
    run_store = _make_run_store(model_name="gpt-4o")
    checkpointer = _make_checkpointer(None)
    models = [SimpleNamespace(name="gpt-4o", context_window=1000)]
    app = _make_app(run_store, checkpointer=checkpointer, models=models, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    context = response.json()["context_usage"]
    assert context == {
        "token_count": 0,
        "max_context_tokens": 1000,
        "percentage": 0.0,
    }


def test_context_usage_omitted_when_checkpointer_raises(monkeypatch):
    """A failing checkpointer should not break the endpoint, just hide context_usage."""
    run_store = _make_run_store(model_name="gpt-4o")
    checkpointer = _make_checkpointer(None, raises=True)
    models = [SimpleNamespace(name="gpt-4o", context_window=1000)]
    app = _make_app(run_store, checkpointer=checkpointer, models=models, monkeypatch=monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_usage"] is None
    # The legacy aggregation must still come back intact.
    assert payload["total_tokens"] == 150
