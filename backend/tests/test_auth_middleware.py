"""Tests for AuthMiddleware — whitelist, disabled mode, JWT, API Key, tenant context."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.jwt_handler import create_access_token
from app.gateway.auth.middleware import create_auth_middleware
from deerflow.config.auth_config import load_auth_config_from_dict, reset_auth_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.config.tenant_storage import TenantConfig


def _mock_tenant_get(tenant_id):
    """Return a valid active TenantConfig for any tenant_id used in tests."""
    return TenantConfig(tenant_id=tenant_id, name=tenant_id, is_active=True)


@pytest.fixture(autouse=True)
def _reset_configs():
    reset_auth_config()
    yield
    reset_auth_config()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(create_auth_middleware())

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/protected")
    def protected():
        return {"tenant": get_current_tenant_id()}

    @app.get("/api/admin/tenants")
    def admin_tenants():
        return {"tenants": []}

    return app


class TestWhitelist:
    def test_health_is_whitelisted(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        client = TestClient(_make_app())
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_docs_are_whitelisted(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        client = TestClient(_make_app())
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_is_whitelisted(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        client = TestClient(_make_app())
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_auth_login_is_whitelisted(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        client = TestClient(_make_app())
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
        # 401 is fine — it means the route was reached (auth not blocking it)
        assert resp.status_code != 401 or resp.json()["detail"] != "Missing or invalid Authorization header"


class TestDisabledMode:
    def test_no_header_defaults_tenant(self):
        load_auth_config_from_dict({"enabled": False})
        with patch("app.gateway.auth.middleware.TenantStorage.get", side_effect=_mock_tenant_get):
            client = TestClient(_make_app())
            resp = client.get("/api/protected")
        assert resp.status_code == 200
        assert resp.json()["tenant"] == "default"

    def test_header_sets_tenant(self):
        load_auth_config_from_dict({"enabled": False})
        with patch("app.gateway.auth.middleware.TenantStorage.get", side_effect=_mock_tenant_get):
            client = TestClient(_make_app())
            resp = client.get("/api/protected", headers={"X-DeerFlow-Tenant": "myorg"})
        assert resp.status_code == 200
        assert resp.json()["tenant"] == "myorg"

    def test_invalid_tenant_header_raises_400(self):
        load_auth_config_from_dict({"enabled": False})
        with patch("app.gateway.auth.middleware.TenantStorage.get", side_effect=_mock_tenant_get):
            client = TestClient(_make_app())
            resp = client.get("/api/protected", headers={"X-DeerFlow-Tenant": "../etc"})
        assert resp.status_code == 400


class TestJwtAuth:
    def test_missing_auth_header_returns_401(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        client = TestClient(_make_app())
        resp = client.get("/api/protected")
        assert resp.status_code == 401

    def test_valid_jwt_sets_tenant(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        token = create_access_token(tenant_id="acme", username="admin", role="admin")
        with patch("app.gateway.auth.middleware.TenantStorage.get", side_effect=_mock_tenant_get):
            client = TestClient(_make_app())
            resp = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["tenant"] == "acme"

    def test_invalid_jwt_returns_401(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        client = TestClient(_make_app())
        resp = client.get("/api/protected", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_wrong_secret_jwt_returns_401(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        token = create_access_token(tenant_id="acme", username="admin")
        # Change secret
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "different-secret"})
        client = TestClient(_make_app())
        resp = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_refresh_token_rejected_for_api_access(self):
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test-secret"})
        from app.gateway.auth.jwt_handler import create_refresh_token
        refresh = create_refresh_token(tenant_id="acme", username="admin")
        client = TestClient(_make_app())
        resp = client.get("/api/protected", headers={"Authorization": f"Bearer {refresh}"})
        assert resp.status_code == 401


class TestApiKeyAuth:
    def test_valid_api_key_access(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        from app.gateway.auth.api_key_handler import create_api_key

        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        result = create_api_key(name="test-key")
        with patch("app.gateway.auth.middleware.TenantStorage.get", side_effect=_mock_tenant_get):
            client = TestClient(_make_app())
            resp = client.get(
                "/api/protected",
                headers={
                    "Authorization": f"Bearer {result['raw_key']}",
                    "X-DeerFlow-Tenant": "default",
                },
            )
        assert resp.status_code == 200

    def test_invalid_api_key_returns_401(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.gateway.auth.api_key_handler._api_keys_file", lambda: tmp_path / "api_keys.json")
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "s"})
        client = TestClient(_make_app())
        resp = client.get(
            "/api/protected",
            headers={"Authorization": "Bearer df-fakekey123"},
        )
        assert resp.status_code == 401


class TestTenantEnforcement:
    def test_nonexistent_tenant_returns_403(self):
        load_auth_config_from_dict({"enabled": False})
        with patch("app.gateway.auth.middleware.TenantStorage.get", return_value=None):
            client = TestClient(_make_app())
            resp = client.get("/api/protected", headers={"X-DeerFlow-Tenant": "ghost"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "tenant_not_found"

    def test_disabled_tenant_returns_403(self):
        load_auth_config_from_dict({"enabled": False})
        tc = TenantConfig(tenant_id="disabled-org", name="Disabled", is_active=False)
        with patch("app.gateway.auth.middleware.TenantStorage.get", return_value=tc):
            client = TestClient(_make_app())
            resp = client.get("/api/protected", headers={"X-DeerFlow-Tenant": "disabled-org"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "tenant_disabled"

    def test_admin_paths_skip_enforcement(self):
        load_auth_config_from_dict({"enabled": False})
        with patch("app.gateway.auth.middleware.TenantStorage.get", return_value=None):
            client = TestClient(_make_app())
            resp = client.get("/api/admin/tenants", headers={"X-DeerFlow-Tenant": "ghost"})
        assert resp.status_code == 200
