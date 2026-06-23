"""Cross-user isolation for the stateless ``POST /api/runs/stream`` and ``/wait`` endpoints.

These endpoints receive ``thread_id`` in the request body, so the
``@require_permission(owner_check=True)`` decorator — which reads the
``thread_id`` *path* parameter — cannot protect them. The owner check
lives inside ``services.start_run()`` instead; this suite pins it at the
HTTP layer so the gap cannot silently reopen.

Strategy
--------
``app.state.run_manager.create_or_reject`` raises ``ConflictError``, so a
request that *passes* the owner check deterministically short-circuits
with 409 before any agent code runs. The two outcomes:

- 404 + ``create_or_reject`` never awaited -> blocked by the owner check
- 409 + ``create_or_reject`` awaited       -> passed the owner check

The thread store is a real ``MemoryThreadMetaStore`` (not a mock) so the
``check_access`` semantics under test — missing row allows, ``user_id``
NULL allows, foreign owner denies — are exercised through real code.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from app.gateway.auth.models import User
from app.gateway.routers import runs
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import ConflictError

USER_A = User(email="owner-a@example.com", password_hash="x", system_role="user", id=uuid4())
USER_B = User(email="intruder-b@example.com", password_hash="x", system_role="user", id=uuid4())
INTERNAL_USER = SimpleNamespace(id="default", system_role="internal")

THREAD_A = "thread-owned-by-a"
THREAD_SHARED = "thread-shared-null-owner"


@pytest.fixture(autouse=True)
def _stub_app_config():
    """Inject a minimal AppConfig so the allowed path (which builds a
    RunContext via ``get_config()``) never reads config.yaml from disk."""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _make_thread_store() -> MemoryThreadMetaStore:
    store = MemoryThreadMetaStore(InMemoryStore())

    async def _seed():
        await store.create(THREAD_A, user_id=str(USER_A.id))
        await store.create(THREAD_SHARED, user_id=None)

    asyncio.run(_seed())
    return store


@contextmanager
def _client(user):
    """Yield a ``TestClient`` authenticated as ``user`` plus the stubbed
    ``create_or_reject`` mock, closing the client (and its anyio portal /
    background threads) on exit.

    ``create_or_reject`` raises ``ConflictError`` so a request that passes the
    owner check short-circuits to 409 before any agent code runs.
    """
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(runs.router)
    app.state.thread_store = _make_thread_store()
    app.state.stream_bridge = MagicMock()
    app.state.checkpointer = MagicMock()
    app.state.store = MagicMock()
    app.state.run_events_config = None
    app.state.run_event_store = MagicMock()
    run_manager = MagicMock()
    run_manager.create_or_reject = AsyncMock(side_effect=ConflictError("sentinel: owner check passed"))
    app.state.run_manager = run_manager
    with TestClient(app) as client:
        yield client, run_manager.create_or_reject


def _body(thread_id: str | None = None) -> dict:
    if thread_id is None:
        return {}
    return {"config": {"configurable": {"thread_id": thread_id}}}


# ---------------------------------------------------------------------------
# Denied: another user's thread
# ---------------------------------------------------------------------------


def test_stream_cross_user_returns_404():
    """User B cannot start a run on user A's thread via /api/runs/stream."""
    with _client(USER_B) as (client, create_or_reject):
        response = client.post("/api/runs/stream", json=_body(THREAD_A))
    assert response.status_code == 404
    assert response.json()["detail"] == f"Thread {THREAD_A} not found"
    create_or_reject.assert_not_awaited()


def test_wait_cross_user_returns_404_without_channel_values():
    """User B cannot read user A's checkpoint state via /api/runs/wait."""
    with _client(USER_B) as (client, create_or_reject):
        response = client.post("/api/runs/wait", json=_body(THREAD_A))
    assert response.status_code == 404
    assert response.json() == {"detail": f"Thread {THREAD_A} not found"}
    create_or_reject.assert_not_awaited()


# ---------------------------------------------------------------------------
# Allowed: owner, fresh/untracked/shared threads, internal role
# ---------------------------------------------------------------------------


def test_stream_owner_passes_owner_check():
    """User A reaches run creation on their own thread (409 sentinel)."""
    with _client(USER_A) as (client, create_or_reject):
        response = client.post("/api/runs/stream", json=_body(THREAD_A))
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_wait_owner_passes_owner_check():
    with _client(USER_A) as (client, create_or_reject):
        response = client.post("/api/runs/wait", json=_body(THREAD_A))
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_stream_without_thread_id_passes_owner_check():
    """Stateless run with no thread_id auto-creates a thread — never blocked."""
    with _client(USER_B) as (client, create_or_reject):
        response = client.post("/api/runs/stream", json=_body())
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_stream_untracked_thread_passes_owner_check():
    """A thread_id with no thread_meta row (untracked legacy) stays accessible."""
    with _client(USER_B) as (client, create_or_reject):
        response = client.post("/api/runs/stream", json=_body("never-created-thread"))
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_stream_shared_thread_passes_owner_check():
    """A thread_meta row with user_id NULL (shared / pre-auth data) stays accessible."""
    with _client(USER_B) as (client, create_or_reject):
        response = client.post("/api/runs/stream", json=_body(THREAD_SHARED))
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_stream_internal_role_scoped_by_owner_header():
    """IM channels run with the internal system role on behalf of the
    connection owner named in X-DeerFlow-Owner-User-Id — the owner check is
    scoped to that owner rather than bypassed."""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    with _client(INTERNAL_USER) as (client, create_or_reject):
        response = client.post(
            "/api/runs/stream",
            json=_body(THREAD_A),
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: str(USER_A.id)},
        )
    assert response.status_code == 409
    create_or_reject.assert_awaited()


def test_stream_internal_role_with_foreign_owner_header_returns_404():
    """The internal token alone must not grant access to another user's thread."""
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    with _client(INTERNAL_USER) as (client, create_or_reject):
        response = client.post(
            "/api/runs/stream",
            json=_body(THREAD_A),
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: str(USER_B.id)},
        )
    assert response.status_code == 404
    create_or_reject.assert_not_awaited()


def test_stream_internal_role_without_owner_header_is_scoped_to_internal_user():
    """Without an owner header internal callers keep access to their own and
    shared/untracked threads, but not to user-owned threads."""
    with _client(INTERNAL_USER) as (client, create_or_reject):
        denied = client.post("/api/runs/stream", json=_body(THREAD_A))
        allowed = client.post("/api/runs/stream", json=_body(THREAD_SHARED))
    assert denied.status_code == 404
    assert allowed.status_code == 409
    create_or_reject.assert_awaited()
