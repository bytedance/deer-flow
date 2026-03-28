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


def test_clear_memory_route_returns_cleared_memory() -> None:
    app = FastAPI()
    app.include_router(memory.router)

    with patch("app.gateway.routers.memory.clear_memory_data", return_value=_sample_memory()):
        with TestClient(app) as client:
            response = client.delete("/api/memory")

    assert response.status_code == 200
    assert response.json()["facts"] == []


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
