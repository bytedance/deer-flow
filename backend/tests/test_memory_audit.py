"""Tests for the memory audit query endpoint (GET /api/memory/audit)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import memory


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(memory.router)
    return app


def _make_audit_row(
    row_id: int = 1,
    tenant_id: str = "tenant-1",
    user_id: str = "user-1",
    action: str = "create",
    layer: str = "user",
    fact_id: str = "fact-1",
    before: dict | None = None,
    after: dict | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = row_id
    row.tenant_id = tenant_id
    row.user_id = user_id
    row.action = action
    row.layer = layer
    row.fact_id = fact_id
    row.before = before
    row.after = after or {"content": "test"}
    row.created_at = created_at or datetime(2026, 5, 1, tzinfo=UTC)
    return row


def _mock_session_factory(rows: list[MagicMock]) -> MagicMock:
    """Create an async context manager session factory."""
    session = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=session)
    return factory


# ---------------------------------------------------------------------------
# GET /api/memory/audit
# ---------------------------------------------------------------------------


def test_get_audit_logs_returns_entries():
    """Returns audit log entries."""
    rows = [
        _make_audit_row(row_id=1, action="create", layer="domain"),
        _make_audit_row(row_id=2, action="delete", layer="session"),
    ]
    session_factory = _mock_session_factory(rows)

    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("deerflow.persistence.engine.get_session_factory", return_value=session_factory),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/audit")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["id"] == 1
    assert body[0]["action"] == "create"
    assert body[1]["action"] == "delete"


def test_get_audit_logs_with_filters():
    """Applies user_id, action, and layer filters."""
    rows = [_make_audit_row()]
    session_factory = _mock_session_factory(rows)

    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("deerflow.persistence.engine.get_session_factory", return_value=session_factory),
    ):
        with TestClient(_make_app()) as client:
            response = client.get(
                "/api/memory/audit",
                params={"user_id": "user-1", "action": "create", "layer": "domain", "limit": 50},
            )

    assert response.status_code == 200


def test_get_audit_logs_empty():
    """Returns empty list when no audit entries exist."""
    session_factory = _mock_session_factory([])

    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("deerflow.persistence.engine.get_session_factory", return_value=session_factory),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/audit")

    assert response.status_code == 200
    assert response.json() == []


def test_get_audit_logs_persistence_unavailable():
    """Returns 500 when persistence is unavailable."""
    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("deerflow.persistence.engine.get_session_factory", return_value=None),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/audit")

    assert response.status_code == 500


def test_get_audit_logs_response_shape():
    """Verifies all fields are present in the response."""
    rows = [
        _make_audit_row(
            row_id=42,
            tenant_id="t1",
            user_id="u1",
            action="update",
            layer="user",
            fact_id="f1",
            before={"old": "data"},
            after={"new": "data"},
            created_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC),
        )
    ]
    session_factory = _mock_session_factory(rows)

    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="t1"),
        patch("deerflow.persistence.engine.get_session_factory", return_value=session_factory),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/audit")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["id"] == 42
    assert entry["tenant_id"] == "t1"
    assert entry["user_id"] == "u1"
    assert entry["action"] == "update"
    assert entry["layer"] == "user"
    assert entry["fact_id"] == "f1"
    assert entry["before"] == {"old": "data"}
    assert entry["after"] == {"new": "data"}
    assert "2026-05-15" in entry["created_at"]
