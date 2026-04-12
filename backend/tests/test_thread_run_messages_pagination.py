"""Tests for paginated GET /api/threads/{thread_id}/runs/{run_id}/messages endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(event_store=None):
    """Build a test FastAPI app with stub auth and mocked state."""
    app = make_authed_test_app()
    app.include_router(thread_runs.router)

    if event_store is not None:
        app.state.run_event_store = event_store

    return app


def _make_event_store(rows: list[dict]):
    """Return an AsyncMock event store whose list_messages_by_run() returns rows."""
    store = MagicMock()
    store.list_messages_by_run = AsyncMock(return_value=rows)
    return store


def _make_message(seq: int) -> dict:
    return {"seq": seq, "event_type": "ai_message", "category": "message", "content": f"msg-{seq}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_paginated_envelope():
    """GET /api/threads/{tid}/runs/{rid}/messages returns {data: [...], has_more: bool}."""
    rows = [_make_message(i) for i in range(1, 4)]
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs/run-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "has_more" in body
    assert body["has_more"] is False
    assert len(body["data"]) == 3


def test_has_more_true_when_extra_row_returned():
    """has_more=True when event store returns limit+1 rows."""
    # Default limit is 50; provide 51 rows
    rows = [_make_message(i) for i in range(1, 52)]  # 51 rows
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-2/runs/run-2/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert len(body["data"]) == 50  # trimmed to limit


def test_after_seq_forwarded_to_event_store():
    """after_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(10)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-3/runs/run-3/messages?after_seq=5")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-3", "run-3",
        limit=51,  # default limit(50) + 1
        before_seq=None,
        after_seq=5,
    )


def test_before_seq_forwarded_to_event_store():
    """before_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(3)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-4/runs/run-4/messages?before_seq=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-4", "run-4",
        limit=51,
        before_seq=10,
        after_seq=None,
    )


def test_custom_limit_forwarded_to_event_store():
    """Custom limit is forwarded as limit+1 to the event store."""
    rows = [_make_message(i) for i in range(1, 6)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-5/runs/run-5/messages?limit=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-5", "run-5",
        limit=11,  # 10 + 1
        before_seq=None,
        after_seq=None,
    )


def test_empty_data_when_no_messages():
    """Returns empty data list with has_more=False when no messages exist."""
    app = _make_app(event_store=_make_event_store([]))
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-6/runs/run-6/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["has_more"] is False
