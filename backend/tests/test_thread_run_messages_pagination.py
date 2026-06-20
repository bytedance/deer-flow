"""Tests for paginated GET /api/threads/{thread_id}/runs/{run_id}/messages endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from _run_message_pagination_helpers import assert_run_message_page
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(event_store=None, run_manager=None):
    """Build a test FastAPI app with stub auth and mocked state."""
    app = make_authed_test_app()
    app.include_router(thread_runs.router)

    if event_store is not None:
        app.state.run_event_store = event_store
    if run_manager is None:
        run_manager = AsyncMock()
        run_manager.get.return_value = None
    app.state.run_manager = run_manager

    return app


def _make_event_store(rows: list[dict]):
    """Return an AsyncMock event store whose list_messages_by_run() returns rows."""
    store = MagicMock()
    store.list_messages_by_run = AsyncMock(return_value=rows)
    return store


def _make_message(seq: int) -> dict:
    return {"seq": seq, "event_type": "ai_message", "category": "message", "content": f"msg-{seq}"}


def _make_store_only_run_manager() -> RunManager:
    store = MemoryRunStore()
    asyncio.run(
        store.put(
            "store-only-run",
            thread_id="thread-store",
            assistant_id="lead_agent",
            status="running",
            multitask_strategy="reject",
            metadata={},
            kwargs={},
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    return RunManager(store=store)


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
    assert [m["seq"] for m in body["data"]] == list(range(2, 52))


def test_default_page_keeps_newest_messages_when_extra_row_returned():
    """Default latest-page trimming drops the older sentinel row, not the newest message."""
    rows = [_make_message(i) for i in range(16, 67)]
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        assert_run_message_page(
            client,
            "/api/threads/thread-2/runs/run-2/messages",
            expected_seq=list(range(17, 67)),
        )


def test_before_seq_page_keeps_newest_side_when_extra_row_returned():
    """Backward pagination trims the older sentinel so adjacent pages do not miss the boundary message."""
    rows = [_make_message(i) for i in range(1, 18)]
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        assert_run_message_page(
            client,
            "/api/threads/thread-2/runs/run-2/messages?before_seq=18&limit=16",
            expected_seq=list(range(2, 18)),
        )


def test_after_seq_page_keeps_oldest_side_when_extra_row_returned():
    """Forward pagination still trims the newer sentinel row."""
    rows = [_make_message(i) for i in range(11, 62)]
    app = _make_app(event_store=_make_event_store(rows))
    with TestClient(app) as client:
        assert_run_message_page(
            client,
            "/api/threads/thread-2/runs/run-2/messages?after_seq=10",
            expected_seq=list(range(11, 61)),
        )


def test_after_seq_forwarded_to_event_store():
    """after_seq query param is forwarded to event_store.list_messages_by_run."""
    rows = [_make_message(10)]
    event_store = _make_event_store(rows)
    app = _make_app(event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-3/runs/run-3/messages?after_seq=5")
    assert response.status_code == 200
    event_store.list_messages_by_run.assert_awaited_once_with(
        "thread-3",
        "run-3",
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
        "thread-4",
        "run-4",
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
        "thread-5",
        "run-5",
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


def test_get_run_hydrates_store_only_run():
    """GET /api/threads/{tid}/runs/{rid} should read historical store rows."""
    app = _make_app(run_manager=_make_store_only_run_manager())
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-store/runs/store-only-run")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "store-only-run"
    assert body["thread_id"] == "thread-store"
    assert body["status"] == "running"


def test_cancel_store_only_run_returns_409():
    """Store-only runs are readable but not cancellable by this worker."""
    app = _make_app(run_manager=_make_store_only_run_manager())
    with TestClient(app) as client:
        response = client.post("/api/threads/thread-store/runs/store-only-run/cancel")

    assert response.status_code == 409
    assert "not active on this worker" in response.json()["detail"]


def test_join_store_only_run_returns_409():
    """join endpoint should return 409 for store-only runs (no local stream state)."""
    app = _make_app(run_manager=_make_store_only_run_manager())
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-store/runs/store-only-run/join")

    assert response.status_code == 409
    assert "not active on this worker" in response.json()["detail"]


def test_stream_store_only_run_returns_409():
    """stream endpoint (action=None) should return 409 for store-only runs."""
    app = _make_app(run_manager=_make_store_only_run_manager())
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-store/runs/store-only-run/stream")

    assert response.status_code == 409
    assert "not active on this worker" in response.json()["detail"]


def test_list_run_messages_injects_turn_duration():
    """Verify that list_run_messages injects turn_duration into ALL AI messages for the run."""
    from unittest.mock import AsyncMock

    from deerflow.runtime import RunRecord

    # Mock a run record that took exactly 5 seconds
    mock_run = RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id=None,
        status="success",
        on_disconnect="cancel",
        created_at="2026-06-20T10:00:00Z",
        updated_at="2026-06-20T10:00:05Z",
    )

    rows = [
        {"seq": 1, "run_id": "run-1", "content": {"type": "human", "text": "Hello"}},
        {"seq": 2, "run_id": "run-1", "content": {"type": "ai", "text": "Thinking..."}},
        {"seq": 3, "run_id": "run-1", "content": {"type": "ai", "text": "Response"}},
    ]

    event_store = _make_event_store(rows)
    run_manager = AsyncMock()
    run_manager.get.return_value = mock_run
    app = _make_app(event_store=event_store, run_manager=run_manager)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/runs/run-1/messages")

    assert response.status_code == 200
    data = response.json()["data"]

    assert "turn_duration" not in data[0]["content"].get("additional_kwargs", {})

    assert data[1]["content"]["additional_kwargs"]["turn_duration"] == 5
    assert data[2]["content"]["additional_kwargs"]["turn_duration"] == 5


def test_list_thread_messages_injects_turn_duration():
    """Verify that list_thread_messages injects turn_duration into the inner content."""
    from unittest.mock import AsyncMock

    from deerflow.runtime import RunRecord

    mock_run = RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id=None,
        status="success",
        on_disconnect="cancel",
        created_at="2026-06-20T10:00:00Z",
        updated_at="2026-06-20T10:00:05Z",
    )
    rows = [
        {"seq": 1, "run_id": "run-1", "content": {"type": "human", "text": "Hello"}},
        {"seq": 2, "run_id": "run-1", "content": {"type": "ai", "text": "Response"}},
    ]

    event_store = MagicMock()
    event_store.list_messages = AsyncMock(return_value=rows)

    run_manager = AsyncMock()
    run_manager.list_by_thread = AsyncMock(return_value=[mock_run])

    feedback_repo = MagicMock()
    feedback_repo.list_by_thread_grouped = AsyncMock(return_value={})

    app = _make_app(event_store=event_store, run_manager=run_manager)
    app.state.feedback_repo = feedback_repo

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/messages")

    assert response.status_code == 200
    data = response.json()

    assert "turn_duration" not in data[0].get("content", {}).get("additional_kwargs", {})
    assert data[1]["content"]["additional_kwargs"]["turn_duration"] == 5
