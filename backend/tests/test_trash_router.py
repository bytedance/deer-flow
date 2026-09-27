"""Integration tests for the trash API (Phase-2 spec §6.5/§8.2/§8.3/§11).

Mirrors the project-documents router tests: a stub auth middleware stamps a
fake AuthContext per request, so these exercise routing, permission
decorators, fail-closed 404s, the restore outcome matrix, purge semantics,
and the lazy retention sweep through the real HTTP stack.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.authz import AuthContext, Permissions
from app.gateway.deps import get_config
from app.gateway.routers import project_documents, projects, trash
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.runtime.user_context import reset_current_user, set_current_user

_STUB_PERMISSIONS: list[str] = [
    Permissions.PROJECTS_READ,
    Permissions.PROJECTS_WRITE,
    Permissions.PROJECTS_DELETE,
]

_USER_HEADER = "x-test-user"


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamp a fake AuthContext and set the user ContextVar per request."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        user_id = request.headers.get(_USER_HEADER, "user-a")
        user = SimpleNamespace(id=user_id, system_role="user")
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=list(_STUB_PERMISSIONS))
        token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)


async def _init_db(tmp_path) -> None:
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'trash.db'}", sqlite_dir=str(tmp_path))


def _build_app(tmp_path, *, document_repo: Any = "default") -> FastAPI:
    anyio.run(_init_db, tmp_path)
    sf = get_session_factory()
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware)
    app.state.project_repo = ProjectRepository(sf)
    app.state.project_document_repo = ProjectDocumentRepository(sf) if document_repo == "default" else document_repo
    app.state.thread_store = ThreadMetaRepository(sf)
    cfg = MagicMock()
    cfg.uploads = {}
    app.dependency_overrides[get_config] = lambda: cfg
    app.include_router(projects.router)
    app.include_router(project_documents.router)
    app.include_router(trash.router)
    return app


def _as_user(user_id: str) -> dict[str, str]:
    return {_USER_HEADER: user_id}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_mod, "_paths", None)
    yield
    anyio.run(close_engine)


def _create_project(client: TestClient, name: str = "P", **kwargs) -> dict:
    created = client.post("/api/projects", json={"name": name, **kwargs})
    assert created.status_code == 201
    return created.json()


def _upload(client: TestClient, project_id: str, name: str, data: bytes, **kwargs) -> dict:
    response = client.post(f"/api/projects/{project_id}/documents", files={"file": (name, data)}, **kwargs)
    assert response.status_code == 201
    return response.json()["document"]


def _trash(client: TestClient, project_id: str, document_id: str, **kwargs) -> None:
    assert client.delete(f"/api/projects/{project_id}/documents/{document_id}", **kwargs).status_code == 204


def _get_row(app: FastAPI, document_id: str, *, user_id: str = "user-a") -> dict | None:
    import functools

    repo: ProjectDocumentRepository = app.state.project_document_repo
    return anyio.run(functools.partial(repo.get, document_id, include_trashed=True, user_id=user_id))


def _set_trashed_at(document_id: str, when: datetime) -> None:
    from sqlalchemy import update as sa_update

    from deerflow.persistence.projects.model import ProjectDocumentRow

    async def _run() -> None:
        sf = get_session_factory()
        async with sf() as session:
            await session.execute(sa_update(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).values(trashed_at=when))
            await session.commit()

    anyio.run(_run)


def _original_path(app: FastAPI, row: dict, *, user_id: str = "user-a") -> Path:
    from deerflow.config.paths import get_paths
    from deerflow.projects.documents import original_file_path

    return original_file_path(get_paths(), user_id=user_id, row=row)


class TestTrashListing:
    def test_list_empty_then_populated_with_origin_display_fields(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client, name="Roadmap")

        empty = client.get("/api/trash/documents").json()
        assert empty == {"documents": [], "total": 0, "limit": 100, "offset": 0}

        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])

        listing = client.get("/api/trash/documents").json()
        assert listing["total"] == 1
        entry = listing["documents"][0]
        assert entry["id"] == doc["id"]
        assert entry["name"] == "a.txt"
        assert entry["trashed_at"]
        assert entry["trash_origin"] == {"project_id": project["id"], "project_name": "Roadmap"}
        # Trashed rows stay invisible to the shelf.
        assert client.get(f"/api/projects/{project['id']}/documents").json()["total"] == 0
        # Foreign users see none of it.
        assert client.get("/api/trash/documents", headers=_as_user("user-b")).json()["total"] == 0

    def test_project_delete_moves_shelf_into_the_same_trash_listing(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client, name="Doomed")
        doc = _upload(client, project["id"], "a.txt", b"hello")
        assert client.delete(f"/api/projects/{project['id']}").status_code == 204

        listing = client.get("/api/trash/documents").json()
        assert [entry["id"] for entry in listing["documents"]] == [doc["id"]]
        assert listing["documents"][0]["trash_origin"] == {"project_id": project["id"], "project_name": "Doomed"}

    def test_lazy_retention_sweep_runs_before_listing(self, tmp_path):
        """§8.3: GET /api/trash/documents triggers the sweep; expired rows
        are purged before the listing is assembled."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "old.txt", b"old")
        _trash(client, project["id"], doc["id"])
        _set_trashed_at(doc["id"], datetime.now(UTC) - timedelta(days=31))
        row = _get_row(app, doc["id"])
        original = _original_path(app, row)

        listing = client.get("/api/trash/documents").json()

        assert listing["total"] == 0
        assert _get_row(app, doc["id"]) is None
        assert not original.exists()

    def test_listing_throttles_reconciliation_but_never_the_expiry_purge(self, tmp_path, monkeypatch):
        """§8.3 debounce: repeated listings within the window skip the
        O(rows + files) reconciliation while every trigger still purges
        retention-eligible rows."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        repo = app.state.project_document_repo
        calls = {"count": 0}
        original = repo.list_all_for_sweep

        async def counting(*args: Any, **kwargs: Any):
            calls["count"] += 1
            return await original(*args, **kwargs)

        monkeypatch.setattr(repo, "list_all_for_sweep", counting)
        monkeypatch.setattr(trash, "_LAST_RECONCILIATION", {})

        project = _create_project(client)
        first_doc = _upload(client, project["id"], "old.txt", b"old")
        _trash(client, project["id"], first_doc["id"])
        _set_trashed_at(first_doc["id"], datetime.now(UTC) - timedelta(days=31))

        first = client.get("/api/trash/documents")
        assert first.status_code == 200
        assert first.json()["total"] == 0
        assert calls["count"] == 1

        second_doc = _upload(client, project["id"], "old2.txt", b"old")
        _trash(client, project["id"], second_doc["id"])
        _set_trashed_at(second_doc["id"], datetime.now(UTC) - timedelta(days=31))

        second = client.get("/api/trash/documents")
        assert second.json()["total"] == 0
        assert calls["count"] == 1

        monkeypatch.setattr(trash, "_RECONCILIATION_MIN_INTERVAL_SECONDS", 0)
        client.get("/api/trash/documents")
        assert calls["count"] == 2

    def test_reconciliation_window_is_per_user(self, tmp_path, monkeypatch):
        app = _build_app(tmp_path)
        client = TestClient(app)
        repo = app.state.project_document_repo
        calls = {"count": 0}
        original = repo.list_all_for_sweep

        async def counting(*args: Any, **kwargs: Any):
            calls["count"] += 1
            return await original(*args, **kwargs)

        monkeypatch.setattr(repo, "list_all_for_sweep", counting)
        monkeypatch.setattr(trash, "_LAST_RECONCILIATION", {})

        client.get("/api/trash/documents", headers=_as_user("user-a"))
        client.get("/api/trash/documents", headers=_as_user("user-b"))

        assert calls["count"] == 2

    def test_503_when_repository_unavailable(self, tmp_path):
        app = _build_app(tmp_path, document_repo=None)
        client = TestClient(app)
        assert client.get("/api/trash/documents").status_code == 503
        assert client.post("/api/trash/documents/x/restore").status_code == 503
        assert client.post("/api/trash/documents/x/purge").status_code == 503
        assert client.post("/api/trash/purge").status_code == 503


class TestRestore:
    def test_restore_defaults_to_origin_project(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])

        response = client.post(f"/api/trash/documents/{doc['id']}/restore")

        assert response.status_code == 200
        payload = response.json()
        assert payload["outcome"] == "restored"
        assert payload["document"]["id"] == doc["id"]
        assert client.get(f"/api/projects/{project['id']}/documents").json()["total"] == 1
        assert client.get("/api/trash/documents").json()["total"] == 0

    def test_restore_reports_merged_when_target_serves_identical_bytes(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        old = _upload(client, project["id"], "report.txt", b"same bytes")
        _trash(client, project["id"], old["id"])
        new = _upload(client, project["id"], "report.txt", b"same bytes")

        response = client.post(f"/api/trash/documents/{old['id']}/restore")

        assert response.status_code == 200
        payload = response.json()
        assert payload["outcome"] == "merged"
        assert payload["document"]["id"] == new["id"]
        assert client.get("/api/trash/documents").json()["total"] == 0
        assert client.get(f"/api/projects/{project['id']}/documents").json()["total"] == 1

    def test_restore_into_explicit_target(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        origin = _create_project(client, name="Origin")
        target = _create_project(client, name="Target")
        doc = _upload(client, origin["id"], "a.txt", b"hello")
        _trash(client, origin["id"], doc["id"])

        response = client.post(f"/api/trash/documents/{doc['id']}/restore", json={"project_id": target["id"]})

        assert response.status_code == 200
        assert response.json()["outcome"] == "restored"
        assert client.get(f"/api/projects/{target['id']}/documents").json()["total"] == 1

    def test_restore_without_valid_target_is_404(self, tmp_path):
        """Origin gone or archived + no body ⇒ 404 (the UI offers the picker)."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        gone = _create_project(client, name="Gone")
        archived = _create_project(client, name="Archived")
        doc_gone = _upload(client, gone["id"], "a.txt", b"a")
        doc_arch = _upload(client, archived["id"], "b.txt", b"b")
        _trash(client, gone["id"], doc_gone["id"])
        _trash(client, archived["id"], doc_arch["id"])
        assert client.delete(f"/api/projects/{gone['id']}").status_code == 204
        assert client.post(f"/api/projects/{archived['id']}/archive").status_code == 200

        assert client.post(f"/api/trash/documents/{doc_gone['id']}/restore").status_code == 404
        assert client.post(f"/api/trash/documents/{doc_arch['id']}/restore").status_code == 404
        # Explicit valid target still restores them.
        target = _create_project(client, name="T")
        assert client.post(f"/api/trash/documents/{doc_gone['id']}/restore", json={"project_id": target["id"]}).status_code == 200

    def test_restore_into_foreign_or_archived_target_is_404(self, tmp_path):
        """§11: a target the caller does not own is indistinguishable from missing."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        origin = _create_project(client)
        doc = _upload(client, origin["id"], "a.txt", b"hello")
        _trash(client, origin["id"], doc["id"])
        foreign = client.post("/api/projects", json={"name": "Foreign"}, headers=_as_user("user-b")).json()
        archived = _create_project(client, name="A")
        assert client.post(f"/api/projects/{archived['id']}/archive").status_code == 200

        assert client.post(f"/api/trash/documents/{doc['id']}/restore", json={"project_id": foreign["id"]}).status_code == 404
        assert client.post(f"/api/trash/documents/{doc['id']}/restore", json={"project_id": archived["id"]}).status_code == 404
        assert client.post(f"/api/trash/documents/{doc['id']}/restore", json={"project_id": "missing"}).status_code == 404
        # Still trashed after every failed attempt.
        assert client.get("/api/trash/documents").json()["total"] == 1

    def test_restore_of_missing_or_foreign_document_is_404(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])

        assert client.post("/api/trash/documents/missing/restore").status_code == 404
        assert client.post(f"/api/trash/documents/{doc['id']}/restore", headers=_as_user("user-b")).status_code == 404

    def test_restore_with_missing_content_is_409_and_row_stays_trashed(self, tmp_path):
        """§11: 409 content_missing; the row remains trashed, never activated."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])
        row = _get_row(app, doc["id"])
        _original_path(app, row).unlink()

        response = client.post(f"/api/trash/documents/{doc['id']}/restore")

        assert response.status_code == 409
        assert "content_missing" in response.json()["detail"]
        assert client.get("/api/trash/documents").json()["total"] == 1
        assert client.get(f"/api/projects/{project['id']}/documents").json()["total"] == 0


class TestPurge:
    def test_purge_removes_row_and_bytes_then_404s(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])
        row = _get_row(app, doc["id"])
        original = _original_path(app, row)

        assert client.post(f"/api/trash/documents/{doc['id']}/purge").status_code == 204

        assert _get_row(app, doc["id"]) is None
        assert not original.exists()
        assert client.get("/api/trash/documents").json()["total"] == 0
        # Second purge: the row is gone — fail-closed 404.
        assert client.post(f"/api/trash/documents/{doc['id']}/purge").status_code == 404

    def test_purge_rejects_active_foreign_and_missing_documents(self, tmp_path):
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        active = _upload(client, project["id"], "a.txt", b"hello")

        assert client.post(f"/api/trash/documents/{active['id']}/purge").status_code == 404
        assert client.post("/api/trash/documents/missing/purge").status_code == 404

        doc = _upload(client, project["id"], "b.txt", b"b")
        _trash(client, project["id"], doc["id"])
        assert client.post(f"/api/trash/documents/{doc['id']}/purge", headers=_as_user("user-b")).status_code == 404
        # Untouched by all of it.
        assert client.get("/api/trash/documents").json()["total"] == 1

    def test_purge_file_failure_is_500_retryable_and_keeps_row(self, tmp_path, monkeypatch):
        """§11: a non-FileNotFoundError unlink failure rolls back, keeps the
        trashed row, and answers 500 with a retryable message."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])

        real_unlink = Path.unlink

        def flaky_unlink(self: Path, *args, **kwargs):
            if self.name == "a.txt":
                raise OSError("disk full")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", flaky_unlink)
        response = client.post(f"/api/trash/documents/{doc['id']}/purge")

        assert response.status_code == 500
        assert "retried" in response.json()["detail"].lower()
        assert client.get("/api/trash/documents").json()["total"] == 1

    def test_empty_trash_purges_every_trashed_row_regardless_of_age(self, tmp_path):
        """§8.3: Empty trash deletes everything its confirmation listed, so a
        freshly trashed row is purged too — the retention cutoff never gates
        this action (the sweep is the only age-gated purge)."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        fresh = _upload(client, project["id"], "fresh.txt", b"f")
        old = _upload(client, project["id"], "old.txt", b"o")
        kept = _upload(client, project["id"], "kept.txt", b"k")
        _trash(client, project["id"], fresh["id"])
        _trash(client, project["id"], old["id"])
        _set_trashed_at(old["id"], datetime.now(UTC) - timedelta(days=31))
        fresh_path = _original_path(app, _get_row(app, fresh["id"]))

        assert client.post("/api/trash/purge").json() == {"purged": 2}

        assert client.get("/api/trash/documents").json()["total"] == 0
        assert _get_row(app, fresh["id"]) is None
        assert _get_row(app, old["id"]) is None
        assert not fresh_path.exists()
        # Only the trash emptied: the shelf keeps its active row and bytes.
        shelf = client.get(f"/api/projects/{project['id']}/documents").json()
        assert [entry["id"] for entry in shelf["documents"]] == [kept["id"]]

    def test_empty_trash_only_purges_the_callers_rows(self, tmp_path):
        """§11: the empty is owner-scoped — a foreign user's trash survives it."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        mine = _create_project(client)
        theirs = client.post("/api/projects", json={"name": "Theirs"}, headers=_as_user("user-b")).json()
        mine_doc = _upload(client, mine["id"], "mine.txt", b"m")
        their_doc = _upload(client, theirs["id"], "theirs.txt", b"t", headers=_as_user("user-b"))
        _trash(client, mine["id"], mine_doc["id"])
        _trash(client, theirs["id"], their_doc["id"], headers=_as_user("user-b"))

        assert client.post("/api/trash/purge").json() == {"purged": 1}

        assert _get_row(app, mine_doc["id"]) is None
        assert _get_row(app, their_doc["id"], user_id="user-b") is not None

    def test_empty_trash_file_failure_is_500_and_keeps_the_row(self, tmp_path, monkeypatch):
        """§11: a non-FileNotFoundError unlink failure rolls that row back and
        answers 500 with a retryable message instead of reporting success."""
        app = _build_app(tmp_path)
        client = TestClient(app)
        project = _create_project(client)
        doc = _upload(client, project["id"], "a.txt", b"hello")
        _trash(client, project["id"], doc["id"])

        real_unlink = Path.unlink

        def flaky_unlink(self: Path, *args, **kwargs):
            if self.name == "a.txt":
                raise OSError("disk full")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", flaky_unlink)
        response = client.post("/api/trash/purge")

        assert response.status_code == 500
        assert "retried" in response.json()["detail"].lower()
        assert client.get("/api/trash/documents").json()["total"] == 1
