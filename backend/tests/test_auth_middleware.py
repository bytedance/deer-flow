"""Tests for the global AuthMiddleware (fail-closed safety net)."""

from types import SimpleNamespace
from uuid import uuid4

import anyio
import pytest
from starlette.testclient import TestClient

from app.gateway.auth.config import AuthConfig, TrustedHeaderProviderConfig, set_auth_config
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware, _is_public
from deerflow.runtime.user_context import get_current_user

# ── _is_public unit tests ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/health/",
        "/docs",
        "/docs/",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
    ],
)
def test_public_paths(path: str):
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models",
        "/api/mcp/config",
        "/api/memory",
        "/api/skills",
        "/api/threads/123",
        "/api/threads/123/uploads",
        "/api/agents",
        "/api/channels",
        "/api/runs/stream",
        "/api/threads/123/runs",
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
    ],
)
def test_protected_paths(path: str):
    assert _is_public(path) is False


# ── Trailing slash / normalization edge cases ─────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login/local/",
        "/api/v1/auth/register/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/setup-status/",
    ],
)
def test_public_auth_paths_with_trailing_slash(path: str):
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models/",
        "/api/v1/auth/me/",
        "/api/v1/auth/change-password/",
    ],
)
def test_protected_paths_with_trailing_slash(path: str):
    assert _is_public(path) is False


def test_unknown_api_path_is_protected():
    """Fail-closed: any new /api/* path is protected by default."""
    assert _is_public("/api/new-feature") is False
    assert _is_public("/api/v2/something") is False
    assert _is_public("/api/v1/auth/new-endpoint") is False


# ── Middleware integration tests ──────────────────────────────────────────


def _make_app():
    """Create a minimal FastAPI app with AuthMiddleware for testing."""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me():
        return {"id": "1", "email": "test@test.com"}

    @app.get("/api/v1/auth/setup-status")
    async def setup_status():
        return {"needs_setup": False}

    @app.get("/api/models")
    async def models_get():
        return {"models": []}

    @app.get("/api/context-user")
    async def context_user():
        user = get_current_user()
        return {"user_id": str(user.id) if user is not None else None}

    @app.put("/api/mcp/config")
    async def mcp_put():
        return {"ok": True}

    @app.delete("/api/threads/abc")
    async def thread_delete():
        return {"ok": True}

    @app.patch("/api/threads/abc")
    async def thread_patch():
        return {"ok": True}

    @app.post("/api/threads/abc/runs/stream")
    async def stream():
        return {"ok": True}

    @app.get("/api/future-endpoint")
    async def future():
        return {"ok": True}

    return app


def _inject_client_host(app, host: str):
    @app.middleware("http")
    async def _set_client_host(request, call_next):
        request.scope["client"] = (host, 80)
        return await call_next(request)


@pytest.fixture
def client():
    return TestClient(_make_app())


def test_public_path_no_cookie(client):
    res = client.get("/health")
    assert res.status_code == 200


def test_public_auth_path_no_cookie(client):
    """Public auth endpoints (login/register) pass without cookie."""
    res = client.get("/api/v1/auth/setup-status")
    assert res.status_code == 200


def test_protected_auth_path_no_cookie(client):
    """/auth/me requires cookie even though it's under /api/v1/auth/."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_protected_path_no_cookie_returns_401(client):
    res = client.get("/api/models")
    assert res.status_code == 401
    body = res.json()
    assert body["detail"]["code"] == "not_authenticated"


def test_protected_path_with_junk_cookie_rejected(client):
    """Junk cookie → 401. Middleware strictly validates the JWT now
    (AUTH_TEST_PLAN test 7.5.8); it no longer silently passes bad
    tokens through to the route handler."""
    res = client.get("/api/models", cookies={"access_token": "some-token"})
    assert res.status_code == 401


def test_protected_post_no_cookie_returns_401(client):
    res = client.post("/api/threads/abc/runs/stream")
    assert res.status_code == 401


# ── Method matrix: PUT/DELETE/PATCH also protected ────────────────────────


def test_protected_put_no_cookie(client):
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_protected_delete_no_cookie(client):
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


def test_protected_patch_no_cookie(client):
    res = client.patch("/api/threads/abc")
    assert res.status_code == 401


def test_put_with_junk_cookie_rejected(client):
    """Junk cookie on PUT → 401 (strict JWT validation in middleware)."""
    client.cookies.set("access_token", "tok")
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_delete_with_junk_cookie_rejected(client):
    """Junk cookie on DELETE → 401 (strict JWT validation in middleware)."""
    client.cookies.set("access_token", "tok")
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


# ── Fail-closed: unknown future endpoints ─────────────────────────────────


def test_unknown_endpoint_no_cookie_returns_401(client):
    """Any new /api/* endpoint is blocked by default without cookie."""
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401


def test_unknown_endpoint_with_junk_cookie_rejected(client):
    """New endpoints are also protected by strict JWT validation."""
    client.cookies.set("access_token", "tok")
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401


def test_trusted_header_auth_allows_protected_path_without_cookie(monkeypatch):
    app = _make_app()
    _inject_client_host(app, "10.1.2.3")

    user = User(id=uuid4(), email="trusted@test.com", password_hash="hash")
    cfg = AuthConfig(
        jwt_secret="test-secret-key-123",
        provider="trusted_header",
        trusted_header=TrustedHeaderProviderConfig(
            enabled=True,
            trusted_networks=["10.0.0.0/8"],
            user_id_header="X-Forwarded-User",
        ),
    )
    set_auth_config(cfg)

    class _Repo:
        async def get_user_by_id(self, user_id: str):
            return user if user_id == str(user.id) else None

    async def _fake_current_user(_request):  # should not be reached in this test
        raise AssertionError("cookie auth path should not run when trusted header succeeds")

    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo())
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _fake_current_user)

    with TestClient(app) as client:
        response = client.get("/api/models", headers={"X-Forwarded-User": str(user.id)})

    assert response.status_code == 200


def test_trusted_header_auth_falls_back_to_cookie_path_when_provider_returns_none(monkeypatch):
    app = _make_app()
    _inject_client_host(app, "10.1.2.3")

    cfg = AuthConfig(
        jwt_secret="test-secret-key-123",
        provider="trusted_header",
        trusted_header=TrustedHeaderProviderConfig(
            enabled=True,
            trusted_networks=["10.0.0.0/8"],
            user_id_header="X-Forwarded-User",
        ),
    )
    set_auth_config(cfg)

    class _Repo:
        async def get_user_by_id(self, user_id: str):
            return None

    async def _fake_current_user(_request):
        raise AssertionError("cookie auth fallback should be attempted and fail before route handler")

    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo())
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _fake_current_user)

    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"X-Forwarded-User": "missing-user"},
        )

    assert response.status_code == 401


def test_trusted_header_auth_context_is_cleaned_after_request(monkeypatch):
    app = _make_app()
    _inject_client_host(app, "10.1.2.3")

    user = User(id=uuid4(), email="trusted@test.com", password_hash="hash")
    cfg = AuthConfig(
        jwt_secret="test-secret-key-123",
        provider="trusted_header",
        trusted_header=TrustedHeaderProviderConfig(
            enabled=True,
            trusted_networks=["10.0.0.0/8"],
            user_id_header="X-Forwarded-User",
        ),
    )
    set_auth_config(cfg)

    class _Repo:
        async def get_user_by_id(self, user_id: str):
            return user if user_id == str(user.id) else None

    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo())

    with TestClient(app) as client:
        response = client.get("/api/context-user", headers={"X-Forwarded-User": str(user.id)})
        assert response.status_code == 200
        assert response.json()["user_id"] == str(user.id)

    current_user = get_current_user()
    assert current_user is None or str(current_user.id) != str(user.id)


def test_trusted_header_auth_concurrent_requests_isolate_context(monkeypatch):
    app = _make_app()
    _inject_client_host(app, "10.1.2.3")

    user_a = User(id=uuid4(), email="a@test.com", password_hash="hash")
    user_b = User(id=uuid4(), email="b@test.com", password_hash="hash")
    cfg = AuthConfig(
        jwt_secret="test-secret-key-123",
        provider="trusted_header",
        trusted_header=TrustedHeaderProviderConfig(
            enabled=True,
            trusted_networks=["10.0.0.0/8"],
            user_id_header="X-Forwarded-User",
        ),
    )
    set_auth_config(cfg)

    class _Repo:
        async def get_user_by_id(self, user_id: str):
            if user_id == str(user_a.id):
                return user_a
            if user_id == str(user_b.id):
                return user_b
            return None

    monkeypatch.setattr("app.gateway.deps.get_user_repository", lambda: _Repo())

    with TestClient(app) as client:
        async def _call(uid: str):
            return await anyio.to_thread.run_sync(
                lambda: client.get(
                    "/api/context-user",
                    headers={"X-Forwarded-User": uid},
                ).json()["user_id"]
            )

        async def _run():
            async with anyio.create_task_group() as tg:
                results = {}

                async def _store(name: str, uid: str):
                    results[name] = await _call(uid)

                tg.start_soon(_store, "a", str(user_a.id))
                tg.start_soon(_store, "b", str(user_b.id))
            return results

        results = anyio.run(_run)

    assert results["a"] == str(user_a.id)
    assert results["b"] == str(user_b.id)
