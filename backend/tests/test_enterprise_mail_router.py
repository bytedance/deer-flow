from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import enterprise, enterprise_mail
from deerflow.integrations.enterprise.mail import AliMailClient
from deerflow.integrations.enterprise.providers import EnterpriseError
from deerflow.integrations.enterprise.store import EnterpriseStore


@pytest.fixture
def mail_client(tmp_path, monkeypatch):
    check = AsyncMock(return_value=SimpleNamespace())
    store = EnterpriseStore(tmp_path)
    monkeypatch.setattr(enterprise_mail, "authorize", check)
    monkeypatch.setattr(enterprise_mail, "make_store", lambda _: store)
    monkeypatch.setattr(AliMailClient, "check", lambda *_: None)
    monkeypatch.setattr(AliMailClient, "read", lambda *_, **kwargs: {"messages": [], "read_only": True, **kwargs})
    app = FastAPI()
    app.include_router(enterprise.router)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth_source = request.headers.get("x-source", "session")
        request.state.user = SimpleNamespace(id=request.headers.get("x-user", "alice"), system_role="user")
        return await call_next(request)

    with TestClient(app) as http:
        yield http, check, store


def test_session_scoping_revocation_and_secret_redaction(mail_client):
    http, check, _ = mail_client
    payload = {"name": "Office", "email": "alice@example.com", "password": "sensitive-password"}
    assert http.get("/api/enterprise/mail", headers={"x-source": "pat"}).status_code == 403
    response = http.post("/api/enterprise/mail/accounts", json=payload)
    assert response.status_code == 200
    assert "sensitive-password" not in response.text
    account_id = response.json()["id"]
    assert len(http.get("/api/enterprise/mail").json()["accounts"]) == 1
    assert http.get("/api/enterprise/mail", headers={"x-user": "bob"}).json()["accounts"] == []
    url = f"/api/enterprise/mail/accounts/{account_id}"
    assert http.get(url + "/messages", headers={"x-user": "bob"}).status_code == 404
    assert http.delete(url, headers={"x-user": "bob"}).status_code == 404
    assert http.get(url + "/messages").json()["read_only"]
    assert check.call_args.kwargs == {"tool_name": "enterprise_mail"}
    check.side_effect = EnterpriseError("access_denied")
    assert http.get(url + "/messages").status_code == 403
    assert http.delete(url).status_code == 403
    assert http.post("/api/enterprise/mail/accounts", json=payload).status_code == 403


def test_validation_errors_do_not_echo_credentials_and_disconnect_preserves_other_provider(mail_client):
    http, _, store = mail_client
    for payload in ({"password": "sensitive-password"}, {"name": [], "email": [], "password": "sensitive-password"}):
        response = http.post("/api/enterprise/mail/accounts", json=payload)
        assert response.status_code == 400
        assert "sensitive-password" not in response.text
    target = store.create_target("alice", "Group", "wecom_webhook", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    assert http.delete(f"/api/enterprise/mail/accounts/{target['id']}").status_code == 404
    assert len(store.list_targets("alice")) == 1
