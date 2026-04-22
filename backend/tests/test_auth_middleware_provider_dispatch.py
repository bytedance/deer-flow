"""Provider-dispatch tests for AuthMiddleware request-level auth."""

from __future__ import annotations

from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.gateway.auth import AuthConfig, TrustedHeaderProviderConfig, set_auth_config
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware


def _make_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/models")
    async def models_get():
        return {"models": []}

    return app


def _inject_client_host(app, host: str):
    @app.middleware("http")
    async def _set_client_host(request, call_next):
        request.scope["client"] = (host, 80)
        return await call_next(request)


class _Repo:
    def __init__(self, user: User | None = None) -> None:
        self._user = user

    async def create_user(self, user):
        self._user = user
        return user

    async def get_user_by_id(self, user_id: str):
        if self._user and str(self._user.id) == user_id:
            return self._user
        return None

    async def get_user_by_email(self, email: str):
        return None

    async def update_user(self, user):
        self._user = user
        return user

    async def count_users(self):
        return 1 if self._user else 0

    async def count_admin_users(self):
        return 0

    async def get_user_by_oauth(self, provider: str, oauth_id: str):
        return None


@pytest.mark.anyio
async def test_provider_local_does_not_use_forwarded_user(monkeypatch):
    app = _make_app()
    set_auth_config(AuthConfig(jwt_secret="secret", provider="local"))
    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo())

    with TestClient(app) as client:
        response = client.get("/api/models", headers={"X-Forwarded-User": "abc"})

    assert response.status_code == 401


@pytest.mark.anyio
async def test_provider_trusted_header_uses_forwarded_user(monkeypatch):
    app = _make_app()
    _inject_client_host(app, "10.1.2.3")
    user = User(id=uuid4(), email="trusted@test.com", password_hash="hash")
    set_auth_config(
        AuthConfig(
            jwt_secret="secret",
            provider="trusted_header",
            trusted_header=TrustedHeaderProviderConfig(
                enabled=True,
                trusted_networks=["10.0.0.0/8"],
                user_id_header="X-Forwarded-User",
            ),
        )
    )
    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo(user))

    with TestClient(app) as client:
        response = client.get("/api/models", headers={"X-Forwarded-User": str(user.id)})

    assert response.status_code == 200


def test_auth_config_rejects_trusted_header_without_networks():
    with pytest.raises(ValueError, match="trusted_networks"):
        set_auth_config(
            AuthConfig(
                jwt_secret="secret",
                provider="trusted_header",
                trusted_header=TrustedHeaderProviderConfig(enabled=True, trusted_networks=[]),
            )
        )
