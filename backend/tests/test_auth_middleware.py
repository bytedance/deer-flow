"""Tests for the global AuthMiddleware (fail-closed safety net)."""

import pytest
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware, _is_public
from app.gateway.csrf_middleware import CSRFMiddleware

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
        "/api/mcp/cache/reset",
        "/api/memory",
        "/api/skills",
        "/api/threads/123",
        "/api/threads/123/uploads",
        "/api/agents",
        "/api/channels",
        "/api/channels/providers",
        "/api/channels/slack/connect",
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
    from fastapi import FastAPI, Request

    from deerflow.runtime.user_context import get_effective_user_id

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        return {
            "id": str(user.id),
            "email": user.email,
            "system_role": user.system_role,
            "needs_setup": user.needs_setup,
        }

    @app.get("/api/v1/auth/setup-status")
    async def setup_status():
        return {"needs_setup": False}

    @app.get("/api/models")
    async def models_get():
        return {"models": []}

    @app.get("/api/whoami")
    async def whoami(request: Request):
        user = request.state.user
        return {
            "id": str(user.id),
            "email": getattr(user, "email", None),
            "system_role": getattr(user, "system_role", None),
            "context_user_id": get_effective_user_id(),
        }

    @app.get("/api/current-user-from-dep")
    async def current_user_from_dep(request: Request):
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        state_user = request.state.user
        return {
            "id": str(user.id),
            "state_id": str(state_user.id),
            "auth_source": request.state.auth_source,
            "context_user_id": get_effective_user_id(),
        }

    @app.put("/api/mcp/config")
    async def mcp_put():
        return {"ok": True}

    @app.post("/api/mcp/cache/reset")
    async def mcp_cache_reset():
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


def _make_auth_csrf_app():
    """Create a minimal app with production middleware ordering."""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/threads/abc/runs/stream")
    async def protected_mutation():
        return {"ok": True}

    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
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


def test_auth_disabled_allows_protected_path_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 200
    assert res.json() == {"models": []}


def test_auth_disabled_stamps_default_admin_user_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/whoami")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "context_user_id": "default",
    }


def test_auth_disabled_auth_me_reuses_middleware_user_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/v1/auth/me")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "needs_setup": False,
    }


def test_auth_disabled_does_not_clobber_valid_session_cookie(monkeypatch):
    from types import SimpleNamespace

    async def fake_current_user(request):
        return SimpleNamespace(
            id="session-user",
            email="session@test.local",
            system_role="user",
            needs_setup=False,
        )

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", fake_current_user)
    client = TestClient(_make_app())

    res = client.get("/api/whoami", cookies={"access_token": "valid-session"})

    assert res.status_code == 200
    assert res.json() == {
        "id": "session-user",
        "email": "session@test.local",
        "system_role": "user",
        "context_user_id": "session-user",
    }


def test_auth_disabled_does_not_clobber_internal_auth_identity(monkeypatch):
    from app.gateway.internal_auth import create_internal_auth_headers
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get(
        "/api/current-user-from-dep",
        headers=create_internal_auth_headers(),
    )

    assert res.status_code == 200
    assert res.json() == {
        "id": DEFAULT_USER_ID,
        "state_id": DEFAULT_USER_ID,
        "auth_source": "internal",
        "context_user_id": DEFAULT_USER_ID,
    }


def test_auth_disabled_skips_csrf_for_state_changing_requests(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_auth_csrf_app())

    res = client.post("/api/threads/abc/runs/stream")

    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_auth_disabled_is_ignored_in_explicit_production_env(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_ENV", "production")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 401


def test_auth_disabled_startup_warning_when_effective(monkeypatch, caplog):
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" in caplog.text
    assert "default" in caplog.text


def test_auth_disabled_startup_warning_suppressed_in_explicit_production_env(monkeypatch, caplog):
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" not in caplog.text


def test_protected_path_with_junk_cookie_rejected(client):
    """Junk cookie → 401. Middleware strictly validates the JWT now
    (AUTH_TEST_PLAN test 7.5.8); it no longer silently passes bad
    tokens through to the route handler."""
    client.cookies.set("access_token", "some-token")
    res = client.get("/api/models")
    assert res.status_code == 401


def test_protected_post_no_cookie_returns_401(client):
    res = client.post("/api/threads/abc/runs/stream")
    assert res.status_code == 401


def test_mcp_cache_reset_post_no_cookie_returns_401(client):
    res = client.post("/api/mcp/cache/reset")
    assert res.status_code == 401


def test_protected_post_with_internal_auth_header_passes():
    from app.gateway.internal_auth import create_internal_auth_headers

    app = _make_app()
    client = TestClient(app)

    res = client.post(
        "/api/threads/abc/runs/stream",
        headers=create_internal_auth_headers(),
    )

    assert res.status_code == 200


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
