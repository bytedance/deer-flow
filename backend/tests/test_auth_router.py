"""Tests for the auth router endpoints (login, refresh, API key CRUD)."""

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.middleware import create_auth_middleware
from app.gateway.routers.auth_router import router
from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config


@pytest.fixture(autouse=True)
def _reset_configs():
    reset_auth_config()
    yield
    reset_auth_config()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(create_auth_middleware())
    app.include_router(router)
    return app


class TestLogin:
    def test_login_disabled_returns_400(self):
        load_auth_config_from_dict({"enabled": False})
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
        assert resp.status_code == 400

    def test_login_no_password_hash_configured(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s", "admin_password_hash": ""})
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
        assert resp.status_code == 401

    def test_login_wrong_username(self):
        pwd_hash = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "s",
            "admin_username": "admin",
            "admin_password_hash": pwd_hash,
        })
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "wrong", "password": "correct-password"})
        assert resp.status_code == 401

    def test_login_wrong_password(self):
        pwd_hash = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "s",
            "admin_username": "admin",
            "admin_password_hash": pwd_hash,
        })
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
        assert resp.status_code == 401

    def test_login_success_returns_token(self):
        pwd_hash = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "test-secret",
            "admin_username": "admin",
            "admin_password_hash": pwd_hash,
        })
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0


class TestRefresh:
    def test_refresh_with_access_token_fails(self):
        from app.gateway.auth.jwt_handler import create_access_token

        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        access = create_access_token(tenant_id="default", username="admin")
        client = TestClient(_make_app())
        resp = client.post("/api/auth/refresh", json={"access_token": access})
        assert resp.status_code == 401

    def test_refresh_with_refresh_token_succeeds(self):
        from app.gateway.auth.jwt_handler import create_refresh_token

        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        refresh = create_refresh_token(tenant_id="default", username="admin")
        client = TestClient(_make_app())
        resp = client.post("/api/auth/refresh", json={"access_token": refresh})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data


class TestApiKeyManagement:
    def _admin_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        pwd_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        load_auth_config_from_dict({
            "enabled": True,
            "jwt_secret": "test-secret",
            "admin_username": "admin",
            "admin_password_hash": pwd_hash,
        })
        client = TestClient(_make_app())
        login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        token = login_resp.json()["access_token"]
        return client, token

    def test_create_api_key(self, tmp_path, monkeypatch):
        client, token = self._admin_client(tmp_path, monkeypatch)
        resp = client.post(
            "/api/auth/api-keys",
            json={"name": "my-key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "my-key"
        assert "raw_key" in data
        assert data["raw_key"].startswith("df-")

    def test_list_api_keys(self, tmp_path, monkeypatch):
        client, token = self._admin_client(tmp_path, monkeypatch)
        # Create a key first
        client.post("/api/auth/api-keys", json={"name": "k1"}, headers={"Authorization": f"Bearer {token}"})
        resp = client.get("/api/auth/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["name"] == "k1"

    def test_revoke_api_key(self, tmp_path, monkeypatch):
        client, token = self._admin_client(tmp_path, monkeypatch)
        create_resp = client.post("/api/auth/api-keys", json={"name": "revoke-me"}, headers={"Authorization": f"Bearer {token}"})
        key_id = create_resp.json()["id"]
        resp = client.delete(f"/api/auth/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        # Key should no longer appear in list
        list_resp = client.get("/api/auth/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert len(list_resp.json()) == 0

    def test_revoke_nonexistent_key(self, tmp_path, monkeypatch):
        client, token = self._admin_client(tmp_path, monkeypatch)
        resp = client.delete("/api/auth/api-keys/nonexistent", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_create_api_key_requires_admin(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        # Create a non-admin token
        from app.gateway.auth.jwt_handler import create_access_token
        member_token = create_access_token(tenant_id="default", username="user", role="member")
        client = TestClient(_make_app())
        resp = client.post(
            "/api/auth/api-keys",
            json={"name": "nope"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert resp.status_code == 403
