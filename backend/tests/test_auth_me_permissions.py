"""GET /api/v1/auth/me effective-permissions tests (RFC #4063 Phase 4).

Pins the /me wiring only: the field is populated from the AuthContext that
AuthMiddleware already resolves per request, and a middleware-less call
falls back to a fresh resolution with the same semantics ``_authenticate``
uses. The permission-derivation semantics themselves (disabled / fail-closed
/ fail-open / per-action requests) are pinned by
test_authorization_route_permissions.py and are not re-tested here.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-auth-me-permissions-min-32")

from app.gateway.authz import Permissions  # noqa: E402
from deerflow.authz.provider import AuthzDecision, AuthzReason  # noqa: E402
from deerflow.config.authorization_config import AuthorizationConfig  # noqa: E402

_TEST_SECRET = "test-secret-key-auth-me-permissions-min-32"

_ALL_PERMISSIONS = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


class _RecordingProvider:
    """Async-only provider recording every decision request it serves."""

    name = "recording"

    def __init__(self, *, denied: set[str] | None = None) -> None:
        self.denied = denied or set()
        self.requests = []

    def authorize(self, request):
        raise AssertionError("route authorization must use the async provider API")

    async def aauthorize(self, request):
        self.requests.append(request)
        allowed = request.target not in self.denied
        return AuthzDecision(
            allow=allowed,
            reasons=[AuthzReason(code="authz.allowed" if allowed else "authz.denied")],
        )

    def filter_resources(self, principal, resource_type, candidates):
        raise AssertionError("route authorization must preserve per-action requests")


@pytest.fixture(autouse=True)
def _setup_auth(tmp_path):
    """Fresh SQLite engine + auth config per test (test_initialize_admin pattern)."""
    from app.gateway import deps
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from app.gateway.routers.auth import _SETUP_STATUS_CACHE, _SETUP_STATUS_INFLIGHT
    from deerflow.persistence.engine import close_engine, init_engine

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    url = f"sqlite+aiosqlite:///{tmp_path}/auth_me.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    _SETUP_STATUS_CACHE.clear()
    _SETUP_STATUS_INFLIGHT.clear()
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        _SETUP_STATUS_CACHE.clear()
        _SETUP_STATUS_INFLIGHT.clear()
        asyncio.run(close_engine())


@pytest.fixture(autouse=True)
def _default_route_authorization_config(monkeypatch):
    """Keep /me independent of a repository config.yaml (disabled by default)."""
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: AuthorizationConfig(),
    )


@pytest.fixture()
def client(_setup_auth):
    from app.gateway.app import create_app
    from app.gateway.auth.config import AuthConfig, set_auth_config

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    app = create_app()
    # No context manager: the full lifespan requires config.yaml, the auth
    # routes work without it (the persistence engine is set up by _setup_auth).
    yield TestClient(app)


def _initialize_admin(client: TestClient):
    resp = client.post(
        "/api/v1/auth/initialize",
        json={"email": "admin@example.com", "password": "Str0ng!Pass99"},
    )
    assert resp.status_code == 201
    return resp


def _enable_authorization(monkeypatch, provider) -> None:
    config = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda c: provider)


# ── Route-level wiring ────────────────────────────────────────────────────


def test_me_lists_all_route_permissions_when_authorization_disabled(client):
    _initialize_admin(client)
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    assert res.json()["permissions"] == _ALL_PERMISSIONS


def test_me_reuses_middleware_resolved_permissions(client, monkeypatch):
    """One provider decision per registered permission — /me reads the
    AuthContext AuthMiddleware already stamped instead of re-resolving."""
    denied = {Permissions.THREADS_DELETE, Permissions.RUNS_CANCEL}
    provider = _RecordingProvider(denied=denied)
    _enable_authorization(monkeypatch, provider)
    _initialize_admin(client)

    res = client.get("/api/v1/auth/me")

    assert res.status_code == 200
    assert res.json()["permissions"] == [p for p in _ALL_PERMISSIONS if p not in denied]
    assert len(provider.requests) == len(_ALL_PERMISSIONS)


def test_initialize_response_leaves_permissions_unresolved(client):
    """Credential-creation responses do not resolve permissions (None), so
    they never advertise a misleading empty grant set."""
    resp = _initialize_admin(client)
    assert resp.json()["permissions"] is None


def test_auth_disabled_me_includes_default_admin_permissions(monkeypatch, _setup_auth, tmp_path):
    from app.gateway.app import create_app
    from app.gateway.auth.config import AuthConfig, set_auth_config

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    client = TestClient(create_app())

    res = client.get("/api/v1/auth/me")

    assert res.status_code == 200
    assert res.json()["permissions"] == _ALL_PERMISSIONS


# ── Middleware-less fallback ──────────────────────────────────────────────


def _fallback_request(user: SimpleNamespace, auth_source: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=auth_source),
        cookies={},
        headers={},
    )


def _stub_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="user-123",
        email="user@example.test",
        system_role="user",
        needs_setup=False,
        oauth_provider=None,
    )


@pytest.mark.asyncio
async def test_me_falls_back_to_fresh_resolution_without_middleware_context():
    """Direct handler invocation (no AuthMiddleware) resolves permissions the
    same way ``_authenticate`` would instead of reporting an empty grant."""
    from app.gateway.routers.auth import get_me

    response = await get_me(_fallback_request(_stub_user(), "session"))

    assert response.permissions == _ALL_PERMISSIONS


@pytest.mark.asyncio
async def test_me_fallback_mirrors_authenticate_internal_caller_semantics(monkeypatch):
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.routers.auth import get_me

    captured = {}

    async def fake_resolve(user, *, is_internal):
        captured["is_internal"] = is_internal
        return ["threads:read"]

    monkeypatch.setattr("app.gateway.authz.resolve_route_permissions", fake_resolve)

    response = await get_me(_fallback_request(_stub_user(), AUTH_SOURCE_INTERNAL))

    assert response.permissions == ["threads:read"]
    assert captured["is_internal"] is True
