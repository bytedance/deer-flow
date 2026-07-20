"""Query validation for thread message and run event read endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs


def _make_app():
    app = make_authed_test_app()
    app.include_router(thread_runs.router)

    event_store = MagicMock()
    event_store.list_messages = AsyncMock(return_value=[])
    event_store.list_messages_by_run = AsyncMock(return_value=[])
    event_store.list_events = AsyncMock(return_value=[])
    app.state.run_event_store = event_store

    run_manager = MagicMock()
    run_manager.list_by_thread = AsyncMock(return_value=[])
    app.state.run_manager = run_manager
    return app


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        ("/api/threads/thread-1/messages", 0),
        ("/api/threads/thread-1/messages", -1),
        ("/api/threads/thread-1/runs/run-1/events", 0),
        ("/api/threads/thread-1/runs/run-1/events", -1),
    ],
)
def test_read_endpoints_reject_non_positive_limits(path: str, limit: int):
    with TestClient(_make_app()) as client:
        response = client.get(path, params={"limit": limit})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "cursor"),
    [
        ("/api/threads/thread-1/messages", "before_seq"),
        ("/api/threads/thread-1/messages", "after_seq"),
        ("/api/threads/thread-1/runs/run-1/messages", "before_seq"),
        ("/api/threads/thread-1/runs/run-1/messages", "after_seq"),
        ("/api/threads/thread-1/runs/run-1/events", "after_seq"),
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_read_endpoints_reject_non_positive_seq_cursors(path: str, cursor: str, value: int):
    with TestClient(_make_app()) as client:
        response = client.get(path, params={cursor: value})

    assert response.status_code == 422


def test_read_endpoints_accept_positive_limits_and_hit_store():
    app = _make_app()
    with TestClient(app) as client:
        thread_messages = client.get("/api/threads/thread-1/messages", params={"limit": 1})
        run_messages = client.get("/api/threads/thread-1/runs/run-1/messages", params={"limit": 1})
        run_events = client.get("/api/threads/thread-1/runs/run-1/events", params={"limit": 1})

    assert thread_messages.status_code == 200
    assert run_messages.status_code == 200
    assert run_events.status_code == 200
    app.state.run_event_store.list_messages.assert_awaited_once_with("thread-1", limit=1, before_seq=None, after_seq=None)
    app.state.run_event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-1",
        "run-1",
        limit=2,
        before_seq=None,
        after_seq=None,
    )
    app.state.run_event_store.list_events.assert_awaited_once_with(
        "thread-1",
        "run-1",
        event_types=None,
        task_id=None,
        limit=1,
        after_seq=None,
    )
