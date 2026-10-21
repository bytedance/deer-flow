"""The HTTP boundary never accepts a caller-supplied owner or returns secrets."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_tracing_profiles import control as _control_fixture

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext, Permissions
from deerflow.config.agents_config import AgentConfig

control = _control_fixture


@pytest.fixture
def api(control, monkeypatch):
    from app.gateway.routers import tracing

    service, _, _, _ = control
    owner = User(id=UUID("11111111-1111-1111-1111-111111111111"), email="admin@example.com", system_role="admin")
    auth = AuthContext(user=owner, permissions=[Permissions.AGENTS_READ, Permissions.AGENTS_WRITE])
    monkeypatch.setattr("app.gateway.authz._authenticate", AsyncMock(return_value=auth))
    monkeypatch.setattr(tracing, "get_profile_service", lambda: service)
    monkeypatch.setattr(tracing, "_require_agents_api_enabled", lambda: None)

    def load(name, *, user_id):
        if name == "worker" and user_id == str(owner.id):
            return AgentConfig(name=name)
        raise FileNotFoundError()

    monkeypatch.setattr(tracing, "load_agent_config", load)
    monkeypatch.setattr(tracing, "get_effective_user_id", lambda: str(auth.user.id))
    app = FastAPI()
    app.include_router(tracing.router)
    with TestClient(app) as client:
        yield client, auth, owner, service


def _draft(owner):
    return {"name": "Operations", "expected_revision": 0, "allowed_user_ids": [str(owner.id)], "providers": [{"provider": "arize", "endpoint": "https://otlp.arize.com", "project": "project", "space_id": "space", "api_key": "http-secret"}]}


def test_admin_profile_commit_is_redacted_and_agent_binding_is_active(api):
    client, _, owner, _ = api
    response = client.post("/api/tracing/profiles", json=_draft(owner))
    assert response.status_code == 200, response.text
    profile = response.json()
    assert "http-secret" not in response.text and profile["providers"][0]["has_api_key"]
    assert client.get("/api/tracing/profiles").json()["profiles"][0]["id"] == profile["id"]
    saved = client.put("/api/agents/worker/tracing", json={"mode": "configured", "profile_id": profile["id"], "expected_revision": 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "active"
    assert saved.json()["delivery_verified"] is False
    assert saved.json()["revision"] == 1
    assert "http-secret" not in saved.text
    assert client.put("/api/agents/worker/tracing", json={"mode": "inherit", "profile_id": None, "expected_revision": 0}).status_code == 409


def test_profile_validation_and_unknown_field_failures_never_echo_secrets(api):
    client, _, owner, _ = api
    draft = _draft(owner)
    draft["providers"][0]["endpoint"] = "https://attacker.example/?token=http-secret"
    response = client.post("/api/tracing/profiles", json=draft)
    assert response.status_code == 422
    assert "http-secret" not in response.text
    draft = _draft(owner)
    draft["owner_user_id"] = "http-secret"
    response = client.post("/api/tracing/profiles", json=draft)
    assert response.status_code == 422 and "http-secret" not in response.text


@pytest.mark.parametrize("transport", ["http", "grpc"])
def test_public_plaintext_profile_is_rejected_without_persisting_or_echoing_credentials(api, transport):
    client, _, owner, service = api
    draft = _draft(owner)
    draft["providers"][0].update(endpoint="http://collector.example/v1/traces", transport=transport)
    response = client.post("/api/tracing/profiles", json=draft)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_tracing_configuration"
    assert "HTTPS" in response.json()["detail"]["message"]
    assert "http-secret" not in response.text
    assert service.repository.list_profiles() == []


def test_nonadmin_cannot_manage_profiles_and_cannot_read_another_owners_binding(api):
    client, auth, owner, _ = api
    profile = client.post("/api/tracing/profiles", json=_draft(owner)).json()
    auth.user = User(id=UUID("22222222-2222-2222-2222-222222222222"), email="other@example.com")
    assert client.get("/api/tracing/profiles").json()["profiles"] == []
    assert client.post("/api/tracing/profiles", json=_draft(owner)).status_code == 403
    assert client.put(f"/api/tracing/profiles/{profile['id']}", json=_draft(owner)).status_code == 403
    assert client.get("/api/agents/worker/tracing").status_code == 404
    assert client.put("/api/agents/worker/tracing", json={"mode": "disabled", "expected_revision": 0}).status_code == 404


def test_agent_binding_requires_write_permission_and_authentication(api):
    client, auth, owner, _ = api
    auth.permissions = [Permissions.AGENTS_READ]
    assert client.get("/api/agents/worker/tracing").json()["can_select"] is False
    assert client.put("/api/agents/worker/tracing", json={"mode": "disabled", "expected_revision": 0}).status_code == 403
    auth.user = None
    assert client.get("/api/tracing/profiles").status_code == 401


@pytest.mark.asyncio
async def test_admin_pat_has_no_profile_management_capability():
    from fastapi import Request

    from app.gateway.auth_disabled import AUTH_SOURCE_PAT
    from app.gateway.routers.tracing import _can_manage

    user = User(email="admin@example.com", system_role="admin")
    request = Request({"type": "http", "state": {"user": user, "auth": AuthContext(user=user), "auth_source": AUTH_SOURCE_PAT}})
    assert await _can_manage(request) is False


@pytest.mark.asyncio
async def test_profile_write_drains_the_transaction_after_caller_cancellation(control, monkeypatch):
    import asyncio
    import threading

    from fastapi import Request

    from app.gateway.routers import tracing

    service, _, _, _ = control
    user = User(email="admin@example.com", system_role="admin")
    request = Request({"type": "http", "state": {"user": user, "auth": AuthContext(user=user)}})
    entered, release = threading.Event(), threading.Event()
    original_save = service.repository.save_profile

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(service.repository, "save_profile", paused)
    monkeypatch.setattr(tracing, "get_profile_service", lambda: service)
    body = tracing.ProfileWriteRequest.model_validate(_draft(user))
    operation = asyncio.create_task(tracing.create_profile.__wrapped__(body, request))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        assert not operation.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
    assert service.list_profiles(str(user.id), is_admin=True)[0]["revision"] == 1


def test_unavailable_authority_is_reported_without_claiming_active_delivery(api, monkeypatch):
    from app.gateway.routers import tracing
    from deerflow.tracing.profiles import TracingUnavailableError

    client, _, owner, _ = api

    def unavailable():
        raise TracingUnavailableError("Tracing profiles require a durable database")

    monkeypatch.setattr(tracing, "get_profile_service", unavailable)
    profiles = client.get("/api/tracing/profiles").json()
    assert profiles["available"] is False and profiles["profiles"] == []
    binding = client.get("/api/agents/worker/tracing").json()
    assert binding["status"] == "unavailable" and binding["delivery_verified"] is False
    assert client.post("/api/tracing/profiles", json=_draft(owner)).status_code == 503
