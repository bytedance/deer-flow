"""Authorization contracts for the tenant-isolated skill marketplace."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skill_market


def _user(role: str) -> User:
    return User(
        id=uuid4(),
        email=f"{role}@example.com",
        password_hash="x",
        system_role=role,
    )


def _app(role: str):
    app = make_authed_test_app(user_factory=lambda: _user(role))
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    app.include_router(skill_market.router)
    return app


def test_normal_user_cannot_list_or_publish_admin_market_entries():
    """The administrator catalogue is never exposed to ordinary tenants."""
    with TestClient(_app("user")) as client:
        assert client.get("/api/admin/skill-market").status_code == 403
        assert (
            client.post(
                "/api/admin/skill-market",
                json={
                    "name": "demo",
                    "description": "demo",
                    "version": "1.0.0",
                    "content": "---\nname: demo\ndescription: demo\n---\n",
                },
            ).status_code
            == 403
        )


def test_market_install_is_explicitly_non_destructive_by_default():
    """The request model defaults to retaining the user's installed copy."""
    assert skill_market.MarketSkillInstallRequest().update is False
    assert skill_market.MarketSkillInstallRequest(update=True).update is True
