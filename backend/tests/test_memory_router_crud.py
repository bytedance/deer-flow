from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.routers import memory as memory_router
from src.config.memory_config import MemoryConfig


def _empty_memory() -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "",
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
        "facts": [],
    }


def _scope_key(namespace_type: str | None, namespace_id: str | None) -> tuple[str, str]:
    return (namespace_type or "global", namespace_id or "global")


def test_memory_facts_crud(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    state: dict[tuple[str, str], dict] = {}

    def fake_get_memory_data(agent_name=None, namespace_type=None, namespace_id=None):
        key = _scope_key(namespace_type, namespace_id)
        return deepcopy(state.get(key, _empty_memory()))

    def fake_reload_memory_data(agent_name=None, namespace_type=None, namespace_id=None):
        return fake_get_memory_data(agent_name=agent_name, namespace_type=namespace_type, namespace_id=namespace_id)

    def fake_save_memory_data(memory_data, agent_name=None, namespace_type=None, namespace_id=None):
        key = _scope_key(namespace_type, namespace_id)
        state[key] = deepcopy(memory_data)
        return True

    monkeypatch.setattr(memory_router, "get_memory_data", fake_get_memory_data)
    monkeypatch.setattr(memory_router, "reload_memory_data", fake_reload_memory_data)
    monkeypatch.setattr(memory_router, "save_memory_data", fake_save_memory_data)

    scope_qs = "?namespace_type=chat&namespace_id=tenant-a"

    r = client.post(f"/api/memory/facts{scope_qs}", json={"content": "User likes black coffee.", "confidence": 0.91})
    assert r.status_code == 200
    body = r.json()
    assert len(body["facts"]) == 1
    fact_id = body["facts"][0]["id"]
    assert body["facts"][0]["content"] == "User likes black coffee."

    r = client.put(
        f"/api/memory/facts/{fact_id}{scope_qs}",
        json={"content": "User likes espresso.", "category": "preference", "confidence": 0.95},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["facts"][0]["content"] == "User likes espresso."
    assert body["facts"][0]["category"] == "preference"
    assert body["facts"][0]["confidence"] == 0.95

    r = client.delete(f"/api/memory/facts/{fact_id}{scope_qs}")
    assert r.status_code == 200
    assert r.json()["facts"] == []


def test_memory_fact_update_not_found(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    monkeypatch.setattr(memory_router, "get_memory_data", lambda **kwargs: _empty_memory())
    monkeypatch.setattr(memory_router, "save_memory_data", lambda *args, **kwargs: True)

    r = client.put("/api/memory/facts/fact_missing", json={"content": "new"})
    assert r.status_code == 404


def test_memory_scope_validation_returns_400(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    def _raise_scope_error(**kwargs):
        raise ValueError("namespace_type and namespace_id are required when memory.strict_scope=true")

    monkeypatch.setattr(memory_router, "get_memory_data", _raise_scope_error)

    r = client.get("/api/memory")
    assert r.status_code == 400
    assert "namespace_type and namespace_id are required" in r.json()["detail"]


def test_memory_config_reports_backend_and_scope_mode(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    monkeypatch.setattr(
        memory_router,
        "get_memory_config",
        lambda: MemoryConfig(
            backend="postgres",
            database_url="postgres://memory-db",
            strict_scope=True,
            auth_mode="downstream_trusted_scope",
            storage_path="",
            debounce_seconds=5,
            max_facts=200,
            fact_confidence_threshold=0.7,
            injection_enabled=True,
            max_injection_tokens=1200,
        ),
    )

    r = client.get("/api/memory/config")

    assert r.status_code == 200
    assert r.json() == {
        "enabled": True,
        "backend": "postgres",
        "storage_path": "",
        "database_configured": True,
        "strict_scope": True,
        "auth_mode": "downstream_trusted_scope",
        "debounce_seconds": 5,
        "max_facts": 200,
        "fact_confidence_threshold": 0.7,
        "injection_enabled": True,
        "max_injection_tokens": 1200,
    }


def test_memory_status_reports_backend_and_current_scope_data(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    monkeypatch.setattr(
        memory_router,
        "get_memory_config",
        lambda: MemoryConfig(
            backend="postgres",
            database_url="postgres://memory-db",
            strict_scope=True,
            auth_mode="downstream_trusted_scope",
            storage_path="",
        ),
    )
    monkeypatch.setattr(
        memory_router,
        "get_memory_data",
        lambda **kwargs: {
            **_empty_memory(),
            "facts": [
                {
                    "id": "fact_1234",
                    "content": "User prefers terse updates.",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2026-03-11T10:22:11Z",
                    "source": "api",
                }
            ],
        },
    )

    r = client.get("/api/memory/status?namespace_type=chat&namespace_id=tenant-a")

    assert r.status_code == 200
    body = r.json()
    assert body["config"]["backend"] == "postgres"
    assert body["config"]["database_configured"] is True
    assert body["config"]["strict_scope"] is True
    assert body["config"]["auth_mode"] == "downstream_trusted_scope"
    assert body["data"]["facts"][0]["content"] == "User prefers terse updates."

