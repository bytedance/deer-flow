"""Tests for thread-level token usage aggregation API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway import context_usage
from app.gateway.context_usage import build_context_usage_payload
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


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


# ---------------------------------------------------------------------------
# Endpoint smoke tests — verify the response shape and that `build_context_usage`
# is exercised. The detailed breakdown logic lives in
# ``app.gateway.context_usage`` and is tested in isolation below.
# ---------------------------------------------------------------------------


def test_thread_token_usage_returns_stable_shape(monkeypatch):
    """Baseline shape — ``context_usage`` block is included (possibly null)."""

    async def _stub(_request, _thread_id, _run_store):
        return None

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_usage"] is None
    assert payload["total_tokens"] == 150
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1")


def test_thread_token_usage_can_include_active_runs(monkeypatch):
    async def _stub(_request, _thread_id, _run_store):
        return None

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

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
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


def test_thread_token_usage_serialises_breakdown(monkeypatch):
    """End-to-end: a populated breakdown round-trips through Pydantic."""

    async def _stub(_request, _thread_id, _run_store):
        return {
            "max_context_tokens": 1000,
            "used_tokens": 300,
            "percentage": 30.0,
            "breakdown": [
                {"key": "messages", "tokens": 200, "active": True},
                {"key": "system_prompt", "tokens": 100, "active": True},
                {"key": "free_space", "tokens": 700, "active": False},
            ],
        }

    monkeypatch.setattr(thread_runs, "build_context_usage", _stub)

    run_store = _make_run_store(model_name=None)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    payload = response.json()["context_usage"]
    assert payload["max_context_tokens"] == 1000
    assert payload["used_tokens"] == 300
    assert payload["percentage"] == 30.0
    assert [row["key"] for row in payload["breakdown"]] == [
        "messages",
        "system_prompt",
        "free_space",
    ]


# ---------------------------------------------------------------------------
# Unit tests for the payload builder — pure-data, no FastAPI plumbing.
# ---------------------------------------------------------------------------


def _kwargs(**overrides) -> dict:
    defaults = dict(
        max_context_tokens=None,
        messages_tokens=0,
        system_prompt_tokens=0,
        skills_tokens=0,
        custom_agents_tokens=0,
        memory_tokens=0,
        system_tools_active=0,
        mcp_tools_active=0,
        system_tools_deferred=0,
        mcp_tools_deferred=0,
        summarization_trigger=None,
    )
    defaults.update(overrides)
    return defaults


def test_payload_omits_zero_categories():
    payload = build_context_usage_payload(**_kwargs(messages_tokens=120))
    keys = [row["key"] for row in payload["breakdown"]]
    assert keys == ["messages"]
    assert payload["used_tokens"] == 120
    assert payload["max_context_tokens"] is None
    assert payload["percentage"] is None


def test_payload_percentage_and_free_space_with_window():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=1000,
            messages_tokens=200,
            system_prompt_tokens=80,
            skills_tokens=20,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert payload["used_tokens"] == 300
    assert payload["percentage"] == 30.0
    assert rows["free_space"]["tokens"] == 700
    assert rows["free_space"]["active"] is False
    # Active rows feed the percentage; free_space does not.
    assert rows["messages"]["active"] is True
    assert rows["system_prompt"]["active"] is True


def test_payload_orders_rows_canonically():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=1000,
            system_tools_active=500,
            system_prompt_tokens=400,
            skills_tokens=300,
            mcp_tools_active=200,
            custom_agents_tokens=100,
            memory_tokens=50,
            mcp_tools_deferred=80,
            system_tools_deferred=40,
            summarization_trigger=8000,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert keys == [
        "messages",
        "system_tools",
        "system_prompt",
        "skills",
        "mcp_tools",
        "custom_agents",
        "memory_files",
        "mcp_tools_deferred",
        "system_tools_deferred",
        "autocompact_buffer",
        "free_space",
    ]


def test_payload_autocompact_buffer_uses_window_minus_trigger():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=20000,
            messages_tokens=100,
            summarization_trigger=15000,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert rows["autocompact_buffer"]["tokens"] == 5000
    assert rows["autocompact_buffer"]["active"] is False


def test_payload_drops_autocompact_when_trigger_missing():
    payload = build_context_usage_payload(**_kwargs(max_context_tokens=20000, messages_tokens=100))
    keys = [row["key"] for row in payload["breakdown"]]
    assert "autocompact_buffer" not in keys


def test_payload_drops_autocompact_when_trigger_exceeds_window():
    """Misconfigured trigger > window must not produce a negative buffer."""
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=100,
            summarization_trigger=15000,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert "autocompact_buffer" not in keys


def test_payload_drops_free_space_when_window_missing():
    payload = build_context_usage_payload(**_kwargs(messages_tokens=500, skills_tokens=100))
    keys = [row["key"] for row in payload["breakdown"]]
    assert "free_space" not in keys


def test_payload_clamps_free_space_to_zero_when_over_budget():
    """If active items already exceed the window, free_space is 0 (not negative)."""
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=100,
            messages_tokens=200,
        )
    )
    keys = [row["key"] for row in payload["breakdown"]]
    assert "free_space" not in keys  # zero rows are filtered out
    # Percentage can exceed 100 — that is the honest signal of over-budget.
    assert payload["percentage"] == 200.0


def test_payload_marks_deferred_rows_inactive():
    payload = build_context_usage_payload(
        **_kwargs(
            max_context_tokens=10000,
            messages_tokens=100,
            mcp_tools_deferred=500,
            system_tools_deferred=300,
        )
    )
    rows = {row["key"]: row for row in payload["breakdown"]}
    assert rows["mcp_tools_deferred"]["active"] is False
    assert rows["system_tools_deferred"]["active"] is False
    # Deferred items must not feed the percentage.
    assert payload["used_tokens"] == 100
    assert payload["percentage"] == 1.0


# ---------------------------------------------------------------------------
# Tests for the internal helpers (model resolution + summarization trigger).
# ---------------------------------------------------------------------------


def test_summarization_trigger_picks_tokens_type():
    config = SimpleNamespace(
        summarization=SimpleNamespace(
            enabled=True,
            trigger=[
                {"type": "messages", "value": 10},
                {"type": "tokens", "value": 12345},
            ],
        ),
    )
    assert context_usage._summarization_trigger_tokens(config) == 12345


def test_summarization_trigger_returns_none_when_disabled():
    config = SimpleNamespace(
        summarization=SimpleNamespace(
            enabled=False,
            trigger=[{"type": "tokens", "value": 12345}],
        ),
    )
    assert context_usage._summarization_trigger_tokens(config) is None
