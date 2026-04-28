from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import memory


def _sample_memory(facts: list[dict] | None = None) -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "2026-03-26T12:00:00Z",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": facts or [],
    }


def test_export_memory_route_returns_current_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    exported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_export",
                "content": "User prefers concise responses.",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
            }
        ]
    )

    with patch("app.gateway.routers.memory.get_memory_data", return_value=exported_memory):
        with TestClient(app) as client:
            response = client.get("/api/memory/export")

    assert response.status_code == 200
    assert response.json()["facts"] == exported_memory["facts"]


def test_import_memory_route_returns_imported_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    imported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_import",
                "content": "User works on DeerFlow.",
                "category": "context",
                "confidence": 0.87,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )

    with patch("app.gateway.routers.memory.import_memory_data", return_value=imported_memory):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=imported_memory)

    assert response.status_code == 200
    assert response.json()["facts"] == imported_memory["facts"]


def test_export_memory_route_preserves_source_error() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    exported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_correction",
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    )

    with patch("app.gateway.routers.memory.get_memory_data", return_value=exported_memory):
        with TestClient(app) as client:
            response = client.get("/api/memory/export")

    assert response.status_code == 200
    assert response.json()["facts"][0]["sourceError"] == "The agent previously suggested npm start."


def test_import_memory_route_preserves_source_error() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    imported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_correction",
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    )

    with patch("app.gateway.routers.memory.import_memory_data", return_value=imported_memory):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=imported_memory)

    assert response.status_code == 200
    assert response.json()["facts"][0]["sourceError"] == "The agent previously suggested npm start."


def test_clear_memory_route_returns_cleared_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch("app.gateway.routers.memory.clear_memory_data", return_value=_sample_memory()):
        with TestClient(app) as client:
            response = client.delete("/api/memory")

    assert response.status_code == 200
    assert response.json()["facts"] == []


def test_create_memory_fact_route_returns_updated_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    updated_memory = _sample_memory(
        facts=[
            {
                "id": "fact_new",
                "content": "User prefers concise code reviews.",
                "category": "preference",
                "confidence": 0.88,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )

    with patch("app.gateway.routers.memory.create_memory_fact", return_value=updated_memory):
        with TestClient(app) as client:
            response = client.post(
                "/api/memory/facts",
                json={
                    "content": "User prefers concise code reviews.",
                    "category": "preference",
                    "confidence": 0.88,
                },
            )

    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_delete_memory_fact_route_returns_updated_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    updated_memory = _sample_memory(
        facts=[
            {
                "id": "fact_keep",
                "content": "User likes Python",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
            }
        ]
    )

    with patch("app.gateway.routers.memory.delete_memory_fact", return_value=updated_memory):
        with TestClient(app) as client:
            response = client.delete("/api/memory/facts/fact_delete")

    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_delete_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch("app.gateway.routers.memory.delete_memory_fact", side_effect=KeyError("fact_missing")):
        with TestClient(app) as client:
            response = client.delete("/api/memory/facts/fact_missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Memory fact 'fact_missing' not found."


def test_update_memory_fact_route_returns_updated_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    updated_memory = _sample_memory(
        facts=[
            {
                "id": "fact_edit",
                "content": "User prefers spaces",
                "category": "workflow",
                "confidence": 0.91,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )

    with patch("app.gateway.routers.memory.update_memory_fact", return_value=updated_memory):
        with TestClient(app) as client:
            response = client.patch(
                "/api/memory/facts/fact_edit",
                json={
                    "content": "User prefers spaces",
                    "category": "workflow",
                    "confidence": 0.91,
                },
            )

    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_update_memory_fact_route_preserves_omitted_fields() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    updated_memory = _sample_memory(
        facts=[
            {
                "id": "fact_edit",
                "content": "User prefers spaces",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )

    with patch("app.gateway.routers.memory.update_memory_fact", return_value=updated_memory) as update_fact:
        with TestClient(app) as client:
            response = client.patch(
                "/api/memory/facts/fact_edit",
                json={
                    "content": "User prefers spaces",
                },
            )

    assert response.status_code == 200
    assert update_fact.call_count == 1
    call_kwargs = update_fact.call_args.kwargs
    assert call_kwargs.get("fact_id") == "fact_edit"
    assert call_kwargs.get("content") == "User prefers spaces"
    assert call_kwargs.get("category") is None
    assert call_kwargs.get("confidence") is None
    assert "user_id" in call_kwargs
    assert response.json()["facts"] == updated_memory["facts"]


def test_update_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch("app.gateway.routers.memory.update_memory_fact", side_effect=KeyError("fact_missing")):
        with TestClient(app) as client:
            response = client.patch(
                "/api/memory/facts/fact_missing",
                json={
                    "content": "User prefers spaces",
                    "category": "workflow",
                    "confidence": 0.91,
                },
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "Memory fact 'fact_missing' not found."


def test_update_memory_fact_route_returns_specific_error_for_invalid_confidence() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch("app.gateway.routers.memory.update_memory_fact", side_effect=ValueError("confidence")):
        with TestClient(app) as client:
            response = client.patch(
                "/api/memory/facts/fact_edit",
                json={
                    "content": "User prefers spaces",
                    "confidence": 0.91,
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid confidence value; must be between 0 and 1."
