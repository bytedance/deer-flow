import asyncio
import hashlib
import stat
import zipfile
from contextlib import asynccontextmanager
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
    assert response.headers["etag"] == f'"{hashlib.sha256(text.encode("utf-8")).hexdigest()}"'


@asynccontextmanager
async def _allow_artifact_write(*_args, **_kwargs):
    yield


class _MountedSandboxProvider:
    uses_thread_data_mounts = True


class _RemoteSandbox:
    def __init__(self, *, fail_next_update: bool = False) -> None:
        self.updates: list[tuple[str, bytes]] = []
        self.fail_next_update = fail_next_update

    def update_file(self, path: str, content: bytes) -> None:
        if self.fail_next_update:
            self.fail_next_update = False
            raise RuntimeError("sandbox sync failed")
        self.updates.append((path, content))


class _RemoteSandboxProvider:
    uses_thread_data_mounts = False

    def __init__(self, *, fail_next_update: bool = False) -> None:
        self.sandbox = _RemoteSandbox(fail_next_update=fail_next_update)
        self.released: list[str] = []

    async def acquire_async(self, _thread_id: str, *, user_id: str | None = None) -> str:
        return "sandbox-1"

    def get(self, sandbox_id: str):
        assert sandbox_id == "sandbox-1"
        return self.sandbox

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)


def _artifact_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _patch_artifact_update_dependencies(monkeypatch, artifact_path: Path, provider=None) -> None:
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)
    monkeypatch.setattr(artifacts_router, "reserve_artifact_write", _allow_artifact_write)
    monkeypatch.setattr(artifacts_router, "get_sandbox_provider", lambda: provider or _MountedSandboxProvider())


def test_update_artifact_replaces_utf8_text_atomically(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    artifact_path.chmod(0o600)
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)

    response = asyncio.run(
        call_unwrapped(
            artifacts_router.update_artifact,
            "thread-1",
            "mnt/user-data/outputs/note.txt",
            artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
            _make_request(),
        )
    )

    assert artifact_path.read_text(encoding="utf-8") == "after"
    assert response.path == "/mnt/user-data/outputs/note.txt"
    assert response.sha256 == _artifact_sha256("after")
    assert response.size == len(b"after")
    if hasattr(artifacts_router.os, "fchmod"):
        replacement_mode = stat.S_IMODE(artifact_path.stat().st_mode)
        assert replacement_mode == 0o660
        assert not replacement_mode & stat.S_IWOTH


def test_update_artifact_replaces_when_fchmod_is_unavailable(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)
    monkeypatch.delattr(artifacts_router.os, "fchmod", raising=False)

    response = asyncio.run(
        call_unwrapped(
            artifacts_router.update_artifact,
            "thread-1",
            "mnt/user-data/outputs/note.txt",
            artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
            _make_request(),
        )
    )

    assert artifact_path.read_text(encoding="utf-8") == "after"
    assert response.sha256 == _artifact_sha256("after")


def test_update_artifact_rejects_stale_revision_without_changing_file(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("agent version", encoding="utf-8")
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/note.txt",
                artifacts_router.ArtifactUpdateRequest(content="user version", expected_sha256=_artifact_sha256("old version")),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 412
    assert artifact_path.read_text(encoding="utf-8") == "agent version"


def test_update_artifact_rejects_non_output_path(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/workspace/note.txt",
                artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 400
    assert artifact_path.read_text(encoding="utf-8") == "before"


def test_update_artifact_rejects_binary_file(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "blob.bin"
    artifact_path.write_bytes(b"before\x00binary")
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/blob.bin",
                artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=hashlib.sha256(b"before\x00binary").hexdigest()),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 415


def test_update_artifact_syncs_non_mounted_sandbox(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    provider = _RemoteSandboxProvider()
    _patch_artifact_update_dependencies(monkeypatch, artifact_path, provider)

    asyncio.run(
        call_unwrapped(
            artifacts_router.update_artifact,
            "thread-1",
            "mnt/user-data/outputs/note.txt",
            artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
            _make_request(),
        )
    )

    assert provider.sandbox.updates == [("/mnt/user-data/outputs/note.txt", b"after")]
    assert provider.released == ["sandbox-1"]
    assert artifact_path.read_text(encoding="utf-8") == "after"


def test_update_artifact_releases_sandbox_when_initial_sync_fails(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    provider = _RemoteSandboxProvider(fail_next_update=True)
    _patch_artifact_update_dependencies(monkeypatch, artifact_path, provider)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/note.txt",
                artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 500
    assert provider.released == ["sandbox-1"]
    assert provider.sandbox.updates == [("/mnt/user-data/outputs/note.txt", b"before")]
    assert artifact_path.read_text(encoding="utf-8") == "before"


def test_update_artifact_rolls_back_remote_when_local_replace_fails(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    provider = _RemoteSandboxProvider()
    _patch_artifact_update_dependencies(monkeypatch, artifact_path, provider)

    def fail_replace(*_args, **_kwargs) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(artifacts_router, "_replace_artifact_atomically", fail_replace)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/note.txt",
                artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 500
    assert provider.sandbox.updates == [
        ("/mnt/user-data/outputs/note.txt", b"after"),
        ("/mnt/user-data/outputs/note.txt", b"before"),
    ]
    assert provider.released == ["sandbox-1"]
    assert artifact_path.read_text(encoding="utf-8") == "before"


def test_update_artifact_rejects_oversized_content(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    _patch_artifact_update_dependencies(monkeypatch, artifact_path)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/note.txt",
                artifacts_router.ArtifactUpdateRequest(
                    content="x" * (artifacts_router.MAX_EDITABLE_ARTIFACT_BYTES + 1),
                    expected_sha256=_artifact_sha256("before"),
                ),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 413
    assert artifact_path.read_text(encoding="utf-8") == "before"


def test_update_artifact_reports_active_run_conflict(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("before", encoding="utf-8")
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    @asynccontextmanager
    async def reject_artifact_write(*_args, **_kwargs):
        raise artifacts_router.ConflictError("active run")
        yield

    monkeypatch.setattr(artifacts_router, "reserve_artifact_write", reject_artifact_write)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                artifacts_router.update_artifact,
                "thread-1",
                "mnt/user-data/outputs/note.txt",
                artifacts_router.ArtifactUpdateRequest(content="after", expected_sha256=_artifact_sha256("before")),
                _make_request(),
            )
        )

    assert exc_info.value.status_code == 409
    assert artifact_path.read_text(encoding="utf-8") == "before"


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


def test_get_artifact_binary_preview_is_inline_file_response(tmp_path, monkeypatch) -> None:
    # Binary (non-text, non-active-content) artifacts must go through the
    # "inline_file" plan so get_artifact serves them via FileResponse.
    artifact_path = tmp_path / "clip.mp3"
    artifact_path.write_bytes(b"\x00\x01ID3fakeaudiobytes")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    response = asyncio.run(call_unwrapped(artifacts_router.get_artifact, "thread-1", "mnt/user-data/outputs/clip.mp3", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.media_type == "audio/mpeg"
    assert response.headers.get("content-disposition", "").startswith("inline;")


def test_get_artifact_binary_preview_supports_range_requests(tmp_path, monkeypatch) -> None:
    # Regression test for #3240: dragging an audio/video artifact's seek bar
    # reset playback to the start because the binary-preview branch used to
    # buffer the whole file into a plain Response, which ignores byte-Range
    # requests entirely (always 200 + full body, never 206). Browsers fall
    # back to restarting playback from byte 0 when a seek's Range request
    # doesn't come back as 206. FileResponse (used for the "file" plan
    # already) handles Range/If-Range natively, so switching the binary
    # branch to FileResponse fixes seeking for free.
    # Cycle through all 256 byte values (incl. \x00) so is_text_file_by_content
    # correctly sniffs this as binary, same as a real audio file would be -- an
    # all-printable-ASCII payload would (correctly) be sniffed as text and miss
    # the branch this test targets.
    payload = bytes(i % 256 for i in range(1_000_000))
    artifact_path = tmp_path / "clip.mp3"
    artifact_path.write_bytes(payload)

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path, user_id=None: artifact_path)

    app = make_authed_test_app()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        full = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/clip.mp3")
        seek = client.get(
            "/api/threads/thread-1/artifacts/mnt/user-data/outputs/clip.mp3",
            headers={"Range": "bytes=500000-"},
        )

    assert full.status_code == 200
    assert full.headers.get("accept-ranges") == "bytes"
    assert full.content == payload

    assert seek.status_code == 206
    assert seek.headers.get("content-range") == f"bytes 500000-999999/{len(payload)}"
    assert seek.content == payload[500000:]
    assert seek.headers.get("content-disposition", "").startswith("inline;")


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
