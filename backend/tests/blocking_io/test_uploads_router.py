"""Regression anchor: uploads router must not block the event loop."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from _router_auth_helpers import call_unwrapped
from fastapi import UploadFile

from app.gateway.routers import uploads
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import ensure_uploads_dir, get_uploads_dir

pytestmark = pytest.mark.asyncio


class _SandboxRecorder:
    def __init__(self) -> None:
        self.updates: list[tuple[str, bytes]] = []

    def update_file(self, path: str, content: bytes) -> None:
        self.updates.append((path, content))


class _MountedProvider:
    uses_thread_data_mounts = True

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("mounted upload path must not acquire a sandbox")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("mounted upload path must not acquire a sandbox")

    def get(self, sandbox_id: str):
        raise AssertionError("mounted upload path must not read a sandbox")


class _RemoteProvider:
    uses_thread_data_mounts = False

    def __init__(self) -> None:
        self.sandbox = _SandboxRecorder()
        self.acquire_async_calls: list[tuple[str | None, str | None]] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("upload route should use acquire_async")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        self.acquire_async_calls.append((thread_id, user_id))
        return "remote-sandbox"

    def get(self, sandbox_id: str):
        if sandbox_id == "remote-sandbox":
            return self.sandbox
        return None


def _reset_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))

    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)


async def _thread_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    user_id = user_id or get_effective_user_id()
    return await asyncio.to_thread(ensure_uploads_dir, thread_id, user_id=user_id)


async def test_upload_endpoint_mounted_provider_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    provider = _MountedProvider()
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: provider)

    result = await call_unwrapped(
        uploads.upload_files,
        "t-mounted",
        request=None,
        files=[UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))],
        config=SimpleNamespace(),
    )

    user_id = get_effective_user_id()
    target = await asyncio.to_thread(lambda: get_uploads_dir("t-mounted", user_id=user_id) / "notes.txt")
    assert result.success is True
    assert result.files[0].filename == "notes.txt"
    assert await asyncio.to_thread(target.read_bytes) == b"hello uploads"


async def test_upload_endpoint_remote_provider_syncs_without_blocking_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    provider = _RemoteProvider()
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(uploads, "get_effective_user_id", lambda: "owner-upload")

    result = await call_unwrapped(
        uploads.upload_files,
        "t-remote",
        request=None,
        files=[UploadFile(filename="report.txt", file=BytesIO(b"remote bytes"))],
        config=SimpleNamespace(),
    )

    assert result.success is True
    assert provider.acquire_async_calls == [("t-remote", "owner-upload")]
    assert provider.sandbox.updates == [("/mnt/user-data/uploads/report.txt", b"remote bytes")]


async def test_list_uploaded_files_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    uploads_dir = await _thread_uploads_dir("t-list")
    await asyncio.to_thread((uploads_dir / "notes.txt").write_bytes, b"hello")

    result = await call_unwrapped(uploads.list_uploaded_files, "t-list", request=None)

    assert result.count == 1
    assert result.files[0].filename == "notes.txt"
    assert result.files[0].size == len(b"hello")


async def test_delete_uploaded_file_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    uploads_dir = await _thread_uploads_dir("t-delete")
    target = uploads_dir / "notes.txt"
    await asyncio.to_thread(target.write_bytes, b"delete me")

    result = await call_unwrapped(uploads.delete_uploaded_file, "t-delete", "notes.txt", request=None)

    assert result == {"success": True, "message": "Deleted notes.txt"}
    assert not await asyncio.to_thread(target.exists)
