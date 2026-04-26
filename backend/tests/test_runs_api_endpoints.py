"""Tests for GET /api/runs/{run_id}/messages and GET /api/runs/{run_id}/feedback endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import runs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(run_store=None, event_store=None, feedback_repo=None):
    """Build a test FastAPI app with stub auth and mocked state."""
    app = make_authed_test_app()
    app.include_router(runs.router)

    if run_store is not None:
        app.state.run_store = run_store
    if event_store is not None:
        app.state.run_event_store = event_store
    if feedback_repo is not None:
        app.state.feedback_repo = feedback_repo

    return app


def _make_run_store(run_record: dict | None):
    """Return an AsyncMock run store whose get() returns run_record."""
    store = MagicMock()
    store.get = AsyncMock(return_value=run_record)
    return store


def _make_event_store(rows: list[dict]):
    """Return an AsyncMock event store whose list_messages_by_run() returns rows."""
    store = MagicMock()
    store.list_messages_by_run = AsyncMock(return_value=rows)
    return store


def _make_message(seq: int) -> dict:
    return {"seq": seq, "event_type": "on_chat_model_stream", "category": "message", "content": f"msg-{seq}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_messages_returns_envelope():
    """GET /api/runs/{run_id}/messages returns {data: [...], has_more: bool}."""
    rows = [_make_message(i) for i in range(1, 4)]
    run_record = {"run_id": "run-1", "thread_id": "thread-1"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "has_more" in body
    assert body["has_more"] is False
    assert len(body["data"]) == 3


def test_run_messages_404_when_run_not_found():
    """Returns 404 when the run store returns None."""
    app = _make_app(
        run_store=_make_run_store(None),
        event_store=_make_event_store([]),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/missing-run/messages")
    assert response.status_code == 404
    assert "missing-run" in response.json()["detail"]


def test_run_messages_has_more_true_when_extra_row_returned():
    """has_more=True when event store returns limit+1 rows."""
    # Default limit is 50; provide 51 rows
    rows = [_make_message(i) for i in range(1, 52)]  # 51 rows
    run_record = {"run_id": "run-2", "thread_id": "thread-2"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store(rows),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-2/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert len(body["data"]) == 50  # trimmed to limit


def test_run_messages_passes_after_seq_to_event_store():
    """after_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(10)]
    run_record = {"run_id": "run-3", "thread_id": "thread-3"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-3/messages?after_seq=5")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-3",
        "run-3",
        limit=51,  # default limit(50) + 1
        before_seq=None,
        after_seq=5,
    )


def test_run_messages_respects_custom_limit():
    """Custom limit is respected and capped at 200."""
    rows = [_make_message(i) for i in range(1, 6)]
    run_record = {"run_id": "run-4", "thread_id": "thread-4"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-4/messages?limit=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-4",
        "run-4",
        limit=11,  # 10 + 1
        before_seq=None,
        after_seq=None,
    )


def test_run_messages_passes_before_seq_to_event_store():
    """before_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(3)]
    run_record = {"run_id": "run-5", "thread_id": "thread-5"}
    event_store = _make_event_store(rows)
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=event_store,
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-5/messages?before_seq=10")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-5",
        "run-5",
        limit=51,
        before_seq=10,
        after_seq=None,
    )


def test_run_messages_empty_data():
    """Returns empty data list when no messages exist."""
    run_record = {"run_id": "run-6", "thread_id": "thread-6"}
    app = _make_app(
        run_store=_make_run_store(run_record),
        event_store=_make_event_store([]),
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/run-6/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["has_more"] is False


def _make_feedback_repo(rows: list[dict]):
    """Return an AsyncMock feedback repo whose list_by_run() returns rows."""
    repo = MagicMock()
    repo.list_by_run = AsyncMock(return_value=rows)
    return repo


def _make_feedback(run_id: str, idx: int) -> dict:
    return {"id": f"fb-{idx}", "run_id": run_id, "thread_id": "thread-x", "value": "up"}


# ---------------------------------------------------------------------------
# TestRunFeedback
# ---------------------------------------------------------------------------


class TestRunFeedback:
    def test_returns_list_of_feedback_dicts(self):
        """GET /api/runs/{run_id}/feedback returns a list of feedback dicts."""
        run_record = {"run_id": "run-fb-1", "thread_id": "thread-fb-1"}
        rows = [_make_feedback("run-fb-1", i) for i in range(3)]
        app = _make_app(
            run_store=_make_run_store(run_record),
            feedback_repo=_make_feedback_repo(rows),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-1/feedback")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 3

    def test_404_when_run_not_found(self):
        """Returns 404 when run store returns None."""
        app = _make_app(
            run_store=_make_run_store(None),
            feedback_repo=_make_feedback_repo([]),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/missing-run/feedback")
        assert response.status_code == 404
        assert "missing-run" in response.json()["detail"]

    def test_empty_list_when_no_feedback(self):
        """Returns empty list when no feedback exists for the run."""
        run_record = {"run_id": "run-fb-2", "thread_id": "thread-fb-2"}
        app = _make_app(
            run_store=_make_run_store(run_record),
            feedback_repo=_make_feedback_repo([]),
        )
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-2/feedback")
        assert response.status_code == 200
        assert response.json() == []

    def test_503_when_feedback_repo_not_configured(self):
        """Returns 503 when feedback_repo is None (no DB configured)."""
        run_record = {"run_id": "run-fb-3", "thread_id": "thread-fb-3"}
        app = _make_app(
            run_store=_make_run_store(run_record),
        )
        # Explicitly set feedback_repo to None to simulate missing DB
        app.state.feedback_repo = None
        with TestClient(app) as client:
            response = client.get("/api/runs/run-fb-3/feedback")
        assert response.status_code == 503
