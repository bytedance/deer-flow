"""Tests for the POST /api/v1/auth/initialize endpoint.

Covers: first-boot admin creation, rejection when system already
initialized, password strength validation,
and public accessibility (no auth cookie required).
"""

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-initialize-admin-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config

_TEST_SECRET = "test-secret-key-initialize-admin-min-32"


@pytest.fixture(autouse=True)
def _setup_auth(tmp_path):
    """Fresh SQLite engine + auth config per test."""
    from app.gateway import deps
    from app.gateway.routers.auth import _SETUP_STATUS_CACHE, _SETUP_STATUS_INFLIGHT
    from deerflow.persistence.engine import close_engine, init_engine

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    url = f"sqlite+aiosqlite:///{tmp_path}/init_admin.db"
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


@pytest.fixture()
def client(_setup_auth):
    from app.gateway.app import create_app
    from app.gateway.auth.config import AuthConfig, set_auth_config

    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    app = create_app()
    # Do NOT use TestClient as a context manager — that would trigger the
    # full lifespan which requires config.yaml. The auth endpoints work
    # without the lifespan (persistence engine is set up by _setup_auth).
    yield TestClient(app)


def _init_payload(**extra):
    """Build a valid /initialize payload."""
    return {
        "email": "admin@example.com",
        "password": "Str0ng!Pass99",
        **extra,
    }


# ── Happy path ────────────────────────────────────────────────────────────


def test_initialize_creates_admin_and_sets_cookie(client):
    """POST /initialize when no admin exists → 201, session cookie set."""
    resp = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "admin@example.com"
    assert data["system_role"] == "admin"
    assert "access_token" in resp.cookies


def test_initialize_needs_setup_false(client):
    """Newly created admin via /initialize has needs_setup=False."""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["needs_setup"] is False


# ── Rejection when already initialized ───────────────────────────────────


def test_initialize_rejected_when_admin_exists(client):
    """Second call to /initialize after admin exists → 409 system_already_initialized."""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    resp2 = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "email": "other@example.com"},
    )
    assert resp2.status_code == 409
    body = resp2.json()
    assert body["detail"]["code"] == "system_already_initialized"


def test_initialize_register_does_not_block_initialization(client):
    """/register creating a user before /initialize doesn't block admin creation."""
    # Register a regular user first
    client.post("/api/v1/auth/register", json={"email": "regular@example.com", "password": "Tr0ub4dor3a"})
    # /initialize should still succeed (checks admin_count, not total user_count)
    resp = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert resp.status_code == 201
    assert resp.json()["system_role"] == "admin"


# ── Endpoint is public (no cookie required) ───────────────────────────────


def test_initialize_accessible_without_cookie(client):
    """No access_token cookie needed for /initialize."""
    resp = client.post(
        "/api/v1/auth/initialize",
        json=_init_payload(),
        cookies={},
    )
    assert resp.status_code == 201


# ── Password validation ───────────────────────────────────────────────────


def test_initialize_rejects_short_password(client):
    """Password shorter than 8 chars → 422."""
    resp = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "password": "short"},
    )
    assert resp.status_code == 422


def test_initialize_rejects_common_password(client):
    """Common password → 422."""
    resp = client.post(
        "/api/v1/auth/initialize",
        json={**_init_payload(), "password": "password123"},
    )
    assert resp.status_code == 422


# ── setup-status reflects initialization ─────────────────────────────────


def test_setup_status_before_initialization(client):
    """setup-status returns needs_setup=True before /initialize is called."""
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is True


def test_setup_status_after_initialization(client):
    """setup-status returns needs_setup=False after /initialize succeeds."""
    client.post("/api/v1/auth/initialize", json=_init_payload())
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is False


def test_setup_status_false_when_only_regular_user_exists(client):
    """setup-status returns needs_setup=True even when regular users exist (no admin)."""
    client.post("/api/v1/auth/register", json={"email": "regular@example.com", "password": "Tr0ub4dor3a"})
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needs_setup"] is True


def test_setup_status_returns_cached_result_on_rapid_calls(client):
    """Rapid /setup-status calls return the cached result (200) instead of 429."""
    client.post("/api/v1/auth/initialize", json=_init_payload())

    # First call succeeds and computes the result.
    resp1 = client.get("/api/v1/auth/setup-status")
    assert resp1.status_code == 200

    # Immediate second call returns cached result, not 429.
    resp2 = client.get("/api/v1/auth/setup-status")
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()
    assert resp2.json()["needs_setup"] is False


def test_setup_status_does_not_return_stale_true_after_initialize(client):
    """A pre-initialize setup-status response should not stay cached as True."""
    before = client.get("/api/v1/auth/setup-status")
    assert before.status_code == 200
    assert before.json()["needs_setup"] is True

    init = client.post("/api/v1/auth/initialize", json=_init_payload())
    assert init.status_code == 201

    after = client.get("/api/v1/auth/setup-status")
    assert after.status_code == 200
    assert after.json()["needs_setup"] is False


@pytest.mark.asyncio
async def test_setup_status_single_flight_per_ip(monkeypatch):
    """Concurrent requests from same IP share one in-flight DB query."""
    from starlette.requests import Request

    from app.gateway.routers.auth import (
        _SETUP_STATUS_CACHE,
        _SETUP_STATUS_INFLIGHT,
        setup_status,
    )

    class _Provider:
        def __init__(self):
            self.calls = 0

        async def count_admin_users(self):
            self.calls += 1
            await asyncio.sleep(0.05)
            return 0

    provider = _Provider()
    monkeypatch.setattr("app.gateway.routers.auth.get_local_provider", lambda: provider)
    _SETUP_STATUS_CACHE.clear()
    _SETUP_STATUS_INFLIGHT.clear()

    def _request() -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/auth/setup-status",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
        )

    results = await asyncio.gather(
        setup_status(_request()),
        setup_status(_request()),
        setup_status(_request()),
    )

    assert all(result["needs_setup"] is True for result in results)
    assert provider.calls == 1
