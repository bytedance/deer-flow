"""Tests for Domain Memory API endpoints (GET/POST/PUT/DELETE /api/memory/domain/*)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import memory


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(memory.router)
    return app


def _domain_config(enabled: bool = True, min_score: float = 0.7) -> MagicMock:
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.min_retrieval_score = min_score
    return cfg


def _make_domain_fact(
    fact_id: str = "df1",
    content: str = "Pump A flow rate is 500 GPM",
    domain: str = "equipment",
    entity_id: str = "pump_a",
    tenant_id: str = "tenant-1",
    confidence: float = 0.95,
    created_at: datetime | None = None,
    similarity_score: float = 0.92,
    adjusted_score: float = 0.88,
) -> Any:
    from deerflow.agents.memory.domain_storage import DomainFact

    return DomainFact(
        id=fact_id,
        content=content,
        domain=domain,
        entity_id=entity_id,
        tenant_id=tenant_id,
        confidence=confidence,
        created_at=created_at or datetime(2026, 5, 1),
        similarity_score=similarity_score,
        adjusted_score=adjusted_score,
    )


# ---------------------------------------------------------------------------
# GET /api/memory/domain (search)
# ---------------------------------------------------------------------------


def test_search_domain_memory_returns_facts():
    """Returns domain facts matching a query."""
    storage = MagicMock()
    storage.search_facts = MagicMock(return_value=[_make_domain_fact()])

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/domain", params={"query": "pump flow rate"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "df1"
    assert body[0]["content"] == "Pump A flow rate is 500 GPM"
    assert body[0]["domain"] == "equipment"
    assert body[0]["entity_id"] == "pump_a"
    assert body[0]["similarity_score"] == 0.92
    assert body[0]["adjusted_score"] == 0.88


def test_search_domain_memory_disabled():
    """Returns empty list when domain memory is disabled."""
    with patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(False)):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/domain", params={"query": "test"})

    assert response.status_code == 200
    assert response.json() == []


def test_search_domain_memory_storage_unavailable():
    """Returns 500 when domain storage is None."""
    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=None),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/domain", params={"query": "test"})

    assert response.status_code == 500


def test_search_domain_memory_with_filters():
    """Passes domain and entity_id filters to storage."""
    storage = MagicMock()
    storage.search_facts = MagicMock(return_value=[])

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get(
                "/api/memory/domain",
                params={"query": "pump", "domain": "equipment", "entity_id": "pump_a", "top_k": 5},
            )

    assert response.status_code == 200
    storage.search_facts.assert_called_once_with(
        tenant_id="tenant-1",
        query="pump",
        domain="equipment",
        entity_id="pump_a",
        top_k=5,
        min_score=0.7,
    )


# ---------------------------------------------------------------------------
# POST /api/memory/domain/facts (create)
# ---------------------------------------------------------------------------


def test_create_domain_fact():
    """Creates a domain fact and returns it."""
    storage = MagicMock()
    storage.store_fact = MagicMock(return_value="new-fact-id")

    payload = {
        "content": "Reactor 1 temp is 350C",
        "domain": "process",
        "entity_id": "reactor_1",
        "confidence": 0.9,
    }

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/facts", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "new-fact-id"
    assert body["content"] == "Reactor 1 temp is 350C"
    assert body["domain"] == "process"
    storage.store_fact.assert_called_once()


def test_create_domain_fact_disabled():
    """Returns 400 when domain memory is disabled."""
    payload = {"content": "test", "domain": "test", "entity_id": "test"}

    with patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(False)):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/facts", json=payload)

    assert response.status_code == 400


def test_create_domain_fact_storage_unavailable():
    """Returns 500 when domain storage is None."""
    payload = {"content": "test", "domain": "test", "entity_id": "test"}

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=None),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/facts", json=payload)

    assert response.status_code == 500


def test_create_domain_fact_store_returns_none():
    """Returns 500 when store_fact returns None."""
    storage = MagicMock()
    storage.store_fact = MagicMock(return_value=None)

    payload = {"content": "test", "domain": "test", "entity_id": "test"}

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/facts", json=payload)

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# PUT /api/memory/domain/facts/{id} (update — 501)
# ---------------------------------------------------------------------------


def test_update_domain_fact_returns_501():
    """Update logs audit intent but returns 501 (not yet implemented)."""
    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.put(
                "/api/memory/domain/facts/df1",
                json={"content": "Updated content"},
            )

    assert response.status_code == 501


def test_update_domain_fact_disabled():
    """Returns 400 when domain memory is disabled."""
    with patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(False)):
        with TestClient(_make_app()) as client:
            response = client.put("/api/memory/domain/facts/df1", json={"content": "x"})

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/memory/domain/facts/{id} (delete — 501)
# ---------------------------------------------------------------------------


def test_delete_domain_fact_returns_501():
    """Delete logs audit intent but returns 501 (not yet implemented)."""
    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.delete("/api/memory/domain/facts/df1")

    assert response.status_code == 501


def test_delete_domain_fact_disabled():
    """Returns 400 when domain memory is disabled."""
    with patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(False)):
        with TestClient(_make_app()) as client:
            response = client.delete("/api/memory/domain/facts/df1")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/memory/domain/export
# ---------------------------------------------------------------------------


def test_export_domain_memory():
    """Export returns domain facts via search."""
    storage = MagicMock()
    storage.search_facts = MagicMock(return_value=[_make_domain_fact(content="Exported fact")])

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
    ):
        with TestClient(_make_app()) as client:
            response = client.get("/api/memory/domain/export")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "Exported fact"


# ---------------------------------------------------------------------------
# POST /api/memory/domain/import
# ---------------------------------------------------------------------------


def test_import_domain_memory():
    """Import stores facts and returns count."""
    storage = MagicMock()
    storage.store_fact = MagicMock(return_value="imported-id")

    payload = {
        "facts": [
            {"content": "Fact 1", "domain": "equipment", "entity_id": "pump_a", "confidence": 0.9},
            {"content": "Fact 2", "domain": "process", "entity_id": "reactor_1", "confidence": 0.8},
        ]
    }

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/import", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["total"] == 2
    assert storage.store_fact.call_count == 2


def test_import_domain_memory_disabled():
    """Returns 400 when domain memory is disabled."""
    with patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(False)):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/import", json={"facts": []})

    assert response.status_code == 400


def test_import_domain_memory_partial_failure():
    """Reports correct count when some facts fail to store."""
    storage = MagicMock()
    storage.store_fact = MagicMock(side_effect=["id-1", None, "id-3"])

    payload = {
        "facts": [
            {"content": "OK 1", "domain": "a", "entity_id": "e1", "confidence": 0.9},
            {"content": "FAIL", "domain": "a", "entity_id": "e2", "confidence": 0.9},
            {"content": "OK 3", "domain": "a", "entity_id": "e3", "confidence": 0.9},
        ]
    }

    with (
        patch("app.gateway.routers.memory.get_domain_memory_config", return_value=_domain_config(True)),
        patch("app.gateway.routers.memory.get_domain_storage", return_value=storage),
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="tenant-1"),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.log_memory_audit", new=AsyncMock()),
    ):
        with TestClient(_make_app()) as client:
            response = client.post("/api/memory/domain/import", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["total"] == 3
