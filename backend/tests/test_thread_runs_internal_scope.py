"""Regression coverage for the runs/messages read endpoints' identity scoping (#5437).

Trusted internal callers are *authorized* as a synthetic internal user
(``system_role="internal"``) whose id is ``"default"`` or the
``make_safe_user_id``-normalized owner, while ``start_run`` stamps run rows
with the raw trusted-owner value. Filtering the reads by the authorization
identity therefore never matches the persisted rows. The read endpoints must
skip the per-user filter for internal callers — thread visibility is already
authorized by ``@require_permission(..., owner_check=True)`` — and keep it for
browser/API sessions.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION
from app.gateway.authz import AuthContext, Permissions
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user
from app.gateway.routers import thread_runs
from deerflow.runtime.events.store.memory import MemoryRunEventStore
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


class _PermissiveThreadStore:
    """Stands in for the thread store behind ``owner_check=True``."""

    async def check_access(self, _thread_id: str, _user_id: str, *, require_existing: bool = False) -> bool:
        return True


class _RecordingRunStore(MemoryRunStore):
    """Records the per-user filter identity each read resolves to.

    ``MemoryRunEventStore.list_messages`` ignores ``user_id`` (only the SQL
    backends honor it), so the runs store is where the resolved filter id is
    observable in-memory: hidden-run lookups and turn-duration injection both
    flow through ``list_by_thread``/``get`` with the endpoint's filter id.
    """

    def __init__(self) -> None:
        super().__init__()
        self.list_by_thread_user_ids: list[str | None] = []
        self.get_user_ids: list[str | None] = []

    async def list_by_thread(self, thread_id, *, user_id=None, **kwargs):
        self.list_by_thread_user_ids.append(user_id)
        return await super().list_by_thread(thread_id, user_id=user_id, **kwargs)

    async def get(self, run_id, *, user_id=None, **kwargs):
        self.get_user_ids.append(user_id)
        return await super().get(run_id, user_id=user_id, **kwargs)


class _RecordingFeedbackRepo:
    """Records the per-user identity the feedback queries are scoped with."""

    def __init__(self) -> None:
        self.list_by_thread_user_ids: list[str | None] = []
        self.list_by_run_ids_user_ids: list[str | None] = []

    async def list_by_thread_grouped(self, thread_id, *, user_id=None):
        self.list_by_thread_user_ids.append(user_id)
        return {}

    async def list_by_run_ids(self, thread_id, run_ids, *, user_id=None):
        self.list_by_run_ids_user_ids.append(user_id)
        return {}


def _browser_user() -> User:
    return User(id=BROWSER_USER_ID, email="scope-test@example.com", password_hash="x", system_role="user")


def _internal_user(owner_raw: str | None):
    # Mirrors AuthMiddleware + get_internal_user: the synthetic internal user
    # carries the safe-spelled owner id, or "default" without an owner header.
    return get_internal_user(owner_user_id=owner_raw)


def _seed_run(store: MemoryRunStore, run_id: str, *, user_id: str | None, status: str = "success") -> None:
    asyncio.run(store.put(run_id, thread_id=THREAD_ID, user_id=user_id, status=status))


def _seed_message(event_store: MemoryRunEventStore, run_id: str, message_id: str) -> None:
    asyncio.run(
        event_store.put(
            thread_id=THREAD_ID,
            run_id=run_id,
            event_type="llm.ai.response",
            category="message",
            content={"type": "ai", "id": message_id, "content": message_id, "additional_kwargs": {}},
            metadata={},
        )
    )


def _make_app(
    *,
    user,
    auth_source: str,
    run_store: MemoryRunStore,
    event_store: MemoryRunEventStore | None = None,
    feedback_repo: _RecordingFeedbackRepo | None = None,
) -> TestClient:
    app = FastAPI()
    app.add_middleware(_ScopeAuthMiddleware, user=user, auth_source=auth_source)
    app.state.thread_store = _PermissiveThreadStore()
    app.state.run_manager = RunManager(store=run_store)
    if event_store is not None:
        app.state.run_event_store = event_store
    if feedback_repo is not None:
        app.state.feedback_repo = feedback_repo
    app.include_router(thread_runs.router)
    return TestClient(app)


@pytest.fixture()
def mixed_owner_store() -> MemoryRunStore:
    store = MemoryRunStore()
    _seed_run(store, RUN_BROWSER, user_id=str(BROWSER_USER_ID))
    _seed_run(store, RUN_OWNER, user_id=OWNER_RAW)
    return store


def test_internal_caller_lists_owner_stamped_runs(mixed_owner_store: MemoryRunStore) -> None:
    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=mixed_owner_store,
    )

    with client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()} == {RUN_BROWSER, RUN_OWNER}


def test_internal_caller_get_run_owner_stamped(mixed_owner_store: MemoryRunStore) -> None:
    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=mixed_owner_store,
    )

    with client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs/{RUN_OWNER}",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert response.json()["run_id"] == RUN_OWNER


def test_internal_caller_runs_page_owner_stamped(mixed_owner_store: MemoryRunStore) -> None:
    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=mixed_owner_store,
    )

    with client:
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
    client = _make_app(
        user=_internal_user(None),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=mixed_owner_store,
    )

    with client:
        response = client.get(f"/api/threads/{THREAD_ID}/runs")

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()} == {RUN_BROWSER, RUN_OWNER}


def test_browser_session_keeps_per_user_filter(mixed_owner_store: MemoryRunStore) -> None:
    """Browser sessions keep filtering by their own data identity."""
    client = _make_app(
        user=_browser_user(),
        auth_source=AUTH_SOURCE_SESSION,
        run_store=mixed_owner_store,
    )

    with client:
        listed = client.get(f"/api/threads/{THREAD_ID}/runs")
        cross_user = client.get(f"/api/threads/{THREAD_ID}/runs/{RUN_OWNER}")

    assert listed.status_code == 200
    assert [row["run_id"] for row in listed.json()] == [RUN_BROWSER]
    assert cross_user.status_code == 404


def test_internal_caller_messages_skip_per_user_filter(mixed_owner_store: MemoryRunStore) -> None:
    """Internal callers read the authorized thread's messages unfiltered.

    The observable filter identity is what reaches the scoped queries — the
    runs store (hidden-run lookups, turn durations) and the feedback repo —
    ``None`` for internal callers.
    """
    event_store = MemoryRunEventStore()
    _seed_message(event_store, RUN_OWNER, "msg-owner")
    _seed_message(event_store, RUN_BROWSER, "msg-browser")
    run_store = _RecordingRunStore()
    for run_id, user_id in ((RUN_BROWSER, str(BROWSER_USER_ID)), (RUN_OWNER, OWNER_RAW)):
        _seed_run(run_store, run_id, user_id=user_id)
    feedback_repo = _RecordingFeedbackRepo()

    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        event_store=event_store,
        feedback_repo=feedback_repo,
    )

    with client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/messages",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
        page = client.get(
            f"/api/threads/{THREAD_ID}/messages/page",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert {row["content"]["id"] for row in response.json()} == {"msg-owner", "msg-browser"}
    assert page.status_code == 200
    assert {row["content"]["id"] for row in page.json()["data"]} == {"msg-owner", "msg-browser"}
    assert run_store.list_by_thread_user_ids and all(uid is None for uid in run_store.list_by_thread_user_ids)
    assert feedback_repo.list_by_thread_user_ids == [None]
    assert feedback_repo.list_by_run_ids_user_ids == [None]


def test_browser_session_messages_keep_per_user_filter(mixed_owner_store: MemoryRunStore) -> None:
    """Browser sessions keep passing their own id to the messages pipeline."""
    event_store = MemoryRunEventStore()
    _seed_message(event_store, RUN_OWNER, "msg-owner")
    _seed_message(event_store, RUN_BROWSER, "msg-browser")
    run_store = _RecordingRunStore()
    for run_id, user_id in ((RUN_BROWSER, str(BROWSER_USER_ID)), (RUN_OWNER, OWNER_RAW)):
        _seed_run(run_store, run_id, user_id=user_id)
    feedback_repo = _RecordingFeedbackRepo()

    client = _make_app(
        user=_browser_user(),
        auth_source=AUTH_SOURCE_SESSION,
        run_store=run_store,
        event_store=event_store,
        feedback_repo=feedback_repo,
    )

    with client:
        response = client.get(f"/api/threads/{THREAD_ID}/messages")

    assert response.status_code == 200
    assert {row["content"]["id"] for row in response.json()} == {"msg-owner", "msg-browser"}
    assert run_store.list_by_thread_user_ids and all(uid == str(BROWSER_USER_ID) for uid in run_store.list_by_thread_user_ids)
    assert feedback_repo.list_by_thread_user_ids == [str(BROWSER_USER_ID)]


# ---------------------------------------------------------------------------
# edit/regenerate helper fallback paths (#5482)
# ---------------------------------------------------------------------------


def _helper_request(*, user, auth_source: str, run_store, event_store):
    """Minimal Request stand-in: the helpers only touch state and app.state."""
    app_state = SimpleNamespace(run_manager=RunManager(store=run_store), run_event_store=event_store)
    return SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=auth_source),
        app=SimpleNamespace(state=app_state),
    )


def test_helper_fallback_paths_resolve_internal_caller_runs() -> None:
    """The edit/regenerate helper fallbacks must use the data identity (#5482)."""
    store = _RecordingRunStore()
    _seed_run(store, RUN_OWNER, user_id=OWNER_RAW, status="interrupted")
    _seed_run(store, RUN_BROWSER, user_id=str(BROWSER_USER_ID), status="success")
    request = _helper_request(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=store,
        event_store=MemoryRunEventStore(),
    )

    # The owner-stamped interrupted run resolves through the raw owner stamp.
    interrupted = asyncio.run(thread_runs._find_interrupted_target_run_id(THREAD_ID, {"additional_kwargs": {"run_id": RUN_OWNER}}, request))
    assert interrupted == RUN_OWNER
    assert store.get_user_ids[-1] is None

    # An interrupted run is not an editable source run, but the lookup itself
    # must have reached it (409 for status, not for a missing record).
    with pytest.raises(HTTPException) as exc:
        asyncio.run(thread_runs._require_successful_source_run(THREAD_ID, RUN_OWNER, request))
    assert exc.value.status_code == 409
    assert "successful" in exc.value.detail
    assert store.get_user_ids[-1] is None

    # Fallback scan without any event-store or kwargs anchors still scans the
    # authorized thread unfiltered (and 409s on the miss).
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(
            thread_runs._find_target_run_id(
                THREAD_ID,
                "missing-message",
                {"content": "unmatched"},
                {"additional_kwargs": {}},
                request,
            )
        )
    assert exc2.value.status_code == 409
    assert store.list_by_thread_user_ids and store.list_by_thread_user_ids[-1] is None


def test_helper_fallback_paths_keep_per_user_filter_for_browser_sessions() -> None:
    """Browser sessions keep the per-user filter in the helper fallbacks."""
    store = _RecordingRunStore()
    _seed_run(store, RUN_OWNER, user_id=OWNER_RAW, status="interrupted")
    _seed_run(store, RUN_BROWSER, user_id=str(BROWSER_USER_ID), status="success")
    request = _helper_request(
        user=_browser_user(),
        auth_source=AUTH_SOURCE_SESSION,
        run_store=store,
        event_store=MemoryRunEventStore(),
    )

    # The owner-stamped run is invisible under the browser user's filter.
    assert asyncio.run(thread_runs._find_interrupted_target_run_id(THREAD_ID, {"additional_kwargs": {"run_id": RUN_OWNER}}, request)) is None
    assert store.get_user_ids[-1] == str(BROWSER_USER_ID)

    # Their own successful run still resolves, and a cross-user one 409s.
    record = asyncio.run(thread_runs._require_successful_source_run(THREAD_ID, RUN_BROWSER, request))
    assert record.run_id == RUN_BROWSER
    with pytest.raises(HTTPException) as exc:
        asyncio.run(thread_runs._require_successful_source_run(THREAD_ID, RUN_OWNER, request))
    assert exc.value.status_code == 409
    assert store.get_user_ids[-1] == str(BROWSER_USER_ID)
