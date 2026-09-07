"""Router tests for the projects CRUD API (Phase 1).

Harness mirrors ``test_channel_connections_router.py`` (real SQLAlchemy repo
on a temp sqlite engine + TestClient) and ``_router_auth_helpers`` (stub auth
middleware), extended to also set the request-scoped user ContextVar that
``ProjectRepository`` / ``ThreadMetaRepository`` resolve ownership from, and
to take the user id from a header so cross-user isolation can be exercised.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import projects
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectRepository
from deerflow.persistence.thread_meta import THREAD_ARCHIVED_METADATA_KEY, THREAD_PROJECT_METADATA_KEY, ThreadMetaRepository
from deerflow.runtime.user_context import reset_current_user, set_current_user

_STUB_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
    Permissions.PROJECTS_READ,
    Permissions.PROJECTS_WRITE,
    Permissions.PROJECTS_DELETE,
]

_USER_HEADER = "x-test-user"
_PERMISSIONS_HEADER = "x-test-permissions"


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamp a fake AuthContext and set the user ContextVar per request.

    Mirrors production ``AuthMiddleware`` (``request.state.auth`` +
    ``set_current_user``) so ``@require_permission`` and the
    ContextVar-resolving repositories behave as in the real gateway.
    The user id comes from the ``x-test-user`` header (default ``user-a``) so a
    single app can drive multiple identities. The granted permissions come from
    the ``x-test-permissions`` header (comma-separated; default the full stub
    list) so scope-narrowed callers can be exercised.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        user_id = request.headers.get(_USER_HEADER, "user-a")
        user = SimpleNamespace(id=user_id, system_role="user")
        request.state.user = user
        permissions_header = request.headers.get(_PERMISSIONS_HEADER)
        permissions = permissions_header.split(",") if permissions_header else list(_STUB_PERMISSIONS)
        request.state.auth = AuthContext(user=user, permissions=permissions)
        token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)


async def _init_db(tmp_path) -> None:
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'projects.db'}", sqlite_dir=str(tmp_path))


def _build_projects_app(tmp_path, *, project_repo: Any = "default") -> FastAPI:
    """Build a stub-authed FastAPI app with real SQL project/thread repos."""
    anyio.run(_init_db, tmp_path)
    sf = get_session_factory()
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware)
    app.state.project_repo = ProjectRepository(sf) if project_repo == "default" else project_repo
    app.state.thread_store = ThreadMetaRepository(sf)
    app.include_router(projects.router)
    return app


def _as_user(user_id: str) -> dict[str, str]:
    return {_USER_HEADER: user_id}


def _seed_thread(app: FastAPI, thread_id: str, *, user_id: str, project_id: str | None = None, metadata: dict | None = None) -> dict:
    """Create a thread row directly through the store as ``user_id``."""

    async def _run() -> dict:
        token = set_current_user(SimpleNamespace(id=user_id))
        try:
            return await app.state.thread_store.create(thread_id, project_id=project_id, metadata=metadata)
        finally:
            reset_current_user(token)

    return anyio.run(_run)


def _search_threads(app: FastAPI, *, user_id: str, **kwargs: Any) -> list[dict]:
    async def _run() -> list[dict]:
        token = set_current_user(SimpleNamespace(id=user_id))
        try:
            return await app.state.thread_store.search(**kwargs)
        finally:
            reset_current_user(token)

    return anyio.run(_run)


@pytest.fixture(autouse=True)
def _close_engine_after_test():
    yield
    anyio.run(close_engine)


def test_create_list_get_project(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/projects", json={"name": "Infra overhaul", "instructions": "ctx"})
        assert created.status_code == 201, created.text
        project = created.json()
        assert project["name"] == "Infra overhaul"
        assert project["instructions"] == "ctx"
        assert project["status"] == "active"
        assert project["presentation"] == {}

        listing = client.get("/api/projects")
        assert listing.status_code == 200
        assert [p["id"] for p in listing.json()["projects"]] == [project["id"]]

        fetched = client.get(f"/api/projects/{project['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == project["id"]


def test_get_patch_delete_foreign_project_returns_404(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "mine"}).json()

        # Fail closed: a foreign project is indistinguishable from a missing one.
        assert client.get(f"/api/projects/{project['id']}", headers=_as_user("user-b")).status_code == 404
        assert client.patch(f"/api/projects/{project['id']}", json={"name": "x"}, headers=_as_user("user-b")).status_code == 404
        assert client.delete(f"/api/projects/{project['id']}", headers=_as_user("user-b")).status_code == 404

        # Owner is unaffected.
        assert client.get(f"/api/projects/{project['id']}").status_code == 200
        assert client.get("/api/projects", headers=_as_user("user-b")).json()["projects"] == []


def test_patch_rename_does_not_touch_membership(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "old"}).json()
        _seed_thread(app, "thread-1", user_id="user-a", project_id=project["id"])

        patched = client.patch(f"/api/projects/{project['id']}", json={"name": "new"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "new"

        members = _search_threads(app, user_id="user-a", project_id=project["id"])
        assert [t["thread_id"] for t in members] == ["thread-1"]


def test_archive_restore_idempotent(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]

        for _ in range(2):
            archived = client.post(f"/api/projects/{pid}/archive")
            assert archived.status_code == 200
            assert archived.json()["status"] == "archived"
        assert client.get("/api/projects", params={"status": "active"}).json()["projects"] == []
        assert [p["id"] for p in client.get("/api/projects", params={"status": "archived"}).json()["projects"]] == [pid]

        for _ in range(2):
            restored = client.post(f"/api/projects/{pid}/restore")
            assert restored.status_code == 200
            assert restored.json()["status"] == "active"
        assert [p["id"] for p in client.get("/api/projects").json()["projects"]] == [pid]


def test_delete_unlinks_threads_and_keeps_them(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "thread-1", user_id="user-a", project_id=pid)

        deleted = client.delete(f"/api/projects/{pid}")
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{pid}").status_code == 404

        # Thread row survives with membership cleared.
        threads = _search_threads(app, user_id="user-a")
        assert [t["thread_id"] for t in threads] == ["thread-1"]
        assert THREAD_PROJECT_METADATA_KEY not in threads[0]["metadata"]
        assert _search_threads(app, user_id="user-a", project_id=pid) == []


def test_project_threads_lists_members_only(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        p1 = client.post("/api/projects", json={"name": "p1"}).json()
        p2 = client.post("/api/projects", json={"name": "p2"}).json()
        _seed_thread(app, "thread-p1", user_id="user-a", project_id=p1["id"])
        _seed_thread(app, "thread-p2", user_id="user-a", project_id=p2["id"])
        _seed_thread(app, "thread-loose", user_id="user-a")

        response = client.get(f"/api/projects/{p1['id']}/threads")
        assert response.status_code == 200
        assert [t["thread_id"] for t in response.json()] == ["thread-p1"]

        # Unknown project -> 404, not an empty list.
        assert client.get("/api/projects/nope/threads").status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"limit": -1},
        {"limit": 0},
        {"limit": 1001},
        {"offset": -1},
    ],
)
def test_project_threads_rejects_out_of_bounds_pagination(tmp_path, params):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        response = client.get(f"/api/projects/{project['id']}/threads", params=params)
        assert response.status_code == 422


@pytest.mark.parametrize("params", [{"limit": 1, "offset": 0}, {"limit": 1000}])
def test_project_threads_accepts_boundary_pagination(tmp_path, params):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        _seed_thread(app, "thread-1", user_id="user-a", project_id=project["id"])
        response = client.get(f"/api/projects/{project['id']}/threads", params=params)
        assert response.status_code == 200
        assert [t["thread_id"] for t in response.json()] == ["thread-1"]


def test_project_threads_requires_threads_read(tmp_path):
    """The listing returns thread records (titles/metadata), so it must require
    ``threads:read`` alongside ``projects:read`` — matching
    ``/api/threads/search``. A caller holding only ``projects:read`` (e.g. a
    scoped PAT) must be denied."""
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "thread-1", user_id="user-a", project_id=pid)

        without_threads_read = {
            **_as_user("user-a"),
            _PERMISSIONS_HEADER: ",".join(p for p in _STUB_PERMISSIONS if p != Permissions.THREADS_READ),
        }
        denied = client.get(f"/api/projects/{pid}/threads", headers=without_threads_read)
        assert denied.status_code == 403

        allowed = client.get(f"/api/projects/{pid}/threads", headers=_as_user("user-a"))
        assert allowed.status_code == 200
        assert [t["thread_id"] for t in allowed.json()] == ["thread-1"]


def test_project_threads_redacts_legacy_auth_token(tmp_path):
    """Legacy ``auth_token`` metadata must not leak through the project thread
    listing — thread endpoints already redact it via
    ``_MetadataRedactingResponse``; this listing must match."""
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "thread-1", user_id="user-a", project_id=pid, metadata={"auth_token": "sk-legacy-secret", "keep": "x"})

        response = client.get(f"/api/projects/{pid}/threads")
        assert response.status_code == 200
        metadata = response.json()[0]["metadata"]
        assert "auth_token" not in metadata
        assert metadata["keep"] == "x"
        assert metadata[THREAD_PROJECT_METADATA_KEY] == pid

        # Redaction is response-side only; the stored row keeps the legacy key.
        stored = _search_threads(app, user_id="user-a", project_id=pid)
        assert stored[0]["metadata"]["auth_token"] == "sk-legacy-secret"


def test_project_threads_metadata_unchanged_without_legacy_key(tmp_path):
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "thread-1", user_id="user-a", project_id=pid, metadata={"keep": "x"})

        response = client.get(f"/api/projects/{pid}/threads")
        assert response.status_code == 200
        assert response.json()[0]["metadata"] == {"keep": "x", THREAD_PROJECT_METADATA_KEY: pid}


def test_memory_backend_unavailable(tmp_path):
    app = _build_projects_app(tmp_path, project_repo=None)
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 503
        assert client.post("/api/projects", json={"name": "p"}).status_code == 503


def test_project_threads_wire_shape_is_narrow(tmp_path):
    """The listing must not leak store-row internals: ownership columns
    (``user_id``/``assistant_id``) and any future ``ThreadMetaRow`` column
    stay off the wire, and the OpenAPI schema is no longer empty. The model
    pins exactly the fields ``ProjectThread`` declares."""
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "thread-1", user_id="user-a", project_id=pid, metadata={"keep": "x"})

        response = client.get(f"/api/projects/{pid}/threads")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == {"thread_id", "display_name", "created_at", "updated_at", "metadata"}
        assert row["thread_id"] == "thread-1"
        assert row["metadata"] == {"keep": "x", THREAD_PROJECT_METADATA_KEY: pid}


def test_project_threads_excludes_archived_members(tmp_path):
    """Archived chats leave the project listing the same way they leave the
    sidebar (``archived: false`` semantics): no silent normal-row rendering
    of a retired chat on the project page. The store keeps the row; restore
    flows through the global Archived tab as elsewhere."""
    app = _build_projects_app(tmp_path)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "p"}).json()
        pid = project["id"]
        _seed_thread(app, "active-1", user_id="user-a", project_id=pid)
        _seed_thread(app, "archived-1", user_id="user-a", project_id=pid, metadata={THREAD_ARCHIVED_METADATA_KEY: True})

        response = client.get(f"/api/projects/{pid}/threads")
        assert response.status_code == 200
        assert [t["thread_id"] for t in response.json()] == ["active-1"]

        # The archived row still exists in the store (unfiltered search).
        stored = _search_threads(app, user_id="user-a", project_id=pid)
        assert {t["thread_id"] for t in stored} == {"active-1", "archived-1"}
