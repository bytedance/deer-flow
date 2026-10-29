"""Router tests for legacy IM channel management endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import channels


def _admin_user() -> User:
    return User(
        id=UUID("11111111-2222-3333-4444-555555555555"),
        email="admin@example.com",
        password_hash="x",
        system_role="admin",
    )


def _non_admin_user() -> User:
    return User(
        id=UUID("99999999-8888-7777-6666-555555555555"),
        email="user@example.com",
        password_hash="x",
        system_role="user",
    )


def test_restart_channel_requires_admin(monkeypatch):
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=True))
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_non_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/restart")

    assert response.status_code == 403
    assert "Admin privileges" in response.json()["detail"]
    service.restart_channel.assert_not_awaited()


def test_restart_channel_allows_admin(monkeypatch):
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=True))
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/slack/restart")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Channel slack restarted successfully",
    }
    service.restart_channel.assert_awaited_once_with("slack")


def test_get_channels_status_remains_read_only(monkeypatch):
    service = SimpleNamespace(
        get_status=lambda: {
            "service_running": True,
            "channels": {
                "slack": {
                    "enabled": True,
                    "running": True,
                }
            },
        }
    )
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_non_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.get("/api/channels/")

    assert response.status_code == 200
    assert response.json()["service_running"] is True
    assert response.json()["channels"]["slack"]["running"] is True


def test_restart_on_a_non_holder_names_the_lease_holder(monkeypatch):
    """channels.leader_lease: a restart that reaches an instance without the provider's lease says where it runs."""
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=False), leader_of=lambda name: "pod-b:worker", lease_owner_id="pod-a:worker")
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/telegram/restart")

    assert response.status_code == 200
    assert response.json() == {"success": False, "message": "Channel telegram is connected by another Gateway instance (pod-b:worker); it can only be restarted there"}


def test_a_failed_restart_on_the_holder_keeps_the_generic_message(monkeypatch):
    service = SimpleNamespace(restart_channel=AsyncMock(return_value=False), leader_of=lambda name: "pod-a:worker", lease_owner_id="pod-a:worker")
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: service)
    app = make_authed_test_app(user_factory=_admin_user)
    app.include_router(channels.router)

    with TestClient(app) as client:
        response = client.post("/api/channels/telegram/restart")

    assert response.json() == {"success": False, "message": "Failed to restart channel telegram"}
