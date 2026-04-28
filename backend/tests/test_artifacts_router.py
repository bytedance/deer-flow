import asyncio
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.path_utils as path_utils
import app.gateway.routers.artifacts as artifacts_router
from deerflow.config.paths import Paths

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def test_resolve_output_virtual_path_accepts_outputs_file(tmp_path) -> None:
    paths = Paths(base_dir=tmp_path)

    resolved = paths.resolve_output_virtual_path("thread-1", "/mnt/user-data/outputs/report.txt")

    assert resolved == (tmp_path / "threads" / "thread-1" / "user-data" / "outputs" / "report.txt").resolve()


@pytest.mark.parametrize(
    "virtual_path",
    [
        "/mnt/user-data/uploads/secret.txt",
        "/mnt/user-data/workspace/notes.txt",
        "/mnt/user-data/outputs/../uploads/secret.txt",
    ],
)
def test_resolve_output_virtual_path_rejects_non_output_paths(tmp_path, virtual_path: str) -> None:
    paths = Paths(base_dir=tmp_path)

    with pytest.raises(ValueError):
        paths.resolve_output_virtual_path("thread-1", virtual_path)


def test_resolve_thread_artifact_path_rejects_upload_path(tmp_path, monkeypatch) -> None:
    thread_id = "thread-1"
    paths = Paths(base_dir=tmp_path)
    upload = tmp_path / "threads" / thread_id / "user-data" / "uploads" / "secret.txt"
    upload.parent.mkdir(parents=True)
    upload.write_text("secret", encoding="utf-8")

    monkeypatch.setattr(path_utils, "get_paths", lambda: paths)

    with pytest.raises(artifacts_router.HTTPException) as exc_info:
        path_utils.resolve_thread_artifact_path(thread_id, "/mnt/user-data/uploads/secret.txt")

    assert exc_info.value.status_code == 403


def test_get_artifact_uses_artifact_only_resolver(tmp_path, monkeypatch) -> None:
    thread_id = "thread-1"
    paths = Paths(base_dir=tmp_path)
    artifact = tmp_path / "threads" / thread_id / "user-data" / "outputs" / "note.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("hello", encoding="utf-8")

    def forbidden_generic_resolver(_thread_id: str, _virtual_path: str):
        raise AssertionError("generic resolver must not serve artifact routes")

    monkeypatch.setattr(path_utils, "get_paths", lambda: paths)
    monkeypatch.setattr(paths, "resolve_virtual_path", forbidden_generic_resolver)

    response = asyncio.run(artifacts_router.get_artifact(thread_id, "mnt/user-data/outputs/note.txt", _make_request()))

    assert response.status_code == 200
    assert bytes(response.body).decode("utf-8") == "hello"


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    request = _make_request()
    response = asyncio.run(artifacts_router.get_artifact("thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: skill_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: artifact_path)

    app = FastAPI()
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

    monkeypatch.setattr(artifacts_router, "resolve_thread_artifact_path", lambda _thread_id, _path: skill_path)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")
