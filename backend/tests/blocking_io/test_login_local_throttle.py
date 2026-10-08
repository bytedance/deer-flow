"""Regression anchors: the login throttle must not block the event loop.

``_login_throttle_policy`` resolves the live policy via ``get_app_config()``,
which stats and re-hashes ``config.yaml`` on every call. ``login_local`` is an
unauthenticated async endpoint, and every request from a recorded IP resolves
the policy — including an already-locked attacker flooding the endpoint on
the way to its 429. Both resolution points (the rate-limit check and the
failure recorder) offload via ``asyncio.to_thread``; if either regresses onto
the event loop, the strict Blockbuster gate raises ``BlockingError``.

The counter itself lives behind ``LoginThrottleStore``. The SQL store runs
every statement through the async session (aiosqlite / asyncpg), so the same
anchors run against it too: a synchronous driver call or file access sneaking
into the store would trip the gate here. The engine is built off the loop,
because ``create_async_engine`` resolves the SQLite path synchronously — test
fixture work, not the production path under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from starlette.requests import Request

# Pre-import so the router's lazy imports are cached no-ops under the gate.
import deerflow.persistence.models  # noqa: F401
from app.gateway.auth import login_throttle
from app.gateway.routers import auth as auth_router
from deerflow.persistence.base import Base
from deerflow.persistence.login_throttle import LoginThrottleRow, LoginThrottleStore, MemoryLoginThrottleStore, SqlLoginThrottleStore

pytestmark = pytest.mark.asyncio

_CLIENT_IP = "203.0.113.9"
_POLICY = {"max_attempts": 5, "lockout_seconds": 3600.0}


def _build_sqlite_engine(path: Path) -> AsyncEngine:
    """Create the schema with a sync engine and return the async one (runs in a worker thread)."""
    sync_engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine, tables=[LoginThrottleRow.__table__])
    finally:
        sync_engine.dispose()
    return create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")


@pytest_asyncio.fixture(params=["memory", "sql"])
async def store(request, tmp_path, monkeypatch) -> AsyncIterator[LoginThrottleStore]:
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    engine: AsyncEngine | None = None
    if request.param == "memory":
        store: LoginThrottleStore = MemoryLoginThrottleStore()
    else:
        engine = await asyncio.to_thread(_build_sqlite_engine, tmp_path / "throttle.db")
        store = SqlLoginThrottleStore(async_sessionmaker(engine, expire_on_commit=False))
    login_throttle.install_login_throttle_store(store)
    try:
        yield store
    finally:
        login_throttle.reset_login_throttle_store()
        if engine is not None:
            await engine.dispose()


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login/local",
            "headers": [],
            "query_string": b"",
            "client": (_CLIENT_IP, 44000),
            "server": ("testserver", 80),
        }
    )


def _form() -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(username="user@example.com", password="wrong")


async def test_locked_ip_policy_resolution_does_not_block_loop(store) -> None:
    """A locked IP floods the endpoint: every request resolves the policy on
    the way to 429, and that resolution must stay off the event loop."""
    for _ in range(_POLICY["max_attempts"]):
        await store.record_failure(_CLIENT_IP, **_POLICY)  # sentence running

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.login_local(_request(), Response(), _form(), remember_me=True)

    assert exc_info.value.status_code == 429


async def test_failed_login_recording_does_not_block_loop(store, monkeypatch) -> None:
    """The wrong-password path resolves the policy again inside the recorder;
    counting must happen without blocking IO on the loop."""

    class _Provider:
        async def authenticate(self, credentials):
            return None

    monkeypatch.setattr(auth_router, "get_local_provider", lambda: _Provider())
    await store.record_failure(_CLIENT_IP, **_POLICY)  # counting, not locked

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.login_local(_request(), Response(), _form(), remember_me=True)

    assert exc_info.value.status_code == 401
    assert (await store.get(_CLIENT_IP)).fail_count == 2


async def test_successful_login_reset_does_not_block_loop(store, monkeypatch) -> None:
    """The success path clears the counter through the store on the loop."""
    from app.gateway.auth.config import AuthConfig, set_auth_config
    from app.gateway.auth.models import User

    class _Provider:
        async def authenticate(self, credentials):
            return User(email="user@example.com")

    set_auth_config(AuthConfig(jwt_secret="blocking-io-throttle-test-secret"))
    monkeypatch.setattr(auth_router, "get_local_provider", lambda: _Provider())
    await store.record_failure(_CLIENT_IP, **_POLICY)

    result = await auth_router.login_local(_request(), Response(), _form(), remember_me=True)

    assert result.expires_in > 0
    assert await store.get(_CLIENT_IP) is None


async def test_store_reset_and_probe_do_not_block_loop(store) -> None:
    """Store-level anchor for the success path: ``reset`` (DELETE) and the
    ``get`` probe run through the async session with no sync driver call or
    file access on the loop — the SQL variant is the one that matters."""
    await store.record_failure(_CLIENT_IP, **_POLICY)
    assert (await store.get(_CLIENT_IP)).fail_count == 1

    await store.reset(_CLIENT_IP)

    assert await store.get(_CLIENT_IP) is None
    await store.reset(_CLIENT_IP)  # idempotent on a clean IP
