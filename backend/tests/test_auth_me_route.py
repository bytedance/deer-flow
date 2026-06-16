import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.routing import Router as StarletteRouter

# FastAPI in this repo still passes startup/shutdown kwargs to Starlette's
# Router, but some test environments pin an older Starlette that doesn't
# accept them. Patch only for this test module so we can import the router.
if "on_startup" not in inspect.signature(StarletteRouter.__init__).parameters:
    _ORIGINAL_ROUTER_INIT = StarletteRouter.__init__

    def _compat_router_init(
        self,
        *args,
        on_startup=None,
        on_shutdown=None,
        lifespan=None,
        **kwargs,
    ):
        return _ORIGINAL_ROUTER_INIT(self, *args, **kwargs)

    StarletteRouter.__init__ = _compat_router_init

from app.gateway.routers.auth import get_me


def _make_request(cookie_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header is not None:
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/me",
        "headers": headers,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_get_me_prefers_authenticated_request_state_over_stale_cookie():
    request = _make_request("access_token=stale-token")
    request.state.user = SimpleNamespace(
        id="user-1",
        email="user@example.com",
        system_role="user",
        tenant_id="tenant-a",
        user_name="alice",
        real_name="Alice",
    )

    class DummyInsBaseProvider:
        def __init__(self) -> None:
            self.get_user = AsyncMock(return_value=None)

    provider = DummyInsBaseProvider()

    with (
        patch("app.gateway.deps.get_ins_base_provider", return_value=provider),
        patch("app.gateway.routers.auth.InsBaseAuthProvider", DummyInsBaseProvider),
    ):
        result = await get_me(request)

    assert result.id == "user-1"
    assert result.email == "user@example.com"
    assert result.system_role == "user"
    assert result.tenant_id == "tenant-a"
    assert result.user_name == "alice"
    assert result.real_name == "Alice"
    provider.get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_me_falls_back_to_provider_when_request_state_missing():
    request = _make_request("access_token=fresh-token")

    class DummyInsBaseProvider:
        def __init__(self) -> None:
            self.get_user = AsyncMock(
                return_value=SimpleNamespace(
                    id="user-2",
                    email="ops@example.com",
                    system_role="tenant_admin",
                    tenant_id="tenant-b",
                    ins_base_user_data={
                        "userId": "user-2",
                        "userName": "ops-admin",
                        "realName": "Ops Admin",
                    },
                )
            )

    provider = DummyInsBaseProvider()

    with (
        patch("app.gateway.deps.get_ins_base_provider", return_value=provider),
        patch("app.gateway.routers.auth.InsBaseAuthProvider", DummyInsBaseProvider),
    ):
        result = await get_me(request)

    assert result.id == "user-2"
    assert result.email == "ops@example.com"
    assert result.system_role == "tenant_admin"
    assert result.tenant_id == "tenant-b"
    assert result.user_name == "ops-admin"
    assert result.real_name == "Ops Admin"
    provider.get_user.assert_awaited_once_with("fresh-token")
