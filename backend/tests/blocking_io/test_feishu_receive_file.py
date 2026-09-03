"""Regression anchors: Feishu ``receive_file`` must not block the event loop."""

from __future__ import annotations

import asyncio
import threading
from io import BytesIO
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


def _channel_with_file(content: bytes = b"DATA", filename: str = "report.pdf"):
    from app.channels.feishu import FeishuChannel
    from app.channels.message_bus import MessageBus

    channel = FeishuChannel(MessageBus(), {"app_id": "test", "app_secret": "test"})
    channel._GetMessageResourceRequest = MagicMock()
    builder = MagicMock()
    builder.message_id.return_value = builder
    builder.file_key.return_value = builder
    builder.type.return_value = builder
    builder.build.return_value = object()
    channel._GetMessageResourceRequest.builder.return_value = builder

    response = MagicMock()
    response.success.return_value = True
    response.file = BytesIO(content)
    response.file_name = filename
    channel._api_client = MagicMock()
    channel._api_client.im.v1.message_resource.get.return_value = response
    return channel


class _RemoteSandbox:
    def __init__(self) -> None:
        self.updates: list[tuple[str, bytes]] = []
        self.update_thread_id: int | None = None
        self.released_scopes: list[str] = []

    def update_file(self, path: str, content: bytes) -> None:
        self.update_thread_id = threading.get_ident()
        self.updates.append((path, content))

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)


class _RemoteProvider:
    uses_thread_data_mounts = False

    def __init__(self) -> None:
        self.sandbox = _RemoteSandbox()
        self.acquire_async_calls: list[tuple[str | None, str | None]] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("Feishu receive_file must use acquire_async")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        self.acquire_async_calls.append((thread_id, user_id))
        return "remote-sandbox"

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == "remote-sandbox" else None


class _MountedProvider:
    uses_thread_data_mounts = True

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("mounted uploads must not acquire a sandbox")

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        raise AssertionError("mounted uploads must not acquire a sandbox")

    def get(self, sandbox_id: str):
        raise AssertionError("mounted uploads must not look up a sandbox")


class _BlockingRemoteSandbox(_RemoteSandbox):
    def __init__(self) -> None:
        super().__init__()
        self.update_started = threading.Event()
        self.allow_update = threading.Event()
        self.closed = False

    def update_file(self, path: str, content: bytes) -> None:
        self.update_started.set()
        assert self.allow_update.wait(timeout=2)
        assert not self.closed
        super().update_file(path, content)


class _BlockingRemoteProvider(_RemoteProvider):
    def __init__(self) -> None:
        super().__init__()
        self.sandbox = _BlockingRemoteSandbox()
        self.release_calls: list[str] = []

    def release(self, sandbox_id: str) -> None:
        self.release_calls.append(sandbox_id)
        self.sandbox.closed = True


async def test_receive_file_remote_sandbox_does_not_block_event_loop(tmp_path, monkeypatch) -> None:
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    provider = _RemoteProvider()
    provider_lookup_thread_id = None

    def _get_provider():
        nonlocal provider_lookup_thread_id
        provider_lookup_thread_id = threading.get_ident()
        return provider

    monkeypatch.setattr("app.channels.feishu.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.feishu.get_sandbox_provider", _get_provider)

    loop_thread_id = threading.get_ident()
    result = await _channel_with_file()._receive_single_file(
        "message-1",
        "file-key",
        "file",
        "thread-1",
        user_id="ou-user",
    )

    assert result == "/mnt/user-data/uploads/report.pdf"
    assert provider.acquire_async_calls == [("thread-1", "ou-user")]
    assert provider.sandbox.updates == [(result, b"DATA")]
    assert provider_lookup_thread_id != loop_thread_id
    assert provider.sandbox.update_thread_id != loop_thread_id


async def test_receive_file_mounted_sandbox_skips_redundant_sync(tmp_path, monkeypatch) -> None:
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.feishu.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.feishu.get_sandbox_provider", lambda: _MountedProvider())

    result = await _channel_with_file()._receive_single_file(
        "message-1",
        "file-key",
        "file",
        "thread-1",
        user_id="ou-user",
    )

    assert result == "/mnt/user-data/uploads/report.pdf"
    uploaded = tmp_path / "users" / "ou-user" / "threads" / "thread-1" / "user-data" / "uploads" / "report.pdf"
    assert await asyncio.to_thread(uploaded.read_bytes) == b"DATA"


async def test_cancelled_receive_file_holds_sandbox_lease_until_remote_sync_finishes(tmp_path, monkeypatch) -> None:
    from deerflow.config.paths import Paths
    from deerflow.sandbox.lease import discard_sandbox_lease_manager, get_sandbox_lease_manager

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    provider = _BlockingRemoteProvider()
    manager = get_sandbox_lease_manager(provider)
    monkeypatch.setattr("app.channels.feishu.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.feishu.get_sandbox_provider", lambda: provider)

    await manager.acquire_async("active-run", "thread-1", user_id="ou-user")
    receive_task = asyncio.create_task(
        _channel_with_file()._receive_single_file(
            "message-1",
            "file-key",
            "file",
            "thread-1",
            user_id="ou-user",
        )
    )
    try:
        assert await asyncio.to_thread(provider.sandbox.update_started.wait, 1)
        for _ in range(3):
            receive_task.cancel()
            await asyncio.sleep(0)

        assert not receive_task.done()
        await manager.release_async("active-run")
        assert provider.release_calls == []
        assert not provider.sandbox.closed

        provider.sandbox.allow_update.set()
        with pytest.raises(asyncio.CancelledError):
            await receive_task

        assert provider.sandbox.updates == [("/mnt/user-data/uploads/report.pdf", b"DATA")]
        assert provider.release_calls == ["remote-sandbox"]
        assert provider.sandbox.closed
    finally:
        provider.sandbox.allow_update.set()
        if not receive_task.done():
            receive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receive_task
        await manager.release_async("active-run")
        discard_sandbox_lease_manager(provider)
