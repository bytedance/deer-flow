"""Regression tests for the PermissionProvider plumbing (plan M0-7 / M0-8).

The enterprise plan §2.2 enumerates four cases that the M0 wiring MUST satisfy
so that the M1 ``RbacPermissionProvider`` can drop in without further patches:

1. **No provider registered** -> ``_authenticate()`` and ``AuthMiddleware`` both
   fall back to ``_ALL_PERMISSIONS`` (legacy behaviour).
2. **Provider registered** -> ``AuthContext.permissions`` equals what the
   provider returned (no implicit union with ``_ALL_PERMISSIONS``).
3. **Reverse evidence 1** — provider is actually called at least once during
   request handling (catches the "AuthMiddleware short-circuit" bug where the
   middleware stamps ``_ALL_PERMISSIONS`` and the decorator never re-enters
   ``_authenticate()``).
4. **Reverse evidence 2** — when ``request.state.auth`` is already populated by
   the middleware, ``@require_permission`` does **not** rebuild it (covers the
   ``authz.py:328-331`` short-circuit).
5. **Reverse evidence 3** — the ``internal_auth`` header branch follows the
   provider too (we choose: yes, internal callers also go through the
   provider, so admin tooling does not silently get ``_ALL_PERMISSIONS`` when
   RBAC says otherwise).

These tests are deliberately end-to-end at the ASGI level so any future
refactor that moves permission resolution into a different layer will fail
loudly here instead of silently regressing the whole RBAC story.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import (
    _ALL_PERMISSIONS,
    AuthContext,
    Permissions,
    _authenticate,
    _resolve_permissions_for_user,
    get_permission_provider,
    require_permission,
    set_permission_provider,
)
from app.gateway.internal_auth import create_internal_auth_headers

# ── Helpers ────────────────────────────────────────────────────────────────


class _RecordingProvider:
    """Test PermissionProvider that records every call.

    Returns a deliberately *narrow* permission set so we can distinguish it
    from the ``_ALL_PERMISSIONS`` fallback; if a test path silently used the
    fallback, the assertion ``permissions == {"threads:read"}`` would fail.
    """

    def __init__(self, permissions: set[str] | None = None) -> None:
        self._permissions = permissions if permissions is not None else {Permissions.THREADS_READ}
        self.calls: list[User] = []

    async def resolve_permissions(self, user: User) -> set[str]:
        self.calls.append(user)
        return set(self._permissions)


def _make_user() -> User:
    """Construct a fully-formed ``User`` for direct authz unit tests."""
    return User(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="alice@example.com",
        password_hash="$2b$12$dummy",
        system_role="user",
        created_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def _reset_provider() -> AsyncGenerator[None, None]:
    """Clear the module-global provider between tests.

    Without this, a test that registers a provider and asserts permissions
    leaks the binding into the next test, causing nondeterministic ordering
    failures.
    """
    set_permission_provider(None)
    try:
        yield
    finally:
        set_permission_provider(None)


# ── Direct unit tests on the resolver helper ───────────────────────────────


@pytest.mark.asyncio
async def test_no_provider_returns_all_permissions() -> None:
    """Plan §2.2 case 1: no provider -> ``_ALL_PERMISSIONS`` verbatim."""
    user = _make_user()

    permissions = await _resolve_permissions_for_user(user)

    assert permissions == _ALL_PERMISSIONS, "Default behaviour must equal _ALL_PERMISSIONS so the gateway works without the enterprise extension"


@pytest.mark.asyncio
async def test_registered_provider_overrides_fallback() -> None:
    """Plan §2.2 case 2: provider permissions replace ``_ALL_PERMISSIONS``.

    Crucially, we assert *equality* (no implicit union) — the plan requires
    callers to take responsibility for including legacy permissions if they
    want them.
    """
    user = _make_user()
    provider = _RecordingProvider(permissions={"agents:read", "agents:write"})
    set_permission_provider(provider)

    permissions = await _resolve_permissions_for_user(user)

    assert set(permissions) == {"agents:read", "agents:write"}
    assert "threads:read" not in permissions, "Provider output must NOT be unioned with _ALL_PERMISSIONS; the plan explicitly delegates that responsibility to the provider"
    assert provider.calls == [user]


@pytest.mark.asyncio
async def test_provider_exception_propagates_not_silently_fallback() -> None:
    """Misbehaving provider must surface, not silently grant ``_ALL_PERMISSIONS``."""

    class _BoomProvider:
        async def resolve_permissions(self, user: User) -> set[str]:
            raise RuntimeError("backend down")

    set_permission_provider(_BoomProvider())

    with pytest.raises(RuntimeError, match="backend down"):
        await _resolve_permissions_for_user(_make_user())


def test_set_get_permission_provider_roundtrip() -> None:
    """``set_permission_provider`` / ``get_permission_provider`` agree."""
    assert get_permission_provider() is None

    provider = _RecordingProvider()
    set_permission_provider(provider)
    assert get_permission_provider() is provider

    set_permission_provider(None)
    assert get_permission_provider() is None


# ── ASGI-level tests through AuthMiddleware ────────────────────────────────


def _build_app_with_middleware(monkeypatch: pytest.MonkeyPatch, user: User) -> FastAPI:
    """Build a minimal FastAPI app that mounts ``AuthMiddleware``.

    We monkeypatch ``get_current_user_from_request`` so the ASGI test does not
    need a real JWT pipeline — the focus is permission resolution, not token
    decoding. Routes echo back ``request.state.auth`` so tests can inspect the
    permissions actually handed to handlers.
    """

    async def _fake_get_current_user(request: Request) -> User:
        return user

    monkeypatch.setattr(
        "app.gateway.deps.get_current_user_from_request",
        _fake_get_current_user,
    )

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/echo-permissions")
    async def echo_permissions(request: Request) -> dict[str, list[str]]:
        auth: AuthContext = request.state.auth
        return {"permissions": list(auth.permissions)}

    @app.get("/api/echo-auth-id")
    async def echo_auth_id(request: Request) -> dict[str, str]:
        # Used to detect whether AuthContext is recreated per request.
        return {"auth_obj_id": str(id(request.state.auth))}

    return app


def test_middleware_uses_all_permissions_when_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider registered -> middleware stamps ``_ALL_PERMISSIONS``."""
    user = _make_user()
    client = TestClient(_build_app_with_middleware(monkeypatch, user))
    client.cookies.set("access_token", "irrelevant-because-monkeypatched")

    res = client.get("/api/echo-permissions")

    assert res.status_code == 200
    assert set(res.json()["permissions"]) == set(_ALL_PERMISSIONS)


def test_middleware_uses_provider_when_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider registered -> middleware delegates fully (no fallback union)."""
    user = _make_user()
    provider = _RecordingProvider(permissions={Permissions.THREADS_READ})
    set_permission_provider(provider)

    client = TestClient(_build_app_with_middleware(monkeypatch, user))
    client.cookies.set("access_token", "irrelevant-because-monkeypatched")

    res = client.get("/api/echo-permissions")

    assert res.status_code == 200
    assert res.json()["permissions"] == [Permissions.THREADS_READ]
    # Reverse-evidence 1: provider was called at least once during the request.
    # If the middleware used a cached/hardcoded result, ``calls`` would be empty.
    assert len(provider.calls) >= 1
    assert provider.calls[0].id == user.id


def test_middleware_short_circuits_require_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reverse-evidence 2: ``@require_permission`` reuses the middleware AuthContext.

    The middleware stamps ``request.state.auth`` once. When ``@require_permission``
    runs afterwards, it must take the ``auth is not None`` branch
    (authz.py:328-331) and *not* call ``_authenticate()`` again — otherwise the
    provider would be invoked twice per request, which becomes a real perf
    regression in M1 once RBAC starts hitting the database.

    We test ``@require_permission`` *without* ``@require_auth`` on top because
    that is precisely the short-circuit the plan §2.2 cares about. The
    ``require_auth`` decorator independently calls ``_authenticate()`` for its
    own 401-enforcement and is not part of the short-circuit contract.
    """
    user = _make_user()
    provider = _RecordingProvider(permissions={Permissions.THREADS_READ})
    set_permission_provider(provider)

    app = _build_app_with_middleware(monkeypatch, user)

    @app.get("/api/with-permission-only")
    @require_permission("threads", "read")
    async def with_permission_only(request: Request) -> dict[str, list[str]]:
        auth: AuthContext = request.state.auth
        return {"permissions": list(auth.permissions)}

    client = TestClient(app)
    client.cookies.set("access_token", "irrelevant-because-monkeypatched")

    res = client.get("/api/with-permission-only")
    assert res.status_code == 200
    assert res.json()["permissions"] == [Permissions.THREADS_READ]

    # Provider must be called exactly once: middleware path only. If
    # @require_permission stopped honouring the authz.py:328-331 short-circuit
    # it would re-enter _authenticate() and append a second call here.
    assert len(provider.calls) == 1, (
        f"Expected exactly one provider call; got {len(provider.calls)}. "
        "If this is >1 the @require_permission decorator is no longer "
        "honouring the authz.py:328-331 short-circuit and is re-resolving "
        "permissions even after AuthMiddleware already populated "
        "request.state.auth."
    )


def test_internal_auth_header_also_goes_through_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reverse-evidence 3: internal_auth callers honour the provider too.

    Choice (documented in the plan §2.2): internal callers MUST go through the
    provider so admin tooling does not silently bypass RBAC. If a future
    refactor introduces an "internal users get _ALL_PERMISSIONS" shortcut, this
    test fails immediately.
    """
    provider = _RecordingProvider(permissions={Permissions.RUNS_READ})
    set_permission_provider(provider)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/echo-permissions")
    async def echo_permissions(request: Request) -> dict[str, list[str]]:
        auth: AuthContext = request.state.auth
        return {"permissions": list(auth.permissions)}

    client = TestClient(app)

    res = client.get("/api/echo-permissions", headers=create_internal_auth_headers())

    assert res.status_code == 200
    assert res.json()["permissions"] == [Permissions.RUNS_READ]
    assert len(provider.calls) >= 1, "Internal auth path must consult the provider"


# ── _authenticate() integration (decorator-only path) ──────────────────────


@pytest.mark.asyncio
async def test_authenticate_uses_provider_when_middleware_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decorator-only path (no AuthMiddleware): ``_authenticate`` consults the provider.

    Some tests / clients call decorated handlers without going through the
    ASGI middleware stack. ``_authenticate()`` is the last line of defence and
    must produce the same permission set as the middleware would.
    """
    user = _make_user()
    provider = _RecordingProvider(permissions={Permissions.RUNS_CANCEL})
    set_permission_provider(provider)

    async def _fake_get_optional_user(request: Request) -> User:
        return user

    monkeypatch.setattr(
        "app.gateway.deps.get_optional_user_from_request",
        _fake_get_optional_user,
    )

    # Build a minimal Request-like object — _authenticate only needs ``state``
    # and the import-time call to deps, which we monkeypatched above.
    from types import SimpleNamespace

    fake_request = SimpleNamespace(state=SimpleNamespace(), cookies={})

    auth_context = await _authenticate(fake_request)  # type: ignore[arg-type]

    assert auth_context.permissions == [Permissions.RUNS_CANCEL]
    assert provider.calls and provider.calls[0].id == user.id
