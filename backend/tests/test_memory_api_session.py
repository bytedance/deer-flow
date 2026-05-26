"""Tests for Session Memory API endpoints (GET/POST /api/memory/session/*)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import memory


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(memory.router)
    return app


def _session_config(enabled: bool = True) -> MagicMock:
    cfg = MagicMock()
    cfg.enabled = enabled
    return cfg


def _mock_storage_load(data: dict | None = None) -> MagicMock:
    storage = MagicMock()
    storage.load = MagicMock(return_value=data or {"facts": [], "session_context": {}})
    return storage


# ---------------------------------------------------------------------------
# GET /api/memory/session
# ---------------------------------------------------------------------------


def test_get_session_memory_returns_facts():
    """Returns session facts for a given thread."""
    storage = _mock_storage_load(
        {
            "facts": [
                {
                    "id": "sf1",
                    "content": "Thread context fact",
                    "category": "context",
                    "confidence": 0.8,
                    "createdAt": "2026-05-01T00:00:00Z",
                    "sourceError": None,
                }
            ],
            "session_context": {"key": "value"},
        }
    )

    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/session", params={"thread_id": "thread-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    assert len(body["facts"]) == 1
    assert body["facts"][0]["id"] == "sf1"
    assert body["facts"][0]["content"] == "Thread context fact"
    assert body["session_context"] == {"key": "value"}


def test_get_session_memory_disabled():
    """Returns 404 when session memory is disabled."""
    with patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(False)):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/session", params={"thread_id": "thread-1"})

    assert response.status_code == 404


def test_get_session_memory_storage_unavailable():
    """Returns 500 when session storage is None."""
    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=None),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/session", params={"thread_id": "thread-1"})

    assert response.status_code == 500


def test_get_session_memory_empty():
    """Returns empty facts when no session data exists."""
    storage = _mock_storage_load({"facts": [], "session_context": {}})

    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/session", params={"thread_id": "thread-empty"})

    assert response.status_code == 200
    assert response.json()["facts"] == []


# ---------------------------------------------------------------------------
# GET /api/memory/session/export
# ---------------------------------------------------------------------------


def test_export_session_memory():
    """Export returns same data as GET."""
    storage = _mock_storage_load(
        {"facts": [{"id": "ef1", "content": "Exported", "category": "context", "confidence": 0.9, "createdAt": "", "sourceError": None}], "session_context": {}}
    )

    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/session/export", params={"thread_id": "thread-1"})

    assert response.status_code == 200
    assert response.json()["facts"][0]["content"] == "Exported"


# ---------------------------------------------------------------------------
# POST /api/memory/session/import
# ---------------------------------------------------------------------------


def test_import_session_memory():
    """Import saves facts and returns them."""
    storage = MagicMock()
    storage.save = MagicMock(return_value=True)
    storage.load = MagicMock(
        return_value={
            "facts": [{"id": "if1", "content": "Imported fact", "category": "context", "confidence": 0.7, "createdAt": "", "sourceError": None}],
            "session_context": {},
        }
    )

    import_payload = {
        "thread_id": "thread-1",
        "facts": [
            {"id": "if1", "content": "Imported fact", "category": "context", "confidence": 0.7, "created_at": "", "source_error": None}
        ],
    }

    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/session/import", json=import_payload)

    assert response.status_code == 200
    storage.save.assert_called_once()


def test_import_session_memory_disabled():
    """Returns 400 when session memory is disabled."""
    import_payload = {"thread_id": "thread-1", "facts": []}

    with patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(False)):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/session/import", json=import_payload)

    assert response.status_code == 400


def test_import_session_memory_storage_unavailable():
    """Returns 500 when storage is None."""
    import_payload = {"thread_id": "thread-1", "facts": []}

    with (
        patch("app.gateway.routers.memory.get_session_memory_config", return_value=_session_config(True)),
        patch("app.gateway.routers.memory.get_session_storage", return_value=None),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/session/import", json=import_payload)

    assert response.status_code == 500
