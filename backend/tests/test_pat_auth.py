"""Integration tests for PAT authentication (#4849).

Covers credential precedence in AuthMiddleware, the CSRF boundary for
Bearer-authenticated requests, scope intersection, PAT management routes,
and the self-protection rules (a PAT may not manage PATs or auth state).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

import deerflow.persistence.models  # noqa: F401  (register every table)
from app.gateway.auth_disabled import AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers.auth import router as auth_router
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.personal_access_tokens import PersonalAccessTokenRepository

TEST_JWT_SECRET = "test-pat-jwt-secret-0123456789abcdef"


class _FakeProvider:
    """Minimal LocalAuthProvider stand-in: resolves users by id."""

    def __init__(self, *users) -> None:
        self._users = {str(user.id): user for user in users}

    async def get_user(self, user_id: str):
        return self._users.get(str(user_id))


def _fake_user(user_id: str = "user-1", *, system_role: str = "user"):
    return SimpleNamespace(
        id=user_id,
        email=f"{user_id}@example.com",
        system_role=system_role,
        needs_setup=False,
        token_version=0,
        oauth_provider=None,
        password_hash=None,
    )


@pytest.fixture(autouse=True)
def _default_route_authorization_config(monkeypatch):
    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: AuthorizationConfig(),
    )
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    from app.gateway.auth.config import AuthConfig, set_auth_config

    set_auth_config(AuthConfig(jwt_secret=TEST_JWT_SECRET, token_expiry_days=7))


def _make_pat_app(with_pat_repo: bool = True):
    app = FastAPI()
    # Production order: AuthMiddleware added first (inner), CSRF last (outer).
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)

    @app.get("/api/threads/whoami")
    async def whoami(request: Request):
        return {"user_id": str(request.state.user.id), "auth_source": request.state.auth_source}

    @app.get("/api/admin-check")
    async def admin_check(request: Request):
        from app.gateway.deps import is_admin_user

        return {"is_admin": await is_admin_user(request)}

    @app.post("/api/threads/{thread_id}/runs/stream")
    async def run_stream(request: Request):
        return {"ok": True, "permissions": list(request.state.auth.permissions)}

    @app.delete("/api/memory")
    async def memory_delete(request: Request):
        return {"deleted": True}

    @app.delete("/api/threads/{thread_id}")
    async def thread_delete(request: Request):
        return {"deleted": True}

    # Mirrors the real stateless run entrypoint (routers/runs.py), including
    # the @require_permission decorator, so scope enforcement is exercised
    # end-to-end through the middleware's permission intersection.
    from app.gateway.authz import require_permission

    @app.post("/api/runs/stream")
    @require_permission("runs", "create")
    async def stateless_run_stream(request: Request):
        return {"ok": True}

    return app


@pytest.fixture
def pat_env(tmp_path, monkeypatch):
    """Engine + PAT repo + patched user provider; returns (client, repo)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pats.db", poolclass=NullPool)
    asyncio.run(_create_tables(engine))
    repo = PersonalAccessTokenRepository(async_sessionmaker(engine, expire_on_commit=False))

    fake_provider = _FakeProvider(_fake_user("user-1"), _fake_user("user-2"), _fake_user("admin-1", system_role="admin"))
    monkeypatch.setattr("app.gateway.deps.get_local_provider", lambda: fake_provider)
    monkeypatch.setattr("app.gateway.routers.auth.get_local_provider", lambda: fake_provider)

    app = _make_pat_app()
    app.state.pat_repo = repo
    return app, repo, engine


async def _create_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def client(pat_env):
    app, repo, engine = pat_env
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def _session_cookie(client: TestClient, user_id: str = "user-1", token_version: int = 0) -> str:
    from app.gateway.auth import create_access_token

    token = create_access_token(user_id, token_version=token_version)
    client.cookies.set("access_token", token)
    return token


def _create_pat(client: TestClient, *, scopes: list[str] | None = None, user_id: str = "user-1", expires_in_days: int | None = None) -> dict:
    """Create a PAT via the management API with session auth + CSRF pair."""
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client, user_id=user_id)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    payload = {"name": "test-token", "scopes": scopes or ["runs:read", "threads:read"]}
    if expires_in_days is not None:
        payload["expires_in_days"] = expires_in_days
    response = client.post(
        "/api/v1/auth/pats",
        json=payload,
        headers={CSRF_HEADER_NAME: csrf},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["token"].startswith("dfp_")
    return payload


# ── Middleware precedence (#4849 point 3) ─────────────────────────────────


def test_valid_pat_authenticates_without_cookie(client):
    created = _create_pat(client)
    client.cookies.clear()
    response = client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1", "auth_source": AUTH_SOURCE_PAT}


def test_invalid_bearer_never_falls_back_to_session_cookie(client):
    _session_cookie(client)  # victim session is present and valid
    response = client.get("/api/threads/whoami", headers={"Authorization": "Bearer dfp_not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_non_bearer_authorization_scheme_is_rejected(client):
    _session_cookie(client)
    response = client.get("/api/threads/whoami", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


def test_valid_pat_takes_precedence_over_session_cookie(client):
    created = _create_pat(client)  # sets a session cookie too
    response = client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 200
    assert response.json()["auth_source"] == AUTH_SOURCE_PAT


def test_no_bearer_header_keeps_session_behavior(client):
    _session_cookie(client)
    response = client.get("/api/threads/whoami")
    assert response.status_code == 200
    assert response.json()["auth_source"] == AUTH_SOURCE_SESSION


def test_revoked_pat_is_rejected_immediately(client):
    created = _create_pat(client)
    delete = client.delete(f"/api/v1/auth/pats/{created['id']}", headers={"X-CSRF-Token": client.cookies.get("csrf_token")})
    assert delete.status_code == 200, delete.text

    client.cookies.clear()
    response = client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 401


def test_pat_with_unresolvable_user_is_rejected(client, pat_env):
    app, repo, _engine = pat_env
    # Row owned by a user the provider cannot resolve (deleted user).
    from app.gateway.auth.pat import generate_pat_token, pat_token_digest

    token = generate_pat_token()
    asyncio.run(repo.create(user_id="user-deleted", name="orphan", scopes=["runs:read"], token_digest=pat_token_digest(token)))
    client.cookies.clear()
    response = client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_pat_without_durable_store_is_rejected():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/threads/whoami")
    async def whoami(request):  # pragma: no cover - never reached
        return {}

    with TestClient(app) as bare_client:
        response = bare_client.get("/api/threads/whoami", headers={"Authorization": "Bearer dfp_whatever"})
    assert response.status_code == 401


# ── Scope intersection ────────────────────────────────────────────────────


def test_pat_scopes_intersect_user_permissions(client):
    created = _create_pat(client, scopes=["runs:read"])
    client.cookies.clear()
    response = client.post("/api/threads/t1/runs/stream", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 200
    permissions = response.json()["permissions"]
    assert "runs:read" in permissions
    assert "runs:create" not in permissions
    assert "threads:read" not in permissions


# ── CSRF posture (#4849 point 4) ──────────────────────────────────────────


def test_bearer_request_skips_double_submit(client):
    created = _create_pat(client)
    client.cookies.clear()  # no csrf_token cookie, no X-CSRF-Token header
    response = client.post("/api/threads/t1/runs/stream", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 200


def test_garbage_bearer_riding_cookie_dies_at_auth_not_csrf(client):
    _session_cookie(client)
    response = client.post("/api/threads/t1/runs/stream", headers={"Authorization": "Bearer garbage"})
    # 401 from AuthMiddleware (invalid credential), not 403 from CSRF.
    assert response.status_code == 401


def test_auth_endpoint_origin_check_not_bypassed_by_bearer(client):
    response = client.post(
        "/api/v1/auth/login/local",
        json={"email": "a@b.c", "password": "whatever1!"},
        headers={"Origin": "https://evil.example", "Authorization": "Bearer dfp_garbage"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site auth request denied."


# ── Management routes + self-protection (#4849 point 6) ───────────────────


def test_create_returns_show_once_token_and_list_hides_it(client):
    created = _create_pat(client)
    listed = client.get("/api/v1/auth/pats")
    assert listed.status_code == 200
    entries = listed.json()
    assert [entry["id"] for entry in entries] == [created["id"]]
    assert "token" not in entries[0]
    assert "token_digest" not in entries[0]


def test_create_rejects_unknown_scope(client):
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    response = client.post("/api/v1/auth/pats", json={"name": "bad", "scopes": ["runs:write"]}, headers={CSRF_HEADER_NAME: csrf})
    assert response.status_code == 400
    assert "Unknown PAT scopes" in response.json()["detail"]


def test_revoke_is_scoped_to_owner(client):
    created = _create_pat(client, user_id="user-1")
    # user-2 tries to revoke user-1's token.
    _session_cookie(client, user_id="user-2")
    from app.gateway.csrf_middleware import CSRF_HEADER_NAME

    response = client.delete(f"/api/v1/auth/pats/{created['id']}", headers={CSRF_HEADER_NAME: client.cookies.get("csrf_token")})
    assert response.status_code == 404


def test_pat_cannot_manage_pats(client):
    created = _create_pat(client)
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {created['token']}"}
    assert client.get("/api/v1/auth/pats", headers=headers).status_code == 403
    assert client.post("/api/v1/auth/pats", json={"name": "child", "scopes": ["runs:read"]}, headers=headers).status_code == 403
    assert client.delete(f"/api/v1/auth/pats/{created['id']}", headers=headers).status_code == 403


def test_pat_cannot_change_password(client):
    created = _create_pat(client)
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "x", "new_password": "Whatever123!"},
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert response.status_code == 403
    # The default-deny route policy blocks the request at the middleware,
    # before the route-level session-only guard gets a chance; the 403 is the
    # security property either way.
    assert "pat" in response.json()["detail"].lower()


def test_successful_pat_auth_stamps_last_used(client, pat_env):
    _app, repo, _engine = pat_env
    created = _create_pat(client)
    client.cookies.clear()
    assert client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {created['token']}"}).status_code == 200

    records = asyncio.run(repo.list_for_user("user-1"))
    assert records[0]["last_used_at"] is not None


def test_expired_pat_rejected_at_middleware(client, pat_env):
    _app, repo, _engine = pat_env
    from app.gateway.auth.pat import generate_pat_token, pat_token_digest

    token = generate_pat_token()
    asyncio.run(
        repo.create(
            user_id="user-1",
            name="already-expired",
            scopes=["runs:read"],
            token_digest=pat_token_digest(token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    client.cookies.clear()
    response = client.get("/api/threads/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_create_with_expiry_returns_expires_at(client):
    created = _create_pat(client, expires_in_days=30)
    assert created["expires_at"] is not None


def test_pat_never_carries_admin_capability_even_for_admin_owner(client):
    created = _create_pat(client, user_id="admin-1", scopes=["runs:read"])
    client.cookies.clear()
    # The route-level default-deny policy blocks the PAT before the route
    # runs; the is_admin_user guard inside it remains as defense in depth
    # for compositions without the middleware.
    response = client.get("/api/admin-check", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 403

    # Control: the same admin over a session cookie keeps admin capability.
    _session_cookie(client, user_id="admin-1")
    control = client.get("/api/admin-check")
    assert control.status_code == 200
    assert control.json() == {"is_admin": True}


def test_pat_default_denied_on_route_outside_pat_policy(client):
    """P1 regression (#5041 review): a PAT holding every scope must not reach
    destructive routes that have no PAT policy — scope intersection only
    constrains @require_permission routes, so undecorated mutation routes
    would otherwise accept a runs:read-only token."""
    created = _create_pat(client, scopes=["threads:read", "threads:write", "threads:delete", "runs:create", "runs:read", "runs:cancel"])
    client.cookies.clear()
    response = client.delete("/api/memory", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 403
    assert "PAT" in response.json()["detail"]


def test_session_cookie_reaches_route_that_denies_pat(client):
    """The default-deny is PAT-specific: the same route stays open to the
    owning user's session cookie (PATs narrow, never widen, and never
    restrict the interactive path)."""
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client, user_id="user-1")
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    response = client.delete("/api/memory", headers={CSRF_HEADER_NAME: csrf})
    assert response.status_code == 200
    assert response.json() == {"deleted": True}


def test_pat_policy_allows_thread_lifecycle_routes(client):
    created = _create_pat(client, scopes=["threads:delete"])
    client.cookies.clear()
    response = client.delete("/api/threads/t1", headers={"Authorization": f"Bearer {created['token']}"})
    assert response.status_code == 200
    assert response.json() == {"deleted": True}


def test_pat_scopes_enforced_on_stateless_run_entry(client):
    """Follow-up to the review's P1-1: the stateless run entrypoints now
    carry @require_permission("runs", "create"), so a threads:read-only PAT
    cannot start runs even though the route sits inside the PAT allowlist."""
    read_only = _create_pat(client, scopes=["threads:read"])
    client.cookies.clear()
    denied = client.post("/api/runs/stream", headers={"Authorization": f"Bearer {read_only['token']}"})
    assert denied.status_code == 403

    create_scope = _create_pat(client, scopes=["runs:create"])
    client.cookies.clear()
    allowed = client.post("/api/runs/stream", headers={"Authorization": f"Bearer {create_scope['token']}"})
    assert allowed.status_code == 200


def test_auth_disabled_mode_ignores_bearer_header(monkeypatch, tmp_path):
    """DEER_FLOW_AUTH_DISABLED is an operator override of all authentication.

    A stray Authorization header (e.g. added by a proxy in front of an E2E
    sandbox) must not turn into a 401 in that mode.
    """
    monkeypatch.setattr("app.gateway.auth_middleware.is_auth_disabled", lambda: True)
    app = _make_pat_app()
    with TestClient(app) as disabled_client:
        response = disabled_client.get("/api/threads/whoami", headers={"Authorization": "Bearer dfp_garbage"})
    assert response.status_code == 200
    assert response.json()["auth_source"] == "auth_disabled"
