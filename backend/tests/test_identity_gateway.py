"""Unit tests for the Identity Gateway router."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.gateway.routers.identity import router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI test client with Paths pointing to a temp directory."""
    import deerflow.config.paths as paths_module
    from deerflow.config.paths import Paths

    paths_obj = Paths(tmp_path)
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_obj)

    # Also patch the identity router's get_paths import
    import app.gateway.routers.identity as identity_module
    monkeypatch.setattr(identity_module, "get_paths", lambda: paths_obj)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


# ── Department endpoints ───────────────────────────────────────────────────────

class TestDeptEndpoints:
    def test_list_depts_empty(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/depts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_dept(self, client):
        tc, tmp_path = client
        resp = tc.post("/api/identity/depts", json={"dept_id": "research"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["dept_id"] == "research"
        assert data["user_count"] == 0

    def test_create_dept_then_list(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "eng"})
        resp = tc.get("/api/identity/depts")
        assert resp.status_code == 200
        names = [d["dept_id"] for d in resp.json()]
        assert "eng" in names

    def test_create_dept_duplicate_returns_409(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "research"})
        resp = tc.post("/api/identity/depts", json={"dept_id": "research"})
        assert resp.status_code == 409

    def test_create_dept_invalid_id(self, client):
        tc, _ = client
        resp = tc.post("/api/identity/depts", json={"dept_id": "bad/id"})
        assert resp.status_code == 422


# ── User endpoints ─────────────────────────────────────────────────────────────

class TestUserEndpoints:
    def test_list_users_empty(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "d1"})
        resp = tc.get("/api/identity/depts/d1/users")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_users_dept_not_found(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/depts/nonexistent/users")
        assert resp.status_code == 404

    def test_create_user(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "d1"})
        resp = tc.post("/api/identity/depts/d1/users/alice")
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == "alice"
        assert data["dept_id"] == "d1"

    def test_create_user_dept_not_found(self, client):
        tc, _ = client
        resp = tc.post("/api/identity/depts/nonexistent/users/alice")
        assert resp.status_code == 404

    def test_create_user_duplicate_returns_409(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "d1"})
        tc.post("/api/identity/depts/d1/users/alice")
        resp = tc.post("/api/identity/depts/d1/users/alice")
        assert resp.status_code == 409


# ── Agent endpoints ────────────────────────────────────────────────────────────

class TestAgentEndpoints:
    def _setup(self, tc):
        tc.post("/api/identity/depts", json={"dept_id": "d1"})
        tc.post("/api/identity/depts/d1/users/alice")

    def test_create_agent(self, client):
        tc, _ = client
        self._setup(tc)
        resp = tc.post("/api/identity/depts/d1/users/alice/agents", json={"agent_name": "sci-agent"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_name"] == "sci-agent"
        assert data["has_workspace"] is True

    def test_list_agents(self, client):
        tc, _ = client
        self._setup(tc)
        tc.post("/api/identity/depts/d1/users/alice/agents", json={"agent_name": "agent1"})
        tc.post("/api/identity/depts/d1/users/alice/agents", json={"agent_name": "agent2"})
        resp = tc.get("/api/identity/depts/d1/users/alice/agents")
        assert resp.status_code == 200
        names = [a["agent_name"] for a in resp.json()]
        assert "agent1" in names
        assert "agent2" in names

    def test_create_agent_duplicate_returns_409(self, client):
        tc, _ = client
        self._setup(tc)
        tc.post("/api/identity/depts/d1/users/alice/agents", json={"agent_name": "a1"})
        resp = tc.post("/api/identity/depts/d1/users/alice/agents", json={"agent_name": "a1"})
        assert resp.status_code == 409


# ── Persona endpoints ──────────────────────────────────────────────────────────

class TestPersonaEndpoints:
    def test_get_persona_empty(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/persona")
        assert resp.status_code == 200
        assert resp.json()["files"] == []

    def test_write_and_read_global_persona(self, client):
        tc, _ = client
        resp = tc.put("/api/identity/persona/SOUL.md", json={"content": "Be helpful."})
        assert resp.status_code == 200

        resp = tc.get("/api/identity/persona")
        files = resp.json()["files"]
        soul_files = [f for f in files if f["name"] == "SOUL.md"]
        assert len(soul_files) == 1
        assert "Be helpful." in soul_files[0]["content"]

    def test_write_dept_persona(self, client):
        tc, _ = client
        tc.post("/api/identity/depts", json={"dept_id": "eng"})
        resp = tc.put(
            "/api/identity/persona/IDENTITY.md",
            json={"content": "Engineering AI.", "dept_id": "eng"},
        )
        assert resp.status_code == 200

        # Reading with dept identity should include it
        resp = tc.get("/api/identity/persona?dept_id=eng")
        files = resp.json()["files"]
        ident_files = [f for f in files if f["name"] == "IDENTITY.md"]
        assert any("Engineering AI." in f["content"] for f in ident_files)

    def test_invalid_persona_file_rejected(self, client):
        tc, _ = client
        resp = tc.put("/api/identity/persona/UNKNOWN.md", json={"content": "x"})
        assert resp.status_code == 422


# ── Skills endpoint ────────────────────────────────────────────────────────────

class TestSkillsEndpoint:
    def test_get_skills_empty(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/skills")
        assert resp.status_code == 200
        assert isinstance(resp.json()["skills"], list)

    def test_get_skills_with_invalid_dept_id(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/skills?dept_id=bad/id")
        assert resp.status_code == 422


# ── Effective config endpoint ─────────────────────────────────────────────────

class TestEffectiveConfigEndpoint:
    def test_returns_empty_dict_when_no_config_files(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/effective-config?dept_id=d1&user_id=u1")
        assert resp.status_code == 200
        data = resp.json()
        assert "identity" in data
        assert "config" in data
        # No config files → empty merged dict
        assert data["config"] == {}

    def test_invalid_dept_id_rejected(self, client):
        tc, _ = client
        resp = tc.get("/api/identity/effective-config?dept_id=bad/id")
        assert resp.status_code == 422
