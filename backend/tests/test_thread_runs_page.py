"""Tests for GET /api/threads/{thread_id}/runs and /runs/page."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus


def _record(run_id: str, created_at: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.cancel,
        created_at=created_at,
        updated_at=created_at,
    )


def _make_app(records: list[RunRecord]) -> tuple:
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    run_manager = MagicMock()
    run_manager.list_by_thread = AsyncMock(return_value=records)
    app.state.run_manager = run_manager
    return app, run_manager


def test_list_runs_returns_bare_array():
    records = [
        _record("r3", "2026-01-03T00:00:00+00:00"),
        _record("r2", "2026-01-02T00:00:00+00:00"),
    ]
    app, run_manager = _make_app(records)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert [row["run_id"] for row in body] == ["r3", "r2"]
    run_manager.list_by_thread.assert_awaited_once()
    kwargs = run_manager.list_by_thread.await_args.kwargs
    assert kwargs.get("limit", 100) == 100
    assert "before_created_at" not in kwargs
    assert "before_run_id" not in kwargs


def test_list_runs_ignores_langgraph_sdk_limit_query():
    """SDK always sends limit=10; honoring it would shrink the existing array."""
    records = [_record(f"r{i}", f"2026-01-{i:02d}T00:00:00+00:00") for i in range(1, 4)]
    app, run_manager = _make_app(records)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs", params={"limit": 10, "offset": 0})

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) == 3
    assert "limit" not in run_manager.list_by_thread.await_args.kwargs


def test_runs_page_returns_envelope_and_has_more():
    records = [
        _record("r3", "2026-01-03T00:00:00+00:00"),
        _record("r2", "2026-01-02T00:00:00+00:00"),
        _record("r1", "2026-01-01T00:00:00+00:00"),
    ]
    app, run_manager = _make_app(records)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs/page", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert [row["run_id"] for row in body["data"]] == ["r3", "r2"]
    assert body["has_more"] is True
    assert body["next_before_created_at"] == "2026-01-02T00:00:00+00:00"
    assert body["next_before_run_id"] == "r2"
    kwargs = run_manager.list_by_thread.await_args.kwargs
    assert kwargs["limit"] == 3
    assert kwargs["before_created_at"] is None
    assert kwargs["before_run_id"] is None


def test_runs_page_passes_cursor_through():
    app, run_manager = _make_app([_record("r1", "2026-01-01T00:00:00+00:00")])
    with TestClient(app) as client:
        response = client.get(
            "/api/threads/thread-1/runs/page",
            params={
                "limit": 2,
                "before_created_at": "2026-01-02T00:00:00+00:00",
                "before_run_id": "r2",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is False
    assert body["next_before_created_at"] is None
    assert body["next_before_run_id"] is None
    kwargs = run_manager.list_by_thread.await_args.kwargs
    assert kwargs["before_created_at"] == "2026-01-02T00:00:00+00:00"
    assert kwargs["before_run_id"] == "r2"


def test_runs_page_is_not_captured_as_run_id():
    app, _run_manager = _make_app([])
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs/page")

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "has_more": False,
        "next_before_created_at": None,
        "next_before_run_id": None,
    }
