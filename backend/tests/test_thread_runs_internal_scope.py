"""Regression coverage for the runs read endpoints' identity scoping (#5437).

Trusted internal callers are *authorized* as a synthetic internal user
(``system_role="internal"``) whose id is ``"default"`` or the
``make_safe_user_id``-normalized owner, while ``start_run`` stamps run rows
with the raw trusted-owner value. Filtering the reads by the authorization
identity therefore never matches the persisted rows. The endpoints must skip
the per-user filter for internal callers — thread visibility is already
authorized by ``@require_permission(..., owner_check=True)`` — and keep it for
browser/API sessions.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION
from app.gateway.authz import AuthContext, Permissions
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user
from app.gateway.routers import thread_runs
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore

THREAD_ID = "thread-scope"
BROWSER_USER_ID = UUID("00000000-0000-0000-0000-00000000000a")
# A lossy trusted-owner value: make_safe_user_id normalizes it to
# "feishu-owner-777-<digest>", which can never equal the raw value stamped on
# the run row — the exact mismatch class reported in #5437.
OWNER_RAW = "feishu:owner-777"
RUN_BROWSER = "run-browser-row"
RUN_OWNER = "run-owner-row"

_STUB_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


class _ScopeAuthMiddleware(BaseHTTPMiddleware):
    """Stamp the same state trio production ``AuthMiddleware`` stamps."""

    def __init__(self, app, *, user, auth_source: str) -> None:
        super().__init__(app)
        self._user = user
        self._auth_source = auth_source

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.user = self._user
        request.state.auth_source = self._auth_source
        request.state.auth = AuthContext(user=self._user, permissions=list(_STUB_PERMISSIONS))
        return await call_next(request)


def _browser_user() -> User:
    return User(id=BROWSER_USER_ID, email="scope-test@example.com", password_hash="x", system_role="user")


def _seed_run(store: MemoryRunStore, run_id: str, *, user_id: str | None) -> None:
    asyncio.run(
        store.put(
            run_id,
            thread_id=THREAD_ID,
            user_id=user_id,
            status="success",
        )
    )


class _PermissiveThreadStore:
    """Stands in for the thread store behind ``owner_check=True``."""

    async def check_access(self, _thread_id: str, _user_id: str, *, require_existing: bool = False) -> bool:
        return True


def _internal_user(owner_raw: str | None):
    # Mirrors AuthMiddleware + get_internal_user: the synthetic internal user
    # carries the safe-spelled owner id, or "default" without an owner header.
    return get_internal_user(owner_user_id=owner_raw)


@pytest.fixture()
def mixed_owner_store() -> MemoryRunStore:
    store = MemoryRunStore()
    _seed_run(store, RUN_BROWSER, user_id=str(BROWSER_USER_ID))
    _seed_run(store, RUN_OWNER, user_id=OWNER_RAW)
    return store


def test_internal_caller_lists_owner_stamped_runs(mixed_owner_store: MemoryRunStore) -> None:
    app = FastAPI()
    app.add_middleware(
        _ScopeAuthMiddleware,
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
    )
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=mixed_owner_store)
    app.include_router(thread_runs.router)

    with TestClient(app) as client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()} == {RUN_BROWSER, RUN_OWNER}


def test_internal_caller_get_run_owner_stamped(mixed_owner_store: MemoryRunStore) -> None:
    app = FastAPI()
    app.add_middleware(
        _ScopeAuthMiddleware,
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
    )
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=mixed_owner_store)
    app.include_router(thread_runs.router)

    with TestClient(app) as client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs/{RUN_OWNER}",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert response.json()["run_id"] == RUN_OWNER


def test_internal_caller_runs_page_owner_stamped(mixed_owner_store: MemoryRunStore) -> None:
    app = FastAPI()
    app.add_middleware(
        _ScopeAuthMiddleware,
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
    )
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=mixed_owner_store)
    app.include_router(thread_runs.router)

    with TestClient(app) as client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs/page",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()["data"]} == {RUN_BROWSER, RUN_OWNER}
    assert response.json()["has_more"] is False


def test_internal_caller_without_owner_header_sees_authorized_thread_runs(mixed_owner_store: MemoryRunStore) -> None:
    """No owner header ⇒ synthetic id "default", which matches nothing either.

    The thread is authorized via owner_check, so its runs stay listable.
    """
    app = FastAPI()
    app.add_middleware(
        _ScopeAuthMiddleware,
        user=_internal_user(None),
        auth_source=AUTH_SOURCE_INTERNAL,
    )
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=mixed_owner_store)
    app.include_router(thread_runs.router)

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{THREAD_ID}/runs")

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()} == {RUN_BROWSER, RUN_OWNER}


def test_browser_session_keeps_per_user_filter(mixed_owner_store: MemoryRunStore) -> None:
    """Browser sessions keep filtering by their own data identity."""
    app = FastAPI()
    app.add_middleware(
        _ScopeAuthMiddleware,
        user=_browser_user(),
        auth_source=AUTH_SOURCE_SESSION,
    )
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=mixed_owner_store)
    app.include_router(thread_runs.router)

    with TestClient(app) as client:
        listed = client.get(f"/api/threads/{THREAD_ID}/runs")
        cross_user = client.get(f"/api/threads/{THREAD_ID}/runs/{RUN_OWNER}")

    assert listed.status_code == 200
    assert [row["run_id"] for row in listed.json()] == [RUN_BROWSER]
    assert cross_user.status_code == 404
