from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import memory
from deerflow.config.memory_config import MemoryConfig


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


def _management_enabled_config() -> MemoryConfig:
    return MemoryConfig(enabled=True, management_api_enabled=True)


def test_memory_management_routes_disabled_by_default() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    requests = [
        ("GET", "/api/memory", None),
        ("GET", "/api/memory/export", None),
        ("GET", "/api/memory/status", None),
        ("POST", "/api/memory/import", _sample_memory()),
        ("POST", "/api/memory/facts", {"content": "blocked", "category": "context", "confidence": 0.8}),
        ("DELETE", "/api/memory", None),
    ]

    with TestClient(app) as client:
        for method, path, payload in requests:
            response = client.request(method, path, json=payload)
            assert response.status_code == 403
            assert response.json()["detail"] == memory.MEMORY_MANAGEMENT_DISABLED_DETAIL


def test_memory_config_route_returns_safe_gate_state() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with TestClient(app) as client:
        response = client.get("/api/memory/config")

    assert response.status_code == 200
    assert response.json()["management_api_enabled"] is False
    assert "storage_path" not in response.json()


def test_memory_management_routes_require_memory_feature_to_be_enabled() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch(
        "app.gateway.routers.memory.get_memory_config",
        return_value=MemoryConfig(enabled=False, management_api_enabled=True),
    ):
        with TestClient(app) as client:
            response = client.get("/api/memory")

    assert response.status_code == 403
    assert response.json()["detail"] == memory.MEMORY_MANAGEMENT_DISABLED_DETAIL


def test_get_memory_route_returns_current_memory_when_enabled() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    current_memory = _sample_memory(
        facts=[
            {
                "id": "fact_current",
                "content": "User prefers concise responses.",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
            }
        ]
    )

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.get_memory_data", return_value=current_memory),
    ):
        with TestClient(app) as client:
            response = client.get("/api/memory")

    assert response.status_code == 200
    assert response.json()["facts"] == current_memory["facts"]


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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.get_memory_data", return_value=exported_memory),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.import_memory_data", return_value=imported_memory),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.get_memory_data", return_value=exported_memory),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.import_memory_data", return_value=imported_memory),
    ):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=imported_memory)

    assert response.status_code == 200
    assert response.json()["facts"][0]["sourceError"] == "The agent previously suggested npm start."


def test_clear_memory_route_returns_cleared_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.clear_memory_data", return_value=_sample_memory()),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.create_memory_fact", return_value=updated_memory),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.delete_memory_fact", return_value=updated_memory),
    ):
        with TestClient(app) as client:
            response = client.delete("/api/memory/facts/fact_delete")

    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_delete_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.delete_memory_fact", side_effect=KeyError("fact_missing")),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.update_memory_fact", return_value=updated_memory),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.update_memory_fact", return_value=updated_memory) as update_fact,
    ):
        with TestClient(app) as client:
            response = client.patch(
                "/api/memory/facts/fact_edit",
                json={
                    "content": "User prefers spaces",
                },
            )

    assert response.status_code == 200
    update_fact.assert_called_once_with(
        fact_id="fact_edit",
        content="User prefers spaces",
        category=None,
        confidence=None,
    )
    assert response.json()["facts"] == updated_memory["facts"]


def test_update_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.update_memory_fact", side_effect=KeyError("fact_missing")),
    ):
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

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.update_memory_fact", side_effect=ValueError("confidence")),
    ):
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


def test_memory_status_route_returns_config_and_data_when_enabled() -> None:
    app = FastAPI()
    app.include_router(memory.router)
    memory_data = _sample_memory()

    with (
        patch("app.gateway.routers.memory.get_memory_config", return_value=_management_enabled_config()),
        patch("app.gateway.routers.memory.get_memory_data", return_value=memory_data),
    ):
        with TestClient(app) as client:
            response = client.get("/api/memory/status")

    assert response.status_code == 200
    assert response.json()["config"]["management_api_enabled"] is True
    assert response.json()["data"] == memory_data
