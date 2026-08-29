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
from app.gateway.authz import require_cancel_permission_if
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers.auth import router as auth_router
from app.gateway.run_models import RunCreateRequest
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

    # Mirrors the real cancel-then-stream entrypoint (thread_runs.py
    # stream_existing_run): runs:read at the decorator, plus the real
    # conditional runs:cancel check the handler applies when `action` is set.
    from app.gateway.routers.thread_runs import require_cancel_permission_when_action

    @app.post("/api/threads/{thread_id}/runs/{run_id}/stream")
    @require_permission("runs", "read")
    async def cancel_then_stream(thread_id: str, run_id: str, request: Request, action: str | None = None):
        require_cancel_permission_when_action(request, action)
        return {"ok": True}

    # Mirrors the real run-creation entrypoints (thread_runs.py / runs.py):
    # runs:create at the decorator, plus the cancel-capability gate that
    # start_run applies to mutating multitask strategies. RunCreateRequest is
    # imported at module level — FastAPI resolves body annotations against
    # module globals under postponed annotation evaluation.
    @app.post("/api/threads/{thread_id}/runs")
    @require_permission("runs", "create")
    async def create_run(thread_id: str, body: RunCreateRequest, request: Request):
        require_cancel_permission_if(request, body.multitask_strategy != "reject")
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


def _create_pat(client: TestClient, *, name: str = "test-token", scopes: list[str] | None = None, user_id: str = "user-1", expires_in_days: int | None = None) -> dict:
    """Create a PAT via the management API with session auth + CSRF pair."""
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client, user_id=user_id)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    payload = {"name": name, "scopes": scopes or ["runs:read", "threads:read"]}
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


def test_empty_authorization_header_is_present_and_dies_at_auth_not_csrf(client):
    _session_cookie(client)
    response = client.post("/api/threads/t1/runs/stream", headers={"Authorization": ""})
    # An explicitly empty header is present-but-invalid: the same 401 from
    # AuthMiddleware as any other invalid credential, never a CSRF 403.
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


def test_create_rejects_whitespace_only_name(client):
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    for name in (" ", "\t\n"):
        response = client.post("/api/v1/auth/pats", json={"name": name, "scopes": ["runs:read"]}, headers={CSRF_HEADER_NAME: csrf})
        # Rejected by request validation (422) before token generation.
        assert response.status_code == 422, name
        assert "non-whitespace" in response.text


def test_create_trims_surrounding_whitespace_in_name(client):
    created = _create_pat(client, name="  ci bot  ")
    assert created["name"] == "ci bot"


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


def test_pat_policy_does_not_pre_authorize_unimplemented_methods():
    """Route-policy regression (#5041 review): the allowlist must not admit
    methods the router does not implement. The Gateway has no GET collection
    route for /api/threads — pre-authorizing it would make a future GET
    collection route PAT-reachable without an explicit policy change."""
    from app.gateway.auth.pat import is_pat_allowed_route

    assert is_pat_allowed_route("POST", "/api/threads") is True
    assert is_pat_allowed_route("GET", "/api/threads") is False


def test_pat_runs_policy_admits_exactly_the_mounted_routes():
    """The runs subtree is enumerated, not wildcarded: every GET/POST route
    the thread_runs router actually implements is admitted (derived from the
    mounted router, not a hand-maintained list), routes in this router
    outside the runs subtree stay denied, and representative unimplemented
    neighbors — including the POST-only collection names on GET — are
    default-denied. A new route under /runs fails here until explicitly
    allowlisted; a removed one leaves a dead rule visible."""
    from fastapi.routing import APIRoute

    from app.gateway.auth.pat import is_pat_allowed_route
    from app.gateway.routers.thread_runs import router

    def concrete(path: str) -> str:
        return path.replace("{thread_id}", "t1").replace("{run_id}", "r1")

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        path = concrete(route.path)
        under_runs = route.path.startswith("/api/threads/{thread_id}/runs")
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            admitted = is_pat_allowed_route(method, path)
            if under_runs:
                assert admitted, f"{method} {path} is implemented but PAT-denied"
            else:
                # /messages, /messages/page, /token-usage sit outside the runs
                # subtree and are PAT-denied pending the polling-surface
                # decision — pinned here so widening it is a conscious edit.
                assert not admitted, f"{method} {path} is outside the PAT policy"

    for method, path in [
        ("GET", "/api/threads/t1/runs/stream"),
        ("GET", "/api/threads/t1/runs/wait"),
        ("GET", "/api/threads/t1/runs/regenerate"),
        ("GET", "/api/threads/t1/runs/edit-regenerate"),
        ("POST", "/api/threads/t1/runs/r1/messages"),
        ("DELETE", "/api/threads/t1/runs/r1"),
        ("POST", "/api/threads/t1/runs/summary"),
        ("GET", "/api/threads/t1/runs/r1/transfer"),
    ]:
        assert not is_pat_allowed_route(method, path), f"{method} {path} is not implemented and must stay denied"


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


def test_runs_read_only_pat_cannot_cancel_then_stream(client):
    """Review follow-up: cancel-then-stream (`?action=interrupt|rollback`) must
    require runs:cancel even though the route decorator gates at runs:read —
    otherwise a read-only PAT bypasses the separate cancel scope."""
    read_only = _create_pat(client, scopes=["runs:read"])
    client.cookies.clear()

    denied = client.post(
        "/api/threads/t1/runs/run-1/stream?action=interrupt",
        headers={"Authorization": f"Bearer {read_only['token']}"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Permission denied: runs:cancel"

    # The same route without an action is a plain stream join: runs:read is
    # sufficient there.
    join = client.post(
        "/api/threads/t1/runs/run-1/stream",
        headers={"Authorization": f"Bearer {read_only['token']}"},
    )
    assert join.status_code == 200

    cancel_scope = _create_pat(client, scopes=["runs:read", "runs:cancel"])
    client.cookies.clear()
    allowed = client.post(
        "/api/threads/t1/runs/run-1/stream?action=rollback",
        headers={"Authorization": f"Bearer {cancel_scope['token']}"},
    )
    assert allowed.status_code == 200

    # Session callers keep the full permission set (with the CSRF pair their
    # cookie-authenticated POST requires).
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    session_allowed = client.post(
        "/api/threads/t1/runs/run-1/stream?action=interrupt",
        headers={CSRF_HEADER_NAME: csrf},
    )
    assert session_allowed.status_code == 200


def test_runs_create_only_pat_cannot_use_mutating_multitask_strategy(client):
    """Review round 5, P1-a: interrupt/rollback multitask strategies terminate
    an already-active run — runs:cancel capability, not runs:create — so a
    create-only PAT must be denied; "reject" (the default) stays within
    runs:create and must keep working."""
    create_only = _create_pat(client, scopes=["runs:create"])
    client.cookies.clear()

    for strategy in ("interrupt", "rollback"):
        denied = client.post(
            "/api/threads/t1/runs",
            headers={"Authorization": f"Bearer {create_only['token']}"},
            json={"multitask_strategy": strategy},
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"] == "Permission denied: runs:cancel"

    # "reject" — explicitly and as the omitted default — does not touch
    # existing runs and stays available to a create-only credential.
    for body in ({"multitask_strategy": "reject"}, {}):
        allowed = client.post(
            "/api/threads/t1/runs",
            headers={"Authorization": f"Bearer {create_only['token']}"},
            json=body,
        )
        assert allowed.status_code == 200

    cancel_scope = _create_pat(client, scopes=["runs:create", "runs:cancel"])
    client.cookies.clear()
    privileged = client.post(
        "/api/threads/t1/runs",
        headers={"Authorization": f"Bearer {cancel_scope['token']}"},
        json={"multitask_strategy": "interrupt"},
    )
    assert privileged.status_code == 200

    # Session callers keep the full permission set (with the CSRF pair their
    # cookie-authenticated POST requires).
    from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token

    _session_cookie(client)
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    session_allowed = client.post(
        "/api/threads/t1/runs",
        headers={CSRF_HEADER_NAME: csrf},
        json={"multitask_strategy": "interrupt"},
    )
    assert session_allowed.status_code == 200


def test_start_run_gates_mutating_strategies_at_the_choke_point():
    """The strategy gate lives inside start_run itself — the single choke point
    every run-creation path (all five HTTP entrypoints plus internal
    launchers) flows through — so no entry point can bypass it. Mirrored
    routes prove the middleware path; this anchor proves the choke point."""
    import inspect

    from app.gateway.services import start_run

    source = inspect.getsource(start_run)
    assert "require_cancel_permission_if" in source
    assert "multitask_strategy" in source


def test_start_run_gate_denies_create_only_credential_behaviorally():
    """Behavioral pin on the real start_run (the mirror route and source
    anchor above prove wiring, but this drives the production choke point
    itself): a create-only auth context gets 403 for a mutating strategy,
    and the gate never misfires on "reject" — with no cancel permission at
    all, the call proceeds past the gate (failing later on missing test
    wiring, never with a permission 403)."""
    from fastapi import HTTPException

    from app.gateway.authz import AuthContext
    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    def _request(permissions):
        return SimpleNamespace(state=SimpleNamespace(auth=AuthContext(user=SimpleNamespace(id="user-1"), permissions=permissions)))

    async def _denied():
        with pytest.raises(HTTPException) as exc:
            await start_run(RunCreateRequest(multitask_strategy="interrupt"), "t1", _request(["runs:create"]))
        return exc.value

    exc = asyncio.run(_denied())
    assert exc.status_code == 403
    assert exc.detail == "Permission denied: runs:cancel"

    async def _allowed_past_gate():
        try:
            await start_run(RunCreateRequest(), "t1", _request([]))
        except HTTPException as gate_misfire:
            pytest.fail(f"gate misfired on reject: {gate_misfire.status_code} {gate_misfire.detail}")
        except Exception:
            pass  # expected wiring failure past the gate — the gate let it through

    asyncio.run(_allowed_past_gate())


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
