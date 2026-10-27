from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import enterprise, enterprise_mail_outbox
from deerflow.integrations.enterprise.mail_sender import AliMailSender
from deerflow.integrations.enterprise.providers import EnterpriseError
from deerflow.integrations.enterprise.store import EnterpriseStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = EnterpriseStore(tmp_path)
    account = store.create_mail_account("alice", "Office", {"email": "alice@example.com", "password": "private-password", "host": "imap.qiye.aliyun.com"})
    authorize = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(enterprise_mail_outbox, "authorize", authorize)
    monkeypatch.setattr(enterprise_mail_outbox, "make_store", lambda _: store)
    sender = MagicMock(return_value={"status": "sent", "error": None, "accepted": ["bob@example.com"], "refused": []})
    monkeypatch.setattr(AliMailSender, "send", sender)
    app = FastAPI()
    app.include_router(enterprise.router)

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth_source = request.headers.get("x-source", "session")
        request.state.user = SimpleNamespace(id=request.headers.get("x-user", "alice"), system_role="user")
        return await call_next(request)

    with TestClient(app) as http:
        yield http, account["id"], sender, authorize


def test_preview_confirmation_owner_scoping_and_live_revocation(client):
    http, account_id, sender, authorize = client
    payload = {"account_id": account_id, "to": ["bob@example.com"], "subject": "Hello", "body": "Preview me"}
    base = "/api/enterprise/mail/drafts"
    assert http.post(base, json=payload, headers={"x-source": "pat"}).status_code == 403
    draft = http.post(base, json=payload)
    assert draft.status_code == 200
    sender.assert_not_called()
    assert "private-password" not in draft.text
    url = base + "/" + draft.json()["id"]
    assert http.get(url, headers={"x-user": "bob"}).status_code == 404
    assert http.post(url + "/send", json={"confirmed": True}, headers={"x-user": "bob"}).status_code == 404
    assert http.post(url + "/send", json={}).status_code == 400
    assert http.post(url + "/send", json={"confirmed": False}).status_code == 400
    assert http.post(url + "/send", json={"confirmed": True}, headers={"x-source": "internal"}).status_code == 403
    assert authorize.call_args.kwargs == {"tool_name": "enterprise_mail_compose"}
    authorize.side_effect = EnterpriseError("access_denied")
    assert http.post(url + "/send", json={"confirmed": True}).status_code == 403
    sender.assert_not_called()
    authorize.side_effect = None
    assert http.post(url + "/send", json={"confirmed": True}).json()["status"] == "sent"
    assert http.post(url + "/send", json={"confirmed": True}).json()["status"] == "sent"
    assert sender.call_count == 1


def test_body_limit_and_validation_do_not_echo_private_content(client):
    http, account_id, sender, _ = client
    for payload in ({"account_id": account_id, "body": "private-body"}, {"account_id": account_id, "to": ["bad"], "subject": "title", "body": "private-body"}):
        result = http.post("/api/enterprise/mail/drafts", json=payload)
        assert result.status_code == 400
        assert "private-body" not in result.text
    result = http.post("/api/enterprise/mail/drafts", content=b"x" * 131073, headers={"Content-Type": "application/json"})
    assert result.status_code == 413
    sender.assert_not_called()
