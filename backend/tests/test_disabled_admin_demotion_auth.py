"""Disabled-admin demotion through production session and CSRF middleware."""

import asyncio
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_app(monkeypatch, tmp_path):
    from app.gateway import deps
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import login_throttle
    from app.gateway.routers import auth
    from deerflow.config.app_config import pop_current_app_config, push_current_app_config, reload_app_config, reset_app_config
    from deerflow.config.extensions_config import reset_extensions_config
    from deerflow.extensions import get_loaded_extensions, get_runtime_diagnostics, initialize_runtime_diagnostics, set_loaded_extensions
    from deerflow.persistence.engine import close_engine, init_engine

    config_path = tmp_path / "config.yaml"
    config_path.write_text("models: []\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="disabled-admin-regression-secret-at-least-32"))
    monkeypatch.setattr(deps, "_cached_repo", None)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(login_throttle, "_store", None)
    monkeypatch.setattr(auth, "_SETUP_STATUS_CACHE", {})
    monkeypatch.setattr(auth, "_SETUP_STATUS_INFLIGHT", {})
    with ExitStack() as cleanup:
        # Environment selectors do not override pinned config or a run-scoped
        # ContextVar. Isolate both, including create_app's import-time instance.
        cleanup.callback(reset_app_config)
        cleanup.callback(reset_extensions_config)
        cleanup.callback(set_loaded_extensions, get_loaded_extensions())
        cleanup.callback(initialize_runtime_diagnostics, get_runtime_diagnostics())
        reset_app_config()
        reset_extensions_config()
        push_current_app_config(reload_app_config())
        cleanup.callback(pop_current_app_config)
        cleanup.callback(lambda: asyncio.run(close_engine()))
        asyncio.run(init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path}/users.db", sqlite_dir=str(tmp_path)))

        from app.gateway.app import create_app

        # As in the auth integration suite, initialize persistence explicitly;
        # the Agent/sandbox lifespan is unrelated to these account operations.
        yield create_app()


def _csrf(client):
    token = client.cookies.get("csrf_token")
    assert token
    return {"X-CSRF-Token": token}


@pytest.mark.parametrize("reenable", [False, True], ids=["restore-later", "restore-in-same-patch"])
def test_disabled_admin_demotion_preserves_session_authorization(auth_app, reenable):
    admin = TestClient(auth_app)
    target = TestClient(auth_app)
    anonymous = TestClient(auth_app)
    try:
        first = admin.post("/api/v1/auth/initialize", json={"email": "admin@example.com", "password": "Adm1n!Pass99"})
        assert first.status_code == 201
        registered = target.post("/api/v1/auth/register", json={"email": "target@example.com", "password": "Us3r!Pass99"})
        assert registered.status_code == 201
        assert admin.cookies.get("access_token") and target.cookies.get("access_token")
        admin_url = f"/api/v1/admin/users/{first.json()['id']}"
        target_url = f"/api/v1/admin/users/{registered.json()['id']}"

        assert anonymous.get("/api/v1/admin/users").status_code == 401
        assert target.patch(target_url, json={"system_role": "admin"}, headers=_csrf(target)).status_code == 403
        assert admin.patch(target_url, json={"system_role": "admin"}, headers=_csrf(admin)).status_code == 200
        assert target.get("/api/v1/admin/users").status_code == 200
        assert admin.patch(target_url, json={"disabled": True}, headers=_csrf(admin)).status_code == 200

        # Both the existing signed session and a fresh password login are refused.
        assert target.get("/api/v1/auth/me").status_code == 401
        denied_login = target.post("/api/v1/auth/login/local", data={"username": "target@example.com", "password": "Us3r!Pass99"})
        assert denied_login.status_code == 401
        assert admin.patch(admin_url, json={"system_role": "user"}, headers=_csrf(admin)).status_code == 409

        body = {"system_role": "user"}
        if reenable:
            body["disabled"] = False
        assert admin.patch(target_url, json=body).status_code == 403
        changed = admin.patch(target_url, json=body, headers=_csrf(admin))
        assert changed.status_code == 200, changed.text
        assert changed.json()["system_role"] == "user"
        assert changed.json()["disabled"] is (not reenable)
        if not reenable:
            assert target.get("/api/v1/auth/me").status_code == 401
            restored = admin.patch(target_url, json={"disabled": False}, headers=_csrf(admin))
            assert restored.status_code == 200
            assert restored.json()["system_role"] == "user"

        # A pre-suspension admin cookie resolves the current database role.
        assert target.get("/api/v1/auth/me").json()["system_role"] == "user"
        assert target.get("/api/v1/admin/users").status_code == 403
        target.cookies.clear()
        logged_in = target.post("/api/v1/auth/login/local", data={"username": "target@example.com", "password": "Us3r!Pass99"})
        assert logged_in.status_code == 200
        assert target.get("/api/v1/auth/me").json()["system_role"] == "user"
        assert target.patch(target_url, json={"system_role": "admin"}, headers=_csrf(target)).status_code == 403
        assert admin.patch(admin_url, json={"system_role": "user"}, headers=_csrf(admin)).status_code == 409
        assert admin.patch(admin_url, json={"disabled": True}, headers=_csrf(admin)).status_code == 409
        assert admin.get("/api/v1/admin/users").status_code == 200
    finally:
        anonymous.close()
        target.close()
        admin.close()
