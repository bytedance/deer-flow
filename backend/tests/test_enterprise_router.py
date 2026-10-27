from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import enterprise
from deerflow.integrations.enterprise.providers import EnterpriseError
from deerflow.integrations.enterprise.store import EnterpriseStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = SimpleNamespace(scheduler=SimpleNamespace(enabled=True, multi_instance=False))
    check = AsyncMock(return_value=config)
    monkeypatch.setattr(enterprise, "authorize", check)
    store = EnterpriseStore(tmp_path)
    monkeypatch.setattr(enterprise, "make_store", lambda _: store)
    app = FastAPI()
    app.include_router(enterprise.router)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth_source = request.headers.get("x-source", "session")
        request.state.user = SimpleNamespace(id=request.headers.get("x-user", "alice"), system_role=request.headers.get("x-role", "user"))
        return await call_next(request)

    with TestClient(app) as http:
        yield http, check


def test_session_only_crud_and_cross_user_isolation(client):
    http, _ = client
    assert http.get("/api/enterprise", headers={"x-source": "pat"}).status_code == 403
    result = http.post("/api/enterprise/targets", json={"name": "运营群", "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private-key"})
    assert result.status_code == 200
    assert "private-key" not in result.text
    target = result.json()["id"]
    assert len(http.get("/api/enterprise").json()["targets"]) == 1
    assert http.get("/api/enterprise", headers={"x-user": "bob"}).json()["targets"] == []
    http.delete(f"/api/enterprise/targets/{target}", headers={"x-user": "bob"})
    assert len(http.get("/api/enterprise").json()["targets"]) == 1
    result = http.post("/api/enterprise/send", headers={"x-user": "bob"}, json={"target_id": target, "content": "hello", "request_key": "request-key"})
    assert result.status_code == 404
    http.delete(f"/api/enterprise/targets/{target}")
    assert http.get("/api/enterprise").json()["targets"] == []


def test_revoked_permission_rechecked_for_every_request(client):
    http, check = client
    assert http.get("/api/enterprise").status_code == 200
    check.side_effect = EnterpriseError("access_denied")
    assert http.get("/api/enterprise").status_code == 403
    assert http.post("/api/enterprise/send", json={"target_id": "x", "content": "hello", "request_key": "request-key"}).status_code == 403


@pytest.mark.parametrize("grant_mode", ["admin", "direct", "group"])
def test_real_authorization_allows_granted_users_and_rechecks_revocation(client, tmp_path, monkeypatch, grant_mode):
    from deerflow.authz.user_policy import PROVIDER_PATH
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.integrations.enterprise import access
    from deerflow.security.store import UserSecurityStore

    http, _ = client
    config = SimpleNamespace(
        get_tool_config=lambda _: SimpleNamespace(use=access.TOOL_USE),
        scheduler=SimpleNamespace(enabled=True, multi_instance=False),
        authorization=AuthorizationConfig(enabled=True, provider={"use": PROVIDER_PATH, "config": {"store_path": str(tmp_path)}}),
    )
    monkeypatch.setattr(access, "get_app_config", lambda: config)
    monkeypatch.setattr(enterprise, "authorize", access.authorize)
    store = UserSecurityStore(tmp_path)
    if grant_mode == "direct":
        store.set_grant("alice", "tool", "enterprise_messaging", True, actor="admin")
    elif grant_mode == "group":
        group = store.create_group("Operations", actor="admin")
        store.set_member(group["id"], "alice", True, actor="admin")
        store.set_group_grant(group["id"], "tool", "enterprise_messaging", True, actor="admin")

    headers = {"x-role": "admin" if grant_mode == "admin" else "user"}
    response = http.get("/api/enterprise", headers=headers)
    assert response.status_code == 200, response.text
    response = http.post("/api/enterprise/targets", headers=headers, json={"name": "Operations", "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only"})
    assert response.status_code == 200, response.text
    assert len(http.get("/api/enterprise", headers=headers).json()["targets"]) == 1
    assert http.get("/api/enterprise", headers={"x-user": "bob"}).status_code == 403

    if grant_mode != "admin":
        store.set_override("alice", "tool", "enterprise_messaging", "deny", actor="admin")
        assert http.get("/api/enterprise").status_code == 403
        assert http.post("/api/enterprise/send", json={"target_id": response.json()["id"], "content": "hello", "request_key": "request-key"}).status_code == 403
