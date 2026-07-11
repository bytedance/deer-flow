import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.routers.artifacts as artifacts_router
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
from deerflow.config.paths import make_safe_user_id

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    request = _make_request()
    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: skill_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/note.txt?download=false")

    assert response.status_code == 200
    assert response.text == "hello"
    assert "content-disposition" not in response.headers


def test_get_artifact_download_true_forces_attachment_for_skill_archive(tmp_path, monkeypatch) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr("notes.txt", "hello")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: skill_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")


def _make_internal_request(owner: str | None, *, system_role: str = INTERNAL_SYSTEM_ROLE) -> Request:
    """A request as it arrives from a trusted internal caller.

    ``system_role`` is stamped onto ``request.state.user`` the way
    ``AuthMiddleware`` does after validating the internal token. When *owner*
    is given it is carried in the owner-user-id header.
    """
    headers: list[tuple[bytes, bytes]] = []
    if owner is not None:
        headers.append((INTERNAL_OWNER_USER_ID_HEADER_NAME.lower().encode(), owner.encode()))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})
    request.state.user = SimpleNamespace(id="default", system_role=system_role)
    return request


def _capture_resolved_user_id(monkeypatch, tmp_path) -> dict:
    """Patch resolve_thread_virtual_path to record the user_id it is called with."""
    artifact_path = tmp_path / "index.html"
    artifact_path.write_text("<html>", encoding="utf-8")
    seen: dict = {}

    def fake_resolve(_thread_id, _path, user_id=None):
        seen["user_id"] = user_id
        return artifact_path

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", fake_resolve)
    return seen


def test_get_artifact_scopes_to_trusted_owner_header(tmp_path, monkeypatch) -> None:
    # An internal caller acting for an owner must resolve the artifact under
    # that owner's storage, not the synthetic internal user.
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request("owner-123")

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] == "owner-123"


def test_get_artifact_normalizes_raw_owner_id_from_trusted_header(tmp_path, monkeypatch) -> None:
    # The trusted header carries the raw platform owner id (channel workers
    # send it unsanitized; see ChannelManager._owner_headers), while run files
    # live under the make_safe_user_id bucket — so a raw id with chars outside
    # [A-Za-z0-9_-] must resolve to the normalized bucket, not the raw one.
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    raw_owner = "ou_7d8a.6e6d@example:id"
    request = _make_internal_request(raw_owner)

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] == make_safe_user_id(raw_owner)
    assert seen["user_id"] != raw_owner


def test_get_artifact_without_owner_header_falls_back_to_effective_user(tmp_path, monkeypatch) -> None:
    # No owner header → no override; resolution falls back to the effective user
    # (user_id=None lets resolve_thread_virtual_path apply its default).
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request(None)

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] is None


def test_get_artifact_ignores_owner_header_for_non_internal_caller(tmp_path, monkeypatch) -> None:
    # The owner header is only trusted for internal callers; a normal user
    # carrying it must not be able to read another user's storage.
    seen = _capture_resolved_user_id(monkeypatch, tmp_path)
    request = _make_internal_request("owner-123", system_role="user")

    asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/index.html", request))

    assert seen["user_id"] is None


def test_skill_archive_preview_rejects_oversized_member_before_decompression(tmp_path) -> None:
    skill_path = tmp_path / "sample.skill"
    payload = b"A" * (artifacts_router.MAX_SKILL_ARCHIVE_MEMBER_BYTES + 1)
    with zipfile.ZipFile(skill_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zip_ref:
        zip_ref.writestr("SKILL.md", payload)

    assert skill_path.stat().st_size < artifacts_router.MAX_SKILL_ARCHIVE_MEMBER_BYTES

    with pytest.raises(HTTPException) as exc_info:
        artifacts_router._extract_file_from_skill_archive(skill_path, "SKILL.md")

    assert exc_info.value.status_code == 413
