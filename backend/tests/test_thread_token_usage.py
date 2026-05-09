"""Tests for thread-level token usage aggregation API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


def test_thread_token_usage_returns_stable_shape():
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
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
        },
    )
    app = _make_app(run_store)

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
    }
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1")
