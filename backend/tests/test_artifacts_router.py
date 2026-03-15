"""Tests for gateway artifact retrieval through the thread-file backend."""

import asyncio
import io
import zipfile
from types import SimpleNamespace

from src.gateway.routers import artifacts
from src.sandbox import tools as sandbox_tools
from src.storage import thread_files as thread_files_module


class InMemoryArtifactBackend:
    def __init__(self):
        self._store: dict[tuple[str, str], bytes] = {}

    def put_virtual_file(self, thread_id: str, virtual_path: str, content: bytes) -> None:
        self._store[(thread_id, f"/{virtual_path.lstrip('/')}")] = content

    def exists_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        return (thread_id, f"/{virtual_path.lstrip('/')}") in self._store

    def read_virtual_file(self, thread_id: str, virtual_path: str) -> bytes:
        return self._store[(thread_id, f"/{virtual_path.lstrip('/')}")]


class _Sandbox:
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as file_obj:
            file_obj.write(content)


def _request():
    return artifacts.Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.txt",
            "query_string": b"",
            "headers": [],
        }
    )


def test_artifact_router_reads_published_output_after_local_file_is_deleted(monkeypatch, tmp_path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True)
    result_path = outputs_dir / "result.txt"
    backend = InMemoryArtifactBackend()

    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(tmp_path / "workspace"),
                "uploads_path": str(tmp_path / "uploads"),
                "outputs_path": str(outputs_dir),
            },
        },
        context={"thread_id": "thread-1"},
    )

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: _Sandbox())
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(sandbox_tools, "replace_virtual_path", lambda path, thread_data: str(result_path))
    monkeypatch.setattr(thread_files_module, "get_thread_file_backend", lambda feature: backend)
    monkeypatch.setattr(artifacts, "get_thread_file_backend", lambda feature: backend)

    result = sandbox_tools.write_file_tool.func(
        runtime=runtime,
        description="write output",
        path="/mnt/user-data/outputs/result.txt",
        content="durable output",
    )

    assert result == "OK"
    assert result_path.read_text(encoding="utf-8") == "durable output"

    result_path.unlink()

    response = asyncio.run(artifacts.get_artifact("thread-1", "mnt/user-data/outputs/result.txt", _request()))
    assert response.body == b"durable output"
    assert response.media_type == "text/plain"


def test_artifact_router_reads_skill_member_from_backend_archive(monkeypatch):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as zf:
        zf.writestr("SKILL.md", "# Stored Skill")

    backend = InMemoryArtifactBackend()
    backend.put_virtual_file("thread-1", "/mnt/user-data/outputs/example.skill", archive_bytes.getvalue())

    monkeypatch.setattr(artifacts, "get_thread_file_backend", lambda feature: backend)

    response = asyncio.run(artifacts.get_artifact("thread-1", "mnt/user-data/outputs/example.skill/SKILL.md", _request()))
    assert response.body == b"# Stored Skill"
    assert response.media_type == "text/markdown"
