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
from langgraph.store.memory import InMemoryStore
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION
from app.gateway.authz import AuthContext, Permissions
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user
from app.gateway.routers import thread_runs
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
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
    """Stands in for the thread store behind ``owner_check=True``.

    The existing scope tests exercise the established-ownership path, so
    ``get`` reports an existing, owner-established meta row.
    """

    async def check_access(self, _thread_id: str, _user_id: str, *, require_existing: bool = False) -> bool:
        return True

    async def get(self, _thread_id: str, *, user_id: str | None | object = None) -> dict | None:
        return {"thread_id": THREAD_ID, "user_id": "established-owner"}


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
    thread_store=None,
) -> TestClient:
    app = FastAPI()
    app.add_middleware(_ScopeAuthMiddleware, user=user, auth_source=auth_source)
    app.state.thread_store = thread_store if thread_store is not None else _PermissiveThreadStore()
    app.state.run_store = run_store
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
# owner isolation on threads without established metadata (#5448 review P1)
# ---------------------------------------------------------------------------


def test_missing_thread_meta_keeps_owner_isolation_for_internal_callers() -> None:
    """owner_check also authorizes missing-meta (legacy shared) threads.

    There, unfiltered reads would expose other users' persisted runs to the
    acting owner's internal caller, so the raw trusted owner stays the filter
    — the exact value ``start_run`` stamps on run rows (#5448 review P1).
    """
    thread_store = MemoryThreadMetaStore(InMemoryStore())  # no metadata row at all
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-other-user", user_id=str(BROWSER_USER_ID), status="success")

    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        listed = client.get(
            f"/api/threads/{THREAD_ID}/runs",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
        page = client.get(
            f"/api/threads/{THREAD_ID}/runs/page",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
        single = client.get(
            f"/api/threads/{THREAD_ID}/runs/run-other-user",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert listed.status_code == 200
    assert listed.json() == []
    assert page.status_code == 200
    assert page.json()["data"] == []
    assert single.status_code == 404
    # The acting owner's own raw-stamped runs remain visible: seed one and
    # confirm it comes back through the same endpoints.
    owned_store = _RecordingRunStore()
    _seed_run(owned_store, "run-own-owner-stamp", user_id=OWNER_RAW, status="success")
    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=owned_store,
        thread_store=thread_store,
    )
    with client:
        own = client.get(
            f"/api/threads/{THREAD_ID}/runs/run-own-owner-stamp",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
    assert own.status_code == 200
    assert own.json()["run_id"] == "run-own-owner-stamp"


def test_null_owner_thread_meta_keeps_owner_isolation_for_internal_callers() -> None:
    """NULL-owner meta rows (shared/pre-auth data) isolate by raw owner too."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(
        thread_store.create(
            THREAD_ID,
            assistant_id=None,
            user_id=None,  # shared / pre-auth: meta row exists with NULL owner
        )
    )
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-other-user", user_id=str(BROWSER_USER_ID), status="success")

    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        listed = client.get(
            f"/api/threads/{THREAD_ID}/runs",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
        single = client.get(
            f"/api/threads/{THREAD_ID}/runs/run-other-user",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert listed.status_code == 200
    assert listed.json() == []
    assert single.status_code == 404


def test_established_ownership_still_reads_thread_runs_unfiltered(mixed_owner_store: MemoryRunStore) -> None:
    """Established meta ownership keeps the #5437 unfiltered-read behavior."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(thread_store.create(THREAD_ID, assistant_id=None, user_id=OWNER_RAW))
    run_store = _RecordingRunStore()
    _seed_run(run_store, RUN_OWNER, user_id=OWNER_RAW, status="success")
    _seed_run(run_store, "run-legacy-default", user_id="default", status="success")

    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/runs",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    assert {row["run_id"] for row in response.json()} == {RUN_OWNER, "run-legacy-default"}


def test_ownerless_internal_caller_default_filter_on_missing_meta() -> None:
    """Without an owner header the synthetic "default" identity is the filter.

    Pins the owner-less fallback branch of ``_run_scope_user_id``: a run
    stamped with another owner's raw id stays hidden on missing-meta threads.
    """
    thread_store = MemoryThreadMetaStore(InMemoryStore())  # no meta row
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")

    client = _make_app(
        user=_internal_user(None),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        response = client.get(f"/api/threads/{THREAD_ID}/runs")

    assert response.status_code == 200
    assert response.json() == []


def test_subresource_reads_stay_owner_isolated_without_meta() -> None:
    """Run-scoped sub-resources must respect the acting owner's stamp.

    These reads query by ``(thread_id, run_id)`` with no per-user filter of
    their own; on missing-meta threads an internal caller acting for owner A
    could otherwise read owner B's run content by id (#5448 review P1
    follow-up).
    """
    thread_store = MemoryThreadMetaStore(InMemoryStore())  # no meta row
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")
    event_store = MemoryRunEventStore()
    _seed_message(event_store, "run-owner-777", "msg-owner-run")

    stranger_headers = {INTERNAL_OWNER_USER_ID_HEADER_NAME: "feishu:owner-999"}
    owner_headers = {INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW}
    base = f"/api/threads/{THREAD_ID}/runs/run-owner-777"

    stranger = _make_app(
        user=_internal_user("feishu:owner-999"),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        event_store=event_store,
        thread_store=thread_store,
    )
    owner_client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        event_store=event_store,
        thread_store=thread_store,
    )

    with stranger:
        assert stranger.get(base + "/messages", headers=stranger_headers).status_code == 404
        assert stranger.get(base + "/events", headers=stranger_headers).status_code == 404
        assert stranger.get(base + "/workspace-changes", headers=stranger_headers).status_code == 404
        assert stranger.get(base + "/join", headers=stranger_headers).status_code == 404

    with owner_client:
        messages = owner_client.get(base + "/messages", headers=owner_headers)
        events = owner_client.get(base + "/events", headers=owner_headers)

    assert messages.status_code == 200
    assert [row["content"]["id"] for row in messages.json()["data"]] == ["msg-owner-run"]
    assert events.status_code == 200
    assert any(event.get("run_id") == "run-owner-777" for event in events.json())


def test_null_owner_thread_gates_cancel_and_archive_for_internal_callers() -> None:
    """NULL-owner meta rows gate POST /cancel and the archive pair too.

    The round-2 findings: cancel resolved runs unscoped (an interrupt-vs-join
    inconsistency) and the archive manifest leaked the other owner's
    delivered-file count plus a 200-vs-409 delivery oracle on shared threads.
    """
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(thread_store.create(THREAD_ID, assistant_id=None, user_id=None))
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")
    event_store = MemoryRunEventStore()

    stranger_headers = {INTERNAL_OWNER_USER_ID_HEADER_NAME: "feishu:owner-999"}
    stranger = _make_app(
        user=_internal_user("feishu:owner-999"),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        event_store=event_store,
        thread_store=thread_store,
    )

    with stranger:
        cancel = stranger.post(
            f"/api/threads/{THREAD_ID}/runs/run-owner-777/cancel?action=interrupt",
            headers=stranger_headers,
        )
        manifest = stranger.get(
            f"/api/threads/{THREAD_ID}/runs/run-owner-777/artifacts/archive",
            headers=stranger_headers,
        )
        archive = stranger.post(
            f"/api/threads/{THREAD_ID}/runs/run-owner-777/artifacts/archive",
            headers=stranger_headers,
        )

    assert cancel.status_code == 404
    assert manifest.status_code == 404
    assert archive.status_code == 404


def test_null_owner_thread_matching_owner_cancels_and_reads_manifest() -> None:
    """The acting owner keeps cancel and archive access on shared threads."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    asyncio.run(thread_store.create(THREAD_ID, assistant_id=None, user_id=None))
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")
    event_store = MemoryRunEventStore()
    asyncio.run(
        event_store.put(
            thread_id=THREAD_ID,
            run_id="run-owner-777",
            event_type="run.delivery",
            category="outputs",
            content={"presented": 2, "by_tool": {"present_files": ["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.txt"]}},
        )
    )

    owner_client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        event_store=event_store,
        thread_store=thread_store,
    )

    with owner_client:
        manifest = owner_client.get(
            f"/api/threads/{THREAD_ID}/runs/run-owner-777/artifacts/archive",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )
        cancel = owner_client.post(
            f"/api/threads/{THREAD_ID}/runs/run-owner-777/cancel?action=interrupt",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert manifest.status_code == 200
    assert manifest.json() == {"file_count": 2}
    # A terminal run cannot be cancelled again: the acting owner reaches the
    # real conflict path instead of a 404 anti-enumeration answer.
    assert cancel.status_code == 409


# edit/regenerate helper fallback paths (#5482)
# ---------------------------------------------------------------------------


def _helper_request(*, user, auth_source: str, run_store, event_store, owner_header: str | None = None):
    """Minimal Request stand-in: the helpers touch state, app.state and headers."""
    app_state = SimpleNamespace(run_manager=RunManager(store=run_store), run_event_store=event_store)
    headers = {INTERNAL_OWNER_USER_ID_HEADER_NAME: owner_header} if owner_header else {}
    return SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=auth_source),
        app=SimpleNamespace(state=app_state),
        headers=headers,
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
        owner_header=OWNER_RAW,
    )

    # The owner-stamped interrupted run resolves through the raw owner stamp.
    interrupted = asyncio.run(thread_runs._find_interrupted_target_run_id(THREAD_ID, {"additional_kwargs": {"run_id": RUN_OWNER}}, request))
    assert interrupted == RUN_OWNER
    assert store.get_user_ids[-1] == OWNER_RAW

    # An interrupted run is not an editable source run, but the lookup itself
    # must have reached it (409 for status, not for a missing record).
    with pytest.raises(HTTPException) as exc:
        asyncio.run(thread_runs._require_successful_source_run(THREAD_ID, RUN_OWNER, request))
    assert exc.value.status_code == 409
    assert "successful" in exc.value.detail
    assert store.get_user_ids[-1] == OWNER_RAW

    # Fallback scan without any event-store or kwargs anchors still scans the
    # authorized thread through the acting owner's raw-stamp scope (and 409s
    # on the miss).
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
    assert store.list_by_thread_user_ids and store.list_by_thread_user_ids[-1] == OWNER_RAW


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


def test_token_usage_isolated_without_meta_for_internal_callers() -> None:
    """Token-usage aggregate honors the acting owner's raw stamp (#5484 r4)."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())  # no meta row
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")
    _seed_run(run_store, "run-other-user", user_id=str(BROWSER_USER_ID), status="success")
    run_store._runs["run-owner-777"]["token_usage_by_model"] = {"gpt-x": {"total_tokens": 111}}
    run_store._runs["run-owner-777"]["total_tokens"] = 111
    run_store._runs["run-other-user"]["token_usage_by_model"] = {"gpt-x": {"total_tokens": 999}}
    run_store._runs["run-other-user"]["total_tokens"] = 999

    client = _make_app(
        user=_internal_user(OWNER_RAW),
        auth_source=AUTH_SOURCE_INTERNAL,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        response = client.get(
            f"/api/threads/{THREAD_ID}/token-usage",
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: OWNER_RAW},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens"] == 111
    assert body["total_runs"] == 1


def test_token_usage_narrowed_for_browser_sessions_without_meta() -> None:
    """Browser sessions on shared threads see only their own spend too."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())  # no meta row
    run_store = _RecordingRunStore()
    _seed_run(run_store, "run-owner-777", user_id=OWNER_RAW, status="success")
    _seed_run(run_store, "run-browser", user_id=str(BROWSER_USER_ID), status="success")
    run_store._runs["run-owner-777"]["token_usage_by_model"] = {"gpt-x": {"total_tokens": 111}}
    run_store._runs["run-owner-777"]["total_tokens"] = 111
    run_store._runs["run-browser"]["token_usage_by_model"] = {"gpt-x": {"total_tokens": 222}}
    run_store._runs["run-browser"]["total_tokens"] = 222

    client = _make_app(
        user=_browser_user(),
        auth_source=AUTH_SOURCE_SESSION,
        run_store=run_store,
        thread_store=thread_store,
    )

    with client:
        response = client.get(f"/api/threads/{THREAD_ID}/token-usage")

    assert response.status_code == 200
    assert response.json()["total_tokens"] == 222
