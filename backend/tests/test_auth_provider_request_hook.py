from __future__ import annotations

import pytest
from fastapi import Request

from app.gateway.auth.models import User
from app.gateway.auth.providers import AuthProvider


class _NullProvider(AuthProvider):
    async def authenticate(self, credentials: dict) -> User | None:
        return None

    async def get_user(self, user_id: str) -> User | None:
        return None


class _RequestProvider(_NullProvider):
    async def authenticate_request(self, request: Request) -> User | None:
        return User.model_construct(id="user-1", email="hook@test.com", password_hash="hash")


def _make_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/models",
        "raw_path": b"/api/models",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.anyio
async def test_auth_provider_request_hook_defaults_to_none():
    provider = _NullProvider()

    assert await provider.authenticate_request(_make_request()) is None


@pytest.mark.anyio
async def test_auth_provider_request_hook_can_be_overridden():
    provider = _RequestProvider()

    resolved = await provider.authenticate_request(_make_request())

    assert resolved is not None
    assert resolved.email == "hook@test.com"
