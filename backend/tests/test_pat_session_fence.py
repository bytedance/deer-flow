"""End-to-end session-identity fence on the PAT management routes (#5096).

A cross-tab account switch replaces the shared session cookie immediately
while a backgrounded tab's React auth state still names the previous
account — and remount, reconnect, or invalidation can fire a PAT request
inside that window. List would fetch and cache the wrong account's token
summaries under the stale identity's key, and create/revoke would act on
the wrong account. The fence makes the backend reject any declared
identity that disagrees with the authenticated session (user id plus the
session token's generation) before any read or side effect.

Browser clients declare their identity via the ``X-DF-Session`` header
(``<user_id>:<generation>``, generation taken from ``/me``); clients that
send no declaration (the README-documented curl flows) are exempt — they
hold exactly one credential by construction.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

import deerflow.persistence.models  # noqa: F401  (register every table)
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRFMiddleware, generate_csrf_token
from app.gateway.routers.auth import router as auth_router
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.personal_access_tokens import PersonalAccessTokenRepository

TEST_JWT_SECRET = "test-session-fence-jwt-secret-0123456789abcdef"

SESSION_HEADER = "X-DF-Session"


class _FakeProvider:
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Production middleware order around the real auth router + PAT repo."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fence.db", poolclass=NullPool)
    asyncio.run(_create_tables(engine))
    repo = PersonalAccessTokenRepository(async_sessionmaker(engine, expire_on_commit=False))

    fake_provider = _FakeProvider(_fake_user("user-1"), _fake_user("user-2"))
    monkeypatch.setattr("app.gateway.deps.get_local_provider", lambda: fake_provider)
    monkeypatch.setattr("app.gateway.routers.auth.get_local_provider", lambda: fake_provider)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    app.state.pat_repo = repo

    with TestClient(app) as test_client:
        test_client._repo = repo  # type: ignore[attr-defined]
        test_client._engine = engine  # type: ignore[attr-defined]
        yield test_client
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _session_cookie(client: TestClient, user_id: str) -> None:
    from app.gateway.auth import create_access_token

    client.cookies.set("access_token", create_access_token(user_id, token_version=0))


def _csrf_pair(client: TestClient) -> dict[str, str]:
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    return {CSRF_HEADER_NAME: csrf}


def _me_generation(client: TestClient) -> int:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    generation = response.json()["session_generation"]
    assert isinstance(generation, int), response.text
    return generation


# ── /me reports the generation the fence compares against ─────────────────


def test_me_reports_the_session_generation(client):
    _session_cookie(client, "user-2")
    generation = _me_generation(client)

    # The generation is the session token's iat: a different login mints a
    # different generation, so a stale React identity (old user id, old
    # generation) can never satisfy the fence for the new session.
    import time

    time.sleep(1.1)  # iat has second resolution
    _session_cookie(client, "user-1")
    assert _me_generation(client) != generation


# ── List: wrong declared identity never returns the other account's rows ──


def test_list_rejects_a_declared_identity_the_session_does_not_hold(client):
    _session_cookie(client, "user-2")
    generation = _me_generation(client)

    # The race's exact shape: React still believes account user-1.
    stale = client.get("/api/v1/auth/pats", headers={SESSION_HEADER: f"user-1:{generation}"})
    assert stale.status_code == 409, stale.text
    assert "Session identity changed" in stale.json()["detail"]

    # The correct declaration passes, and no declaration at all (curl flows)
    # keeps working.
    ok = client.get("/api/v1/auth/pats", headers={SESSION_HEADER: f"user-2:{generation}"})
    assert ok.status_code == 200, ok.text
    undeclared = client.get("/api/v1/auth/pats")
    assert undeclared.status_code == 200, undeclared.text


# ── Create: wrong declared identity mints nothing ──────────────────────────


def test_create_with_mismatched_identity_mints_nothing(client):
    _session_cookie(client, "user-2")
    generation = _me_generation(client)
    headers = {SESSION_HEADER: f"user-1:{generation}", **_csrf_pair(client)}

    denied = client.post(
        "/api/v1/auth/pats",
        json={"name": "wrong-account", "scopes": ["runs:read"]},
        headers=headers,
    )
    assert denied.status_code == 409, denied.text
    assert "Session identity changed" in denied.json()["detail"]

    repo = client._repo  # type: ignore[attr-defined]
    assert asyncio.run(repo.list_for_user("user-1")) == []
    assert asyncio.run(repo.list_for_user("user-2")) == []


# ── Revoke: wrong declared identity leaves the token active ────────────────


def test_revoke_with_mismatched_identity_leaves_token_active(client):
    _session_cookie(client, "user-2")
    generation = _me_generation(client)

    created = client.post(
        "/api/v1/auth/pats",
        json={"name": "fenced", "scopes": ["runs:read"]},
        headers={SESSION_HEADER: f"user-2:{generation}", **_csrf_pair(client)},
    )
    assert created.status_code == 201, created.text
    pat_id = created.json()["id"]

    denied = client.delete(
        f"/api/v1/auth/pats/{pat_id}",
        headers={SESSION_HEADER: f"user-1:{generation}", **_csrf_pair(client)},
    )
    assert denied.status_code == 409, denied.text

    listed = client.get("/api/v1/auth/pats", headers={SESSION_HEADER: f"user-2:{generation}"})
    assert [entry["id"] for entry in listed.json()] == [pat_id]
    assert listed.json()[0]["revoked_at"] is None


# ── A stale generation alone (same user, replaced session) is rejected ─────


def test_same_user_with_replaced_session_generation_is_rejected(client):
    _session_cookie(client, "user-1")
    stale_generation = _me_generation(client)

    import time

    time.sleep(1.1)  # the session is replaced by a fresh login of the same user
    _session_cookie(client, "user-1")
    fresh_generation = _me_generation(client)

    denied = client.get("/api/v1/auth/pats", headers={SESSION_HEADER: f"user-1:{stale_generation}"})
    assert denied.status_code == 409, denied.text
    ok = client.get("/api/v1/auth/pats", headers={SESSION_HEADER: f"user-1:{fresh_generation}"})
    assert ok.status_code == 200, ok.text
