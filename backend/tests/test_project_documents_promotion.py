"""Integration tests for Projects Phase 2 Slice C: promotion, attach, thread-files.

Covers ``POST …/documents/from-thread`` (confinement 404s, provenance,
shelf_name rename, dedup), ``POST …/documents/{id}/attach-to-thread/{tid}``
(parity with ordinary uploads across mounted/non-mounted providers, denied
``sandbox:execute``, acquire/sync failure behavior, archived source shelf,
fail-closed 404s, ``content_missing``), ``GET …/thread-files`` (paging,
bounds, truncation, group shape, archived/deleted thread absence), and the
attach-vs-purge staged-copy serialization (§13 concurrency).
"""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.authz import AuthContext, Permissions, SandboxRequestLease
from app.gateway.deps import get_config
from app.gateway.routers import project_documents, project_thread_files, projects, uploads
from deerflow.config.paths import get_paths
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.projects.documents import original_file_path
from deerflow.runtime.user_context import reset_current_user, set_current_user

_STUB_PERMISSIONS: list[str] = [
    Permissions.PROJECTS_READ,
    Permissions.PROJECTS_WRITE,
    Permissions.PROJECTS_DELETE,
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
]

_USER_HEADER = "x-test-user"
_USER = "user-a"


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamp a fake AuthContext and set the user ContextVar per request."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        user_id = request.headers.get(_USER_HEADER, _USER)
        user = SimpleNamespace(id=user_id, system_role="user")
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=list(_STUB_PERMISSIONS))
        token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)


async def _init_db(tmp_path) -> None:
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'docs.db'}", sqlite_dir=str(tmp_path))


def _build_app(tmp_path, *, uploads_config: dict | None = None) -> FastAPI:
    anyio.run(_init_db, tmp_path)
    sf = get_session_factory()
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware)
    app.state.project_repo = ProjectRepository(sf)
    app.state.project_document_repo = ProjectDocumentRepository(sf)
    app.state.thread_store = ThreadMetaRepository(sf)
    cfg = MagicMock()
    cfg.uploads = uploads_config or {}
    app.dependency_overrides[get_config] = lambda: cfg
    app.include_router(projects.router)
    app.include_router(project_documents.router)
    app.include_router(project_thread_files.router)
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


def _upload(client: TestClient, project_id: str, name: str, data: bytes, **kwargs) -> Any:
    return client.post(f"/api/projects/{project_id}/documents", files={"file": (name, data)}, **kwargs)


def _seed_thread(app: FastAPI, thread_id: str, *, user_id: str = _USER, project_id: str | None = None, display_name: str | None = None, metadata: dict | None = None) -> dict:
    """Create a thread row directly through the store as ``user_id``."""

    async def _run() -> dict:
        token = set_current_user(SimpleNamespace(id=user_id))
        try:
            return await app.state.thread_store.create(thread_id, project_id=project_id, display_name=display_name, metadata=metadata)
        finally:
            reset_current_user(token)

    return anyio.run(_run)


def _delete_thread(app: FastAPI, thread_id: str, *, user_id: str = _USER) -> None:
    async def _run() -> None:
        token = set_current_user(SimpleNamespace(id=user_id))
        try:
            await app.state.thread_store.delete(thread_id)
        finally:
            reset_current_user(token)

    anyio.run(_run)


def _thread_file(thread_id: str, kind: str, name: str, data: bytes, *, user_id: str = _USER) -> Path:
    """Write a file into a thread's uploads/outputs dir; return its path."""
    from deerflow.config.paths import get_paths

    paths = get_paths()
    directory = paths.sandbox_uploads_dir(thread_id, user_id=user_id) if kind == "upload" else paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_bytes(data)
    return target


def _promote(client: TestClient, project_id: str, headers: dict | None = None, **body) -> Any:
    return client.post(f"/api/projects/{project_id}/documents/from-thread", json=body, headers=headers)


def _attach(client: TestClient, project_id: str, document_id: str, thread_id: str, **kwargs) -> Any:
    return client.post(f"/api/projects/{project_id}/documents/{document_id}/attach-to-thread/{thread_id}", **kwargs)


def _mounted_provider() -> MagicMock:
    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.acquire_async = AsyncMock()
    return provider


def _remote_provider(sandbox: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("ingestion must use acquire_async")
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = sandbox or MagicMock()
    provider.get.return_value = sandbox
    return provider, sandbox


class TestFromThread:
    def test_promote_upload_with_default_name_records_provenance(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            source = _thread_file("thread-1", "upload", "notes.txt", b"hello shelf")

            response = _promote(client, pid, thread_id="thread-1", kind="upload", name="notes.txt")

            assert response.status_code == 201
            body = response.json()
            assert body["deduplicated"] is False
            doc = body["document"]
            assert doc["name"] == "notes.txt"
            assert doc["size_bytes"] == len(b"hello shelf")
            assert doc["source_thread_id"] == "thread-1"
            assert doc["source_kind"] == "upload"
            assert doc["source_name"] == "notes.txt"
            # The source is untouched — a copy, never a move.
            assert source.read_bytes() == b"hello shelf"
            # The shelf serves the copied bytes.
            content = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert content.status_code == 200
            assert content.content == b"hello shelf"
            # Provenance is returned by the shelf listing as well.
            listed = client.get(f"/api/projects/{pid}/documents").json()["documents"]
            assert listed[0]["source_thread_id"] == "thread-1"
            assert listed[0]["source_kind"] == "upload"
            assert listed[0]["source_name"] == "notes.txt"

    def test_promote_output_with_shelf_name_rename(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            _thread_file("thread-1", "output", "result.csv", b"a,b\n1,2\n")

            response = _promote(client, pid, thread_id="thread-1", kind="output", name="result.csv", shelf_name="q3-results.csv")

            assert response.status_code == 201
            doc = response.json()["document"]
            assert doc["name"] == "q3-results.csv"
            # The rename is exactly what makes source_name a consumed column.
            assert doc["source_name"] == "result.csv"
            assert doc["source_kind"] == "output"

    def test_promote_dedup_against_active_shelf_returns_200(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            existing = _upload(client, pid, "first.txt", b"same bytes").json()["document"]
            _seed_thread(app, "thread-1")
            _thread_file("thread-1", "upload", "second.txt", b"same bytes")

            response = _promote(client, pid, thread_id="thread-1", kind="upload", name="second.txt")

            assert response.status_code == 200
            body = response.json()
            assert body["deduplicated"] is True
            # The first writer's row, name and provenance win (§10.9).
            assert body["document"]["id"] == existing["id"]
            assert body["document"]["name"] == "first.txt"
            assert body["document"]["source_thread_id"] is None

    def test_promote_confinement_failure_is_404(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            _thread_file("thread-1", "upload", "real.txt", b"real")

            # Path traversal and subdirectory names are confinement failures.
            assert _promote(client, pid, thread_id="thread-1", kind="upload", name="../real.txt").status_code == 404
            assert _promote(client, pid, thread_id="thread-1", kind="upload", name="sub/real.txt").status_code == 404
            # Missing file.
            assert _promote(client, pid, thread_id="thread-1", kind="upload", name="nope.txt").status_code == 404
            # kind/name mismatch: the file lives in uploads, not outputs.
            assert _promote(client, pid, thread_id="thread-1", kind="output", name="real.txt").status_code == 404
            # Missing thread.
            assert _promote(client, pid, thread_id="thread-nope", kind="upload", name="real.txt").status_code == 404
            # Foreign thread.
            _seed_thread(app, "thread-foreign", user_id="user-b")
            _thread_file("thread-foreign", "upload", "real.txt", b"real", user_id="user-b")
            assert _promote(client, pid, thread_id="thread-foreign", kind="upload", name="real.txt").status_code == 404
            # Missing/foreign project.
            assert _promote(client, "proj-nope", thread_id="thread-1", kind="upload", name="real.txt").status_code == 404
            assert _promote(client, pid, thread_id="thread-1", kind="upload", name="real.txt", headers=_as_user("user-b")).status_code == 404

    def test_promote_into_archived_project_is_404(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            _thread_file("thread-1", "upload", "real.txt", b"real")
            assert client.post(f"/api/projects/{pid}/archive").status_code == 200

            assert _promote(client, pid, thread_id="thread-1", kind="upload", name="real.txt").status_code == 404

    def test_promote_rejects_a_symlinked_kind_dir_escaping_thread_storage(self, tmp_path):
        """A planted outputs symlink pointing outside thread storage must not
        become the trusted base: the source never resolves (404) and the
        external file never lands on the shelf (§11)."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            external = tmp_path / "external"
            external.mkdir()
            (external / "secret.txt").write_bytes(b"external secret")
            outputs_dir = get_paths().sandbox_outputs_dir("thread-1", user_id=_USER)
            outputs_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                outputs_dir.symlink_to(external)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    pytest.skip("Windows symlink privilege is not available")
                raise

            response = _promote(client, pid, thread_id="thread-1", kind="output", name="secret.txt")

            assert response.status_code == 404
            assert client.get(f"/api/projects/{pid}/documents").json()["total"] == 0

    def test_promote_follows_an_in_root_symlinked_kind_dir(self, tmp_path):
        """A kind dir symlinked to a sibling INSIDE the thread's storage keeps
        working — the same behavior as virtual-path resolution (the resolved
        path stays under the trusted thread root)."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1")
            paths = get_paths()
            real = paths.sandbox_user_data_dir("thread-1", user_id=_USER) / "real-outputs"
            real.mkdir(parents=True)
            (real / "inside.txt").write_bytes(b"inside bytes")
            outputs_dir = paths.sandbox_outputs_dir("thread-1", user_id=_USER)
            try:
                outputs_dir.symlink_to(real)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    pytest.skip("Windows symlink privilege is not available")
                raise

            response = _promote(client, pid, thread_id="thread-1", kind="output", name="inside.txt")

            assert response.status_code == 201
            doc = response.json()["document"]
            assert doc["name"] == "inside.txt"
            assert client.get(f"/api/projects/{pid}/documents/{doc['id']}/content").text == "inside bytes"


class TestAttach:
    def test_attach_mounted_provider_copies_without_sync(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.txt", b"attach me").json()["document"]
            _seed_thread(app, "thread-1")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            body = response.json()
            assert body == {
                "filename": "report.txt",
                "size_bytes": len(b"attach me"),
                "virtual_path": "/mnt/user-data/uploads/report.txt",
                "artifact_url": "/api/threads/thread-1/artifacts/mnt/user-data/uploads/report.txt",
            }
            target = _thread_uploads("thread-1") / "report.txt"
            assert target.read_bytes() == b"attach me"
            provider.acquire_async.assert_not_awaited()
            provider.get.assert_not_called()
            # The shelf row and its bytes are untouched by the attach.
            assert client.get(f"/api/projects/{pid}/documents/{doc['id']}/content").status_code == 200

    def test_attach_non_mounted_syncs_original_and_converted(self, tmp_path):
        app = _build_app(tmp_path, uploads_config={"auto_convert_documents": True})
        provider, sandbox = _remote_provider()

        async def fake_convert(file_path: Path, output_path: Path | None = None) -> Path:
            md_path = output_path if output_path is not None else file_path.with_suffix(".md")
            md_path.write_text("converted", encoding="utf-8")
            return md_path

        with (
            TestClient(app) as client,
            patch.object(uploads, "get_sandbox_provider", return_value=provider),
            patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        ):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.pdf", b"pdf-bytes").json()["document"]
            _seed_thread(app, "thread-1")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            assert response.json()["filename"] == "report.pdf"
            assert (_thread_uploads("thread-1") / "report.pdf").read_bytes() == b"pdf-bytes"
            assert (_thread_uploads("thread-1") / "report.md").read_text(encoding="utf-8") == "converted"
            sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.pdf", b"pdf-bytes")
            sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.md", b"converted")

    def test_attach_makes_files_sandbox_readable(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "readable.txt", b"read me").json()["document"]
            _seed_thread(app, "thread-1")

            assert _attach(client, pid, doc["id"], "thread-1").status_code == 200

            mode = stat.S_IMODE(os.stat(_thread_uploads("thread-1") / "readable.txt").st_mode)
            assert mode & 0o444 == 0o444

    def test_attach_denied_sandbox_execute_retains_host_upload_without_allocation(self, tmp_path):
        app = _build_app(tmp_path)
        provider, sandbox = _remote_provider()
        denied_lease = SandboxRequestLease(sandbox=None, sandbox_id=None, denied=True, owner_id=None, provider=None)
        with (
            TestClient(app) as client,
            patch.object(uploads, "get_sandbox_provider", return_value=provider),
            patch.object(uploads, "try_acquire_sandbox_for_request", AsyncMock(return_value=denied_lease)) as acquire,
        ):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "local-only.txt", b"host bytes").json()["document"]
            _seed_thread(app, "thread-1")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            assert (_thread_uploads("thread-1") / "local-only.txt").read_bytes() == b"host bytes"
            acquire.assert_awaited_once()
            # Denial skipped allocation entirely: no sandbox, no sync.
            provider.acquire_async.assert_not_awaited()
            provider.get.assert_not_called()
            sandbox.update_file.assert_not_called()

    def test_attach_acquire_failure_is_500_before_writing(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _remote_provider()[0]
        lost_lease = SandboxRequestLease(sandbox=None, sandbox_id="aio-1", denied=False, owner_id="gateway:upload:x", provider=provider)
        release = AsyncMock()
        with (
            TestClient(app) as client,
            patch.object(SandboxRequestLease, "release", release),
            patch.object(uploads, "get_sandbox_provider", return_value=provider),
            patch.object(uploads, "try_acquire_sandbox_for_request", AsyncMock(return_value=lost_lease)),
        ):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "never.txt", b"data").json()["document"]
            _seed_thread(app, "thread-1")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 500
            assert not (_thread_uploads("thread-1") / "never.txt").exists()
            # open() raised after acquiring the lease; the route's cleanup
            # scope released the partially acquired holder.
            release.assert_awaited_once()

    def test_attach_sync_failure_retains_host_file(self, tmp_path):
        app = _build_app(tmp_path)
        provider, sandbox = _remote_provider()
        sandbox.update_file.side_effect = RuntimeError("sandbox unreachable")
        with TestClient(app, raise_server_exceptions=False) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "kept.txt", b"stays on host").json()["document"]
            _seed_thread(app, "thread-1")

            response = _attach(client, pid, doc["id"], "thread-1")

            # Ordinary uploads behavior for sync-phase failures: the request
            # fails but the host file stays in the thread uploads dir.
            assert response.status_code == 500
            assert (_thread_uploads("thread-1") / "kept.txt").read_bytes() == b"stays on host"

    def test_attach_from_archived_source_project_succeeds(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "archived.txt", b"from archive").json()["document"]
            _seed_thread(app, "thread-1")
            assert client.post(f"/api/projects/{pid}/archive").status_code == 200

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            assert (_thread_uploads("thread-1") / "archived.txt").read_bytes() == b"from archive"
            # The archived shelf is read, never mutated: the row stays active.
            listed = client.get(f"/api/projects/{pid}/documents").json()
            assert listed["total"] == 1

    def test_attach_fail_closed_404s(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "a.txt", b"a").json()["document"]
            _seed_thread(app, "thread-1")

            # Missing/foreign document, wrong project shelf, missing thread.
            assert _attach(client, pid, "doc-nope", "thread-1").status_code == 404
            other_pid = _create_project(client, name="Q")["id"]
            assert _attach(client, other_pid, doc["id"], "thread-1").status_code == 404
            assert _attach(client, pid, doc["id"], "thread-nope").status_code == 404
            # Foreign target thread the caller cannot write.
            _seed_thread(app, "thread-foreign", user_id="user-b")
            assert _attach(client, pid, doc["id"], "thread-foreign").status_code == 404
            # Foreign caller sees nothing.
            assert _attach(client, pid, doc["id"], "thread-1", headers=_as_user("user-b")).status_code == 404
            # Trashed documents are not attachable.
            assert client.delete(f"/api/projects/{pid}/documents/{doc['id']}").status_code == 204
            assert _attach(client, pid, doc["id"], "thread-1").status_code == 404
            # Nothing was ever written to the target thread.
            assert not (_thread_uploads("thread-1") / "a.txt").exists()

    def test_attach_missing_content_is_409(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "gone.txt", b"was here").json()["document"]
            _seed_thread(app, "thread-1")
            original_file_path(get_paths(), user_id=_USER, row=doc_row(app, doc["id"])).unlink()

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 409
            assert "content_missing" in response.json()["detail"]
            assert not (_thread_uploads("thread-1") / "gone.txt").exists()


def _thread_uploads(thread_id: str, *, user_id: str = _USER) -> Path:
    return get_paths().sandbox_uploads_dir(thread_id, user_id=user_id)


def doc_row(app: FastAPI, document_id: str, *, user_id: str = _USER) -> dict:
    async def _run() -> dict:
        token = set_current_user(SimpleNamespace(id=user_id))
        try:
            row = await app.state.project_document_repo.get(document_id)
            assert row is not None
            return row
        finally:
            reset_current_user(token)

    return anyio.run(_run)


class TestThreadFiles:
    def test_groups_shape_with_uploads_and_outputs(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1", project_id=pid, display_name="First")
            _seed_thread(app, "thread-2", project_id=pid)
            _thread_file("thread-1", "upload", "in.txt", b"in")
            _thread_file("thread-1", "output", "out.csv", b"out")
            _thread_file("thread-2", "upload", "only.txt", b"only")

            response = client.get(f"/api/projects/{pid}/thread-files")

            assert response.status_code == 200
            body = response.json()
            assert body["truncated"] is False
            assert body["next_offset"] is None
            assert len(body["groups"]) == 2
            by_id = {g["thread_id"]: g for g in body["groups"]}
            assert by_id["thread-1"]["display_name"] == "First"
            assert by_id["thread-1"]["updated_at"]
            files = {(f["kind"], f["name"]): f for f in by_id["thread-1"]["files"]}
            assert set(files) == {("upload", "in.txt"), ("output", "out.csv")}
            upload_entry = files[("upload", "in.txt")]
            assert upload_entry["size_bytes"] == 2
            assert upload_entry["modified_at"]
            assert upload_entry["artifact_url"] == "/api/threads/thread-1/artifacts/mnt/user-data/uploads/in.txt"
            output_entry = files[("output", "out.csv")]
            assert output_entry["artifact_url"] == "/api/threads/thread-1/artifacts/mnt/user-data/outputs/out.csv"
            assert [f["name"] for f in by_id["thread-2"]["files"]] == ["only.txt"]
            # Threads outside the project never appear.
            _seed_thread(app, "thread-outsider")
            _thread_file("thread-outsider", "upload", "stray.txt", b"stray")
            assert len(client.get(f"/api/projects/{pid}/thread-files").json()["groups"]) == 2

    def test_paging_with_next_offset_cursor(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            for i in range(3):
                _seed_thread(app, f"thread-{i}", project_id=pid)
                _thread_file(f"thread-{i}", "upload", f"f{i}.txt", b"x")

            page1 = client.get(f"/api/projects/{pid}/thread-files?thread_limit=2").json()
            assert len(page1["groups"]) == 2
            assert page1["next_offset"] == 2
            page2 = client.get(f"/api/projects/{pid}/thread-files?thread_limit=2&offset=2").json()
            assert len(page2["groups"]) == 1
            assert page2["next_offset"] is None
            page1_ids = {g["thread_id"] for g in page1["groups"]}
            page2_ids = {g["thread_id"] for g in page2["groups"]}
            assert page1_ids.isdisjoint(page2_ids)
            assert page1_ids | page2_ids == {"thread-0", "thread-1", "thread-2"}

    def test_truncated_flag_reported_never_silent(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1", project_id=pid)
            for i in range(3):
                _thread_file("thread-1", "upload", f"f{i}.txt", b"x")

            body = client.get(f"/api/projects/{pid}/thread-files?file_limit=2").json()
            assert body["truncated"] is True
            assert body["groups"][0]["truncated"] is True
            assert len(body["groups"][0]["files"]) == 2
            # Within the cap there is no truncation.
            body = client.get(f"/api/projects/{pid}/thread-files?file_limit=3").json()
            assert body["truncated"] is False
            assert len(body["groups"][0]["files"]) == 3

    def test_per_group_truncated_flags_identify_the_cut_thread(self, tmp_path):
        """A group over file_limit reports truncated=true while an under-limit
        group in the same response reports false; the envelope stays the OR."""
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-full", project_id=pid)
            _seed_thread(app, "thread-light", project_id=pid)
            for i in range(3):
                _thread_file("thread-full", "upload", f"f{i}.txt", b"x")
            _thread_file("thread-light", "upload", "only.txt", b"x")

            body = client.get(f"/api/projects/{pid}/thread-files?file_limit=2").json()
            assert body["truncated"] is True
            by_id = {g["thread_id"]: g for g in body["groups"]}
            assert by_id["thread-full"]["truncated"] is True
            assert len(by_id["thread-full"]["files"]) == 2
            assert by_id["thread-light"]["truncated"] is False
            assert len(by_id["thread-light"]["files"]) == 1

            body = client.get(f"/api/projects/{pid}/thread-files?file_limit=3").json()
            assert body["truncated"] is False
            assert all(g["truncated"] is False for g in body["groups"])

    def test_query_bounds_are_422(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            assert client.get(f"/api/projects/{pid}/thread-files?thread_limit=0").status_code == 422
            assert client.get(f"/api/projects/{pid}/thread-files?thread_limit=51").status_code == 422
            assert client.get(f"/api/projects/{pid}/thread-files?file_limit=0").status_code == 422
            assert client.get(f"/api/projects/{pid}/thread-files?file_limit=201").status_code == 422
            assert client.get(f"/api/projects/{pid}/thread-files?offset=-1").status_code == 422

    def test_archived_and_deleted_threads_are_absent(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-live", project_id=pid)
            _seed_thread(app, "thread-archived", project_id=pid, metadata={"deerflow_archived": True})
            _seed_thread(app, "thread-deleted", project_id=pid)
            _thread_file("thread-live", "upload", "live.txt", b"x")
            _thread_file("thread-archived", "upload", "arch.txt", b"x")
            _thread_file("thread-deleted", "upload", "del.txt", b"x")
            _delete_thread(app, "thread-deleted")

            body = client.get(f"/api/projects/{pid}/thread-files").json()
            assert [g["thread_id"] for g in body["groups"]] == ["thread-live"]

    def test_archived_project_keeps_read_access(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _seed_thread(app, "thread-1", project_id=pid)
            _thread_file("thread-1", "upload", "a.txt", b"a")
            assert client.post(f"/api/projects/{pid}/archive").status_code == 200

            response = client.get(f"/api/projects/{pid}/thread-files")
            assert response.status_code == 200
            assert len(response.json()["groups"]) == 1

    def test_fail_closed_404s(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            assert client.get("/api/projects/proj-nope/thread-files").status_code == 404
            assert client.get(f"/api/projects/{pid}/thread-files", headers=_as_user("user-b")).status_code == 404


class _SimulatedPurge:
    """Slice-D-style purge against the same engine: lock the document row,
    unlink original + derived, delete the row, commit — one transaction."""

    def __init__(self, app: FastAPI, document_id: str, *, user_id: str = _USER) -> None:
        self.app = app
        self.document_id = document_id
        self.user_id = user_id
        self.row_locked = threading.Event()
        self.proceed = threading.Event()
        self.result: bool | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = anyio.run(self._purge)
        except BaseException as exc:  # surfaced in assertions
            self.error = exc

    async def _purge(self) -> bool:
        from deerflow.persistence.projects.model import ProjectDocumentRow

        token = set_current_user(SimpleNamespace(id=self.user_id))
        try:
            sf = get_session_factory()
            async with sf() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == self.document_id).with_for_update())).scalar_one_or_none()
                if locked is None or locked.trashed_at is not None:
                    await session.rollback()
                    return False
                row = ProjectDocumentRepository._row_to_dict(locked)
                self.row_locked.set()
                if not self.proceed.wait(timeout=10):
                    raise AssertionError("test barrier timed out")
                paths = get_paths()
                original = original_file_path(paths, user_id=self.user_id, row=row)
                original.unlink(missing_ok=True)
                derived = original.parent.parent / "derived" / "converted.md"
                derived.unlink(missing_ok=True)
                await session.delete(locked)
                await session.commit()
                return True
        finally:
            reset_current_user(token)


class TestAttachUniqueNaming:
    """Attach never overwrites an existing thread upload: the claimed
    destination is seeded from the thread's current files, so a collision
    lands under a unique ``_N`` name and the response reflects it."""

    def test_attach_with_same_named_thread_upload_claims_a_unique_name(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.txt", b"shelf bytes").json()["document"]
            _seed_thread(app, "thread-1")
            existing = _thread_file("thread-1", "upload", "report.txt", b"original thread bytes")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            body = response.json()
            assert body["filename"] == "report_1.txt"
            assert body["virtual_path"] == "/mnt/user-data/uploads/report_1.txt"
            # The pre-existing thread file is untouched; the shelf copy
            # landed under the claimed unique name.
            assert existing.read_bytes() == b"original thread bytes"
            assert (_thread_uploads("thread-1") / "report_1.txt").read_bytes() == b"shelf bytes"

    def test_two_same_named_shelf_docs_attach_as_two_distinct_files(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            first = _upload(client, pid, "dup.txt", b"first").json()["document"]
            second = _upload(client, pid, "dup.txt", b"second").json()["document"]
            assert first["id"] != second["id"]
            _seed_thread(app, "thread-1")

            r1 = _attach(client, pid, first["id"], "thread-1")
            r2 = _attach(client, pid, second["id"], "thread-1")

            assert r1.json()["filename"] == "dup.txt"
            assert r2.json()["filename"] == "dup_1.txt"
            assert (_thread_uploads("thread-1") / "dup.txt").read_bytes() == b"first"
            assert (_thread_uploads("thread-1") / "dup_1.txt").read_bytes() == b"second"

    def test_attach_sync_targets_the_claimed_unique_name(self, tmp_path):
        app = _build_app(tmp_path)
        provider, sandbox = _remote_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.txt", b"shelf bytes").json()["document"]
            _seed_thread(app, "thread-1")
            _thread_file("thread-1", "upload", "report.txt", b"original thread bytes")

            response = _attach(client, pid, doc["id"], "thread-1")

            assert response.status_code == 200
            assert response.json()["filename"] == "report_1.txt"
            sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report_1.txt", b"shelf bytes")
            assert sandbox.update_file.call_count == 1


class TestAttachAtomicReservation:
    """Destination claims are reserved atomically (O_EXCL) with next-suffix
    retries: two CONCURRENT same-name ingestions into one thread land as
    ``name.ext`` + ``name_1.ext`` with both byte streams intact — the later
    commit can never overwrite the earlier one."""

    def test_concurrent_attach_same_name_lands_two_intact_files(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            first = _upload(client, pid, "race.txt", b"first-bytes").json()["document"]
            second = _upload(client, pid, "race.txt", b"second-bytes").json()["document"]
            _seed_thread(app, "thread-1")

            # Both sessions seed from the SAME pre-race listing before either
            # can reserve, so both claim "race.txt"; the O_EXCL reservation
            # serializes them and the loser retries as "race_1.txt".
            real_list = uploads.list_files_in_dir
            seeded = threading.Barrier(2)

            def gated_list(directory):
                listing = real_list(directory)
                seeded.wait(timeout=15)
                return listing

            responses: dict[str, Any] = {}

            def do_attach(key: str, doc_id: str) -> None:
                responses[key] = _attach(client, pid, doc_id, "thread-1")

            with patch.object(uploads, "list_files_in_dir", gated_list):
                threads = [threading.Thread(target=do_attach, args=(key, doc["id"])) for key, doc in (("a", first), ("b", second))]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)

            assert all(not thread.is_alive() for thread in threads)
            assert {r.status_code for r in responses.values()} == {200}
            assert sorted(r.json()["filename"] for r in responses.values()) == ["race.txt", "race_1.txt"]
            contents = {path.name: path.read_bytes() for path in _thread_uploads("thread-1").iterdir()}
            assert sorted(contents) == ["race.txt", "race_1.txt"]
            assert sorted(contents.values()) == sorted([b"first-bytes", b"second-bytes"])

    def test_concurrent_attach_reserves_markdown_companions_atomically(self, tmp_path):
        app = _build_app(tmp_path, uploads_config={"auto_convert_documents": True})
        provider = _mounted_provider()

        async def fake_convert(file_path: Path, output_path: Path | None = None) -> Path:
            md_path = output_path if output_path is not None else file_path.with_suffix(".md")
            md_path.write_text(f"converted:{file_path.read_bytes().decode()}", encoding="utf-8")
            return md_path

        with (
            TestClient(app) as client,
            patch.object(uploads, "get_sandbox_provider", return_value=provider),
            patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)),
        ):
            pid = _create_project(client)["id"]
            first = _upload(client, pid, "report.pdf", b"first-pdf").json()["document"]
            second = _upload(client, pid, "report.pdf", b"second-pdf").json()["document"]
            _seed_thread(app, "thread-1")

            real_list = uploads.list_files_in_dir
            seeded = threading.Barrier(2)

            def gated_list(directory):
                listing = real_list(directory)
                seeded.wait(timeout=15)
                return listing

            responses: dict[str, Any] = {}

            def do_attach(key: str, doc_id: str) -> None:
                responses[key] = _attach(client, pid, doc_id, "thread-1")

            with patch.object(uploads, "list_files_in_dir", gated_list):
                threads = [threading.Thread(target=do_attach, args=(key, doc["id"])) for key, doc in (("a", first), ("b", second))]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)

            assert all(not thread.is_alive() for thread in threads)
            assert {r.status_code for r in responses.values()} == {200}
            contents = {path.name: path.read_bytes() for path in _thread_uploads("thread-1").iterdir()}
            assert sorted(contents) == ["report.md", "report.pdf", "report_1.md", "report_1.pdf"]
            assert sorted(contents[name] for name in ("report.pdf", "report_1.pdf")) == sorted([b"first-pdf", b"second-pdf"])
            # Each companion carries its own source's conversion — neither
            # companion overwrote the other.
            companions = sorted((contents["report.md"], contents["report_1.md"]))
            assert companions == sorted([b"converted:first-pdf", b"converted:second-pdf"])


class TestAttachVsPurgeSerialization:
    """§13 concurrency: attach either stages its copy before purge unlinks, or
    finds the row gone and 404s — never a partially copied file."""

    def test_purge_first_attach_404s_with_no_partial_copy(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "race.txt", b"race bytes").json()["document"]
            _seed_thread(app, "thread-1")

            purge = _SimulatedPurge(app, doc["id"])
            purge_thread = threading.Thread(target=purge.run)
            purge_thread.start()
            assert purge.row_locked.wait(timeout=10)

            # The attach attempt blocks on the purge's write lock (SQLite
            # BEGIN IMMEDIATE + busy timeout), then finds the row gone.
            attach_holder: dict[str, Any] = {}

            def do_attach() -> None:
                attach_holder["response"] = _attach(client, pid, doc["id"], "thread-1")

            attach_thread = threading.Thread(target=do_attach)
            attach_thread.start()
            # Let the attach reach its lock wait, then let purge finish.
            threading.Event().wait(0.3)
            purge.proceed.set()
            purge_thread.join(timeout=15)
            attach_thread.join(timeout=15)

            assert purge.error is None and purge.result is True
            assert attach_holder["response"].status_code == 404
            target = _thread_uploads("thread-1") / "race.txt"
            assert not target.exists()

    def test_attach_first_stages_complete_copy_before_purge_unlinks(self, tmp_path):
        app = _build_app(tmp_path)
        provider = _mounted_provider()
        with TestClient(app) as client, patch.object(uploads, "get_sandbox_provider", return_value=provider):
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "race.txt", b"race bytes").json()["document"]
            _seed_thread(app, "thread-1")

            # Hold the attach's under-lock copy at a barrier while the purge
            # attempt starts; the purge then waits for the attach's commit.
            import deerflow.projects.documents as documents_mod

            real_copy = documents_mod._copy_original_under_lock
            copy_entered = threading.Event()
            purge_started = threading.Event()

            def gated_copy(paths, staging_path, *, user_id, row) -> None:
                copy_entered.set()
                if not purge_started.wait(timeout=10):
                    raise AssertionError("test barrier timed out")
                real_copy(paths, staging_path, user_id=user_id, row=row)

            purge = _SimulatedPurge(app, doc["id"])
            purge.proceed.set()  # no barrier needed inside purge itself

            with patch.object(documents_mod, "_copy_original_under_lock", gated_copy):
                attach_holder: dict[str, Any] = {}

                def do_attach() -> None:
                    attach_holder["response"] = _attach(client, pid, doc["id"], "thread-1")

                attach_thread = threading.Thread(target=do_attach)
                attach_thread.start()
                assert copy_entered.wait(timeout=10)

                purge_thread = threading.Thread(target=purge.run)
                purge_thread.start()
                # Give the purge a moment to reach its (blocked) lock wait —
                # it cannot proceed until the attach's transaction commits.
                threading.Event().wait(0.3)
                purge_started.set()
                attach_thread.join(timeout=15)
                purge_thread.join(timeout=15)

            assert attach_holder["response"].status_code == 200
            assert purge.error is None
            # The attach's staged copy completed before purge could unlink:
            # the thread received the full bytes, never a partial file.
            assert (_thread_uploads("thread-1") / "race.txt").read_bytes() == b"race bytes"
