"""Integration tests for the project document shelf API (Phase-2 Slice B).

Upload → list → content → delete-to-trash round trip through the real
routers on a temp SQLite engine, fail-closed 404s for foreign/missing
resources on every route, the archived matrix (§8.4), filename byte
boundaries, dedup status codes, and project delete trashing the shelf.
"""

from __future__ import annotations

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
from app.gateway.routers import project_documents, projects
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
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'docs.db'}", sqlite_dir=str(tmp_path))


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


class TestRoundTrip:
    def test_upload_list_content_delete_round_trip(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            project = _create_project(client)
            pid = project["id"]

            created = _upload(client, pid, "notes.txt", b"hello shelf")
            assert created.status_code == 201
            body = created.json()
            assert body["deduplicated"] is False
            doc = body["document"]
            assert doc["name"] == "notes.txt" and doc["size_bytes"] == 11
            assert doc["source_kind"] == "upload"

            listed = client.get(f"/api/projects/{pid}/documents")
            assert listed.status_code == 200
            payload = listed.json()
            assert payload["total"] == 1
            assert [d["id"] for d in payload["documents"]] == [doc["id"]]

            content = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert content.status_code == 200
            assert content.text == "hello shelf"
            assert "inline" in content.headers["content-disposition"]
            assert content.headers["x-content-type-options"] == "nosniff"

            download = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", params={"download": "true"})
            assert download.status_code == 200
            assert "attachment" in download.headers["content-disposition"]
            assert download.headers["x-content-type-options"] == "nosniff"

            deleted = client.delete(f"/api/projects/{pid}/documents/{doc['id']}")
            assert deleted.status_code == 204

            # Trashed rows are invisible to every endpoint.
            assert client.get(f"/api/projects/{pid}/documents").json()["total"] == 0
            assert client.get(f"/api/projects/{pid}/documents/{doc['id']}/content").status_code == 404
            assert client.delete(f"/api/projects/{pid}/documents/{doc['id']}").status_code == 404

    def test_dedup_hit_returns_200_with_the_first_writers_row(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            first = _upload(client, pid, "first.txt", b"identical bytes")
            assert first.status_code == 201
            second = client.post(f"/api/projects/{pid}/documents", files={"file": ("second.txt", b"identical bytes")})
            assert second.status_code == 200
            body = second.json()
            assert body["deduplicated"] is True
            # First name wins (§10.9); no second row or file was published.
            assert body["document"]["name"] == "first.txt"
            assert body["document"]["id"] == first.json()["document"]["id"]
            assert client.get(f"/api/projects/{pid}/documents").json()["total"] == 1

    def test_reupload_after_trash_creates_a_fresh_row(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            first = _upload(client, pid, "same.txt", b"bytes").json()["document"]
            assert client.delete(f"/api/projects/{pid}/documents/{first['id']}").status_code == 204
            second = _upload(client, pid, "same.txt", b"bytes")
            assert second.status_code == 201
            assert second.json()["document"]["id"] != first["id"]

    def test_same_name_different_content_gets_distinct_ids(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            a = _upload(client, pid, "report.pdf", b"version one").json()["document"]
            b = _upload(client, pid, "report.pdf", b"version two").json()["document"]
            assert a["id"] != b["id"]
            names = {d["id"]: d["name"] for d in client.get(f"/api/projects/{pid}/documents").json()["documents"]}
            assert names == {a["id"]: "report.pdf", b["id"]: "report.pdf"}


class TestListContentMissing:
    """The shelf list reports per-row read-time integrity (§8.3/§11): the
    immutable ORIGINAL is the anchor — missing or size-mismatched ⇒
    ``content_missing: true``; a missing derived companion alone is fine."""

    def test_missing_or_truncated_original_flags_content_missing(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import original_file_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            _upload(client, pid, "healthy.txt", b"fine")
            missing = _upload(client, pid, "missing.txt", b"was here").json()["document"]
            truncated = _upload(client, pid, "truncated.txt", b"full bytes").json()["document"]
            # No derived companion exists (conversion is lazy): the original
            # alone decides integrity.
            _upload(client, pid, "no-companion.txt", b"original only")

            async def _damage() -> None:
                repo = app.state.project_document_repo
                paths = get_paths()
                row = await repo.get(missing["id"], user_id="user-a")
                original_file_path(paths, user_id="user-a", row=row).unlink()
                row = await repo.get(truncated["id"], user_id="user-a")
                original_file_path(paths, user_id="user-a", row=row).write_bytes(b"cut")

            anyio.run(_damage)
            body = client.get(f"/api/projects/{pid}/documents").json()
            by_name = {d["name"]: d for d in body["documents"]}
            assert by_name["healthy.txt"]["content_missing"] is False
            assert by_name["missing.txt"]["content_missing"] is True
            assert by_name["truncated.txt"]["content_missing"] is True
            assert by_name["no-companion.txt"]["content_missing"] is False


class TestUploadValidation:
    def test_filename_255_utf8_bytes_accepted_256_rejected(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            # 252 ASCII chars + one 3-byte CJK char = 255 UTF-8 bytes exactly.
            name_255 = "a" * 252 + "项"
            assert len(name_255.encode("utf-8")) == 255
            ok = _upload(client, pid, name_255, b"x")
            assert ok.status_code == 201
            assert ok.json()["document"]["name"] == name_255

            name_256 = "a" * 253 + "项"
            assert len(name_256.encode("utf-8")) == 256
            rejected = _upload(client, pid, name_256, b"x")
            assert rejected.status_code == 400

    def test_explicit_name_field_is_validated_and_wins(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            renamed = client.post(f"/api/projects/{pid}/documents", files={"file": ("raw.txt", b"x")}, data={"name": "display.txt"})
            assert renamed.status_code == 201
            assert renamed.json()["document"]["name"] == "display.txt"

            # An empty name field is indistinguishable from omission on the
            # wire and falls back to the multipart filename; whitespace-only
            # and separator-bearing names are rejected server-side.
            for bad in ("   ", "a/b.txt", "a\\b.txt", ".."):
                rejected = client.post(f"/api/projects/{pid}/documents", files={"file": ("raw.txt", b"x")}, data={"name": bad})
                assert rejected.status_code == 400, bad

    def test_empty_file_is_400(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            assert _upload(client, pid, "empty.txt", b"").status_code == 400

    def test_pagination_bounds_follow_the_422_convention(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            assert client.get(f"/api/projects/{pid}/documents", params={"limit": 0}).status_code == 422
            assert client.get(f"/api/projects/{pid}/documents", params={"limit": 1001}).status_code == 422
            assert client.get(f"/api/projects/{pid}/documents", params={"offset": -1}).status_code == 422
            assert client.get(f"/api/projects/{pid}/documents", params={"limit": 1, "offset": 0}).status_code == 200

    def test_content_missing_is_an_explicit_error(self, tmp_path):
        from deerflow.projects.documents import original_file_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "lost.txt", b"was here").json()["document"]

            async def _remove() -> None:
                token = set_current_user(SimpleNamespace(id="user-a"))
                try:
                    row = await app.state.project_document_repo.get(doc["id"])
                    original_file_path(__import__("deerflow.config.paths", fromlist=["get_paths"]).get_paths(), user_id="user-a", row=row).unlink()
                finally:
                    reset_current_user(token)

            anyio.run(_remove)
            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 409
            assert "content_missing" in response.json()["detail"]


class TestFailClosed:
    def test_404_for_missing_or_foreign_resources_on_every_route(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "a.txt", b"a").json()["document"]

            # Missing project (the POST carries its required multipart file).
            assert client.get("/api/projects/nope/documents").status_code == 404
            assert client.post("/api/projects/nope/documents", files={"file": ("a.txt", b"a")}).status_code == 404
            assert client.get("/api/projects/nope/documents/x/content").status_code == 404
            assert client.delete("/api/projects/nope/documents/x").status_code == 404

            # Missing document.
            assert client.get(f"/api/projects/{pid}/documents/nope/content").status_code == 404
            assert client.delete(f"/api/projects/{pid}/documents/nope").status_code == 404

            # Foreign user sees nothing, anywhere.
            foreign = _as_user("user-b")
            assert client.get(f"/api/projects/{pid}/documents", headers=foreign).status_code == 404
            assert _upload(client, pid, "b.txt", b"b", headers=foreign).status_code == 404
            assert client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", headers=foreign).status_code == 404
            assert client.delete(f"/api/projects/{pid}/documents/{doc['id']}", headers=foreign).status_code == 404

    def test_503_when_document_repo_unavailable(self, tmp_path):
        app = _build_app(tmp_path, document_repo=None)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            assert client.get(f"/api/projects/{pid}/documents").status_code == 503
            assert _upload(client, pid, "a.txt", b"a").status_code == 503
            assert client.get(f"/api/projects/{pid}/documents/x/content").status_code == 503
            assert client.delete(f"/api/projects/{pid}/documents/x").status_code == 503


class TestArchivedMatrix:
    def test_archived_shelf_reads_work_but_mutations_are_404(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "a.txt", b"alpha").json()["document"]
            assert client.post(f"/api/projects/{pid}/archive").status_code == 200

            # Reads stay available (§8.4).
            assert client.get(f"/api/projects/{pid}/documents").json()["total"] == 1
            assert client.get(f"/api/projects/{pid}/documents/{doc['id']}/content").status_code == 200

            # Mutations fail closed.
            assert _upload(client, pid, "b.txt", b"b").status_code == 404
            assert client.delete(f"/api/projects/{pid}/documents/{doc['id']}").status_code == 404

            # Restore re-opens the shelf.
            assert client.post(f"/api/projects/{pid}/restore").status_code == 200
            assert _upload(client, pid, "b.txt", b"b").status_code == 201
            assert client.delete(f"/api/projects/{pid}/documents/{doc['id']}").status_code == 204


class TestProjectDeleteTrashesShelf:
    def test_delete_project_moves_shelf_to_trash_in_same_transaction(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client, name="Doomed")["id"]
            a = _upload(client, pid, "a.txt", b"a").json()["document"]
            b = _upload(client, pid, "b.txt", b"b").json()["document"]

            assert client.delete(f"/api/projects/{pid}").status_code == 204

            async def _check() -> list[dict]:
                token = set_current_user(SimpleNamespace(id="user-a"))
                try:
                    repo = app.state.project_document_repo
                    out = []
                    for doc_id in (a["id"], b["id"]):
                        out.append(await repo.get(doc_id, include_trashed=True))
                    return out
                finally:
                    reset_current_user(token)

            rows = anyio.run(_check)
            for row in rows:
                assert row is not None and row["trashed_at"]
                assert row["trash_origin"] == {"project_id": pid, "project_name": "Doomed"}
            # No active row may reference the deleted project.
            assert client.get(f"/api/projects/{pid}/documents").status_code == 404


class TestActiveContentForcedToDownload:
    """Active content on the app origin would run script, so it is always an
    attachment (same semantics as the artifacts router) — even with
    ``download=false`` — while passive text and the converted-markdown
    companion stay inline."""

    def test_html_served_as_attachment_with_html_media_type(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "page.html", b"<script>alert(1)</script>").json()["document"]

            for params in ({}, {"download": "false"}, {"download": "true"}):
                response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", params=params)
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/html")
                assert "attachment" in response.headers["content-disposition"]

    def test_xml_family_types_served_as_attachments(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            # ``+xml`` subtypes count as active content (SVG carries script;
            # XHTML is namespaced HTML).
            for name, data in (
                ("icon.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                ("page.xhtml", b'<html xmlns="http://www.w3.org/1999/xhtml"/>'),
                ("feed.xml", b"<?xml version='1.0'?><rss/>"),
            ):
                doc = _upload(client, pid, name, data).json()["document"]
                response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
                assert response.status_code == 200, name
                assert "attachment" in response.headers["content-disposition"], name

    def test_passive_text_stays_inline(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "notes.txt", b"hello").json()["document"]

            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/plain")
            assert "inline" in response.headers["content-disposition"]

            download = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", params={"download": "true"})
            assert "attachment" in download.headers["content-disposition"]

    def test_converted_markdown_companion_stays_inline(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import converted_markdown_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.html", b"<p>hi</p>").json()["document"]

            async def _row() -> dict:
                row = await app.state.project_document_repo.get(doc["id"], user_id="user-a")
                assert row is not None
                return row

            derived = converted_markdown_path(get_paths(), user_id="user-a", row=anyio.run(_row))
            derived.parent.mkdir(parents=True, exist_ok=True)
            derived.write_text("# converted")

            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/markdown")
            assert "inline" in response.headers["content-disposition"]


class TestInlineViewableBinaries:
    """Browser-viewable binaries (PDF, image, audio, video) serve inline with
    ``download=false`` — the sandboxed preview iframe navigates to this
    endpoint — while ``download=true`` and active content stay attachments."""

    def test_pdf_image_video_are_inline_when_not_downloading(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            for name, data, media_type in (
                ("report.pdf", b"%PDF-1.4\nfake", "application/pdf"),
                ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png"),
                ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4"),
            ):
                doc = _upload(client, pid, name, data).json()["document"]
                response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
                assert response.status_code == 200, name
                assert response.headers["content-type"].startswith(media_type), name
                assert "inline" in response.headers["content-disposition"], name

                download = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", params={"download": "true"})
                assert "attachment" in download.headers["content-disposition"], name


class TestContentEndpointOriginalIntegrity:
    """The derived companion is served only while its immutable ORIGINAL
    validates (existence AND recorded size, §6.2/§8.3) — a truncated original
    behind a cached conversion is ``content_missing``, never a healthy
    preview."""

    def test_cached_derived_with_truncated_original_is_content_missing(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import converted_markdown_path, original_file_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.html", b"<p>hi</p>").json()["document"]

            async def _plant_and_truncate() -> None:
                row = await app.state.project_document_repo.get(doc["id"], user_id="user-a")
                assert row is not None
                paths = get_paths()
                derived = converted_markdown_path(paths, user_id="user-a", row=row)
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("# converted")
                original_file_path(paths, user_id="user-a", row=row).write_bytes(b"<p")

            anyio.run(_plant_and_truncate)
            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 409
            assert "content_missing" in response.json()["detail"]

    def test_cached_derived_with_valid_original_is_served(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import converted_markdown_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.html", b"<p>hi</p>").json()["document"]

            async def _plant() -> None:
                row = await app.state.project_document_repo.get(doc["id"], user_id="user-a")
                assert row is not None
                derived = converted_markdown_path(get_paths(), user_id="user-a", row=row)
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("# converted")

            anyio.run(_plant)
            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/markdown")
            assert "inline" in response.headers["content-disposition"]


class TestDownloadServesOriginal:
    """The converted-markdown companion is preview-only: ``download=true``
    always serves the immutable ORIGINAL bytes under the original filename,
    so a prior agent read never changes the download's format."""

    def test_download_true_serves_original_bytes_not_the_conversion(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import converted_markdown_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.pdf", b"%PDF-1.4 original").json()["document"]

            async def _plant() -> None:
                row = await app.state.project_document_repo.get(doc["id"], user_id="user-a")
                assert row is not None
                derived = converted_markdown_path(get_paths(), user_id="user-a", row=row)
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("# converted")

            anyio.run(_plant)
            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content", params={"download": "true"})
            assert response.status_code == 200
            assert response.content == b"%PDF-1.4 original"
            disposition = response.headers["content-disposition"]
            assert "attachment" in disposition
            assert "report.pdf" in disposition
            assert "report.pdf.md" not in disposition

    def test_download_false_on_convertible_serves_converted_markdown_inline(self, tmp_path):
        from deerflow.config.paths import get_paths
        from deerflow.projects.documents import converted_markdown_path

        app = _build_app(tmp_path)
        with TestClient(app) as client:
            pid = _create_project(client)["id"]
            doc = _upload(client, pid, "report.pdf", b"%PDF-1.4 original").json()["document"]

            async def _plant() -> None:
                row = await app.state.project_document_repo.get(doc["id"], user_id="user-a")
                assert row is not None
                derived = converted_markdown_path(get_paths(), user_id="user-a", row=row)
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("# converted")

            anyio.run(_plant)
            response = client.get(f"/api/projects/{pid}/documents/{doc['id']}/content")
            assert response.status_code == 200
            assert response.text == "# converted"
            assert response.headers["content-type"].startswith("text/markdown")
            assert "inline" in response.headers["content-disposition"]


class TestDeleteScopesToTheUrlProject:
    """``trash`` predicates on the URL project (§6.1's guarded UPDATE): a
    document of a sibling project is indistinguishable from missing even when
    the caller owns both shelves."""

    def test_cross_project_delete_is_404_and_leaves_the_document_active(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            project_a = _create_project(client, name="A")
            project_b = _create_project(client, name="B")
            doc = _upload(client, project_b["id"], "b.txt", b"b").json()["document"]

            # Both projects owned: the URL project must still match the row.
            assert client.delete(f"/api/projects/{project_a['id']}/documents/{doc['id']}").status_code == 404
            assert client.get(f"/api/projects/{project_b['id']}/documents/{doc['id']}/content").status_code == 200

            # Same-project delete still works.
            assert client.delete(f"/api/projects/{project_b['id']}/documents/{doc['id']}").status_code == 204
            assert client.get(f"/api/projects/{project_b['id']}/documents/{doc['id']}/content").status_code == 404

    def test_restored_row_is_not_trashable_via_the_old_project_url(self, tmp_path):
        app = _build_app(tmp_path)
        with TestClient(app) as client:
            project_a = _create_project(client, name="A")
            project_b = _create_project(client, name="B")
            doc = _upload(client, project_a["id"], "a.txt", b"a").json()["document"]
            assert client.delete(f"/api/projects/{project_a['id']}/documents/{doc['id']}").status_code == 204

            async def _restore_into_b() -> None:
                outcome, _ = await app.state.project_document_repo.restore(doc["id"], target_project_id=project_b["id"], user_id="user-a")
                assert outcome == "restored"

            anyio.run(_restore_into_b)

            # The row now lives on B's shelf: A's URL fails closed and the
            # document stays active under B.
            assert client.delete(f"/api/projects/{project_a['id']}/documents/{doc['id']}").status_code == 404
            assert client.get(f"/api/projects/{project_b['id']}/documents/{doc['id']}/content").status_code == 200
            assert client.delete(f"/api/projects/{project_b['id']}/documents/{doc['id']}").status_code == 204
