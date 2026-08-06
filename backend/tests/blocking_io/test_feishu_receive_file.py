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

    def update_file(self, path: str, content: bytes) -> None:
        self.update_thread_id = threading.get_ident()
        self.updates.append((path, content))


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


async def test_concurrent_same_name_files_preserve_every_payload(tmp_path, monkeypatch) -> None:
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.feishu.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.feishu.get_sandbox_provider", lambda: _MountedProvider())
    payloads = [f"payload-{index}".encode() for index in range(8)]
    channels = [_channel_with_file(payload, "report.pdf") for payload in payloads]

    results = await asyncio.gather(
        *(
            channel._receive_single_file(
                f"message-{index}",
                f"file-key-{index}",
                "file",
                "thread-1",
                user_id="ou-user",
            )
            for index, channel in enumerate(channels)
        )
    )

    assert len(set(results)) == len(payloads)
    uploads = paths.sandbox_uploads_dir("thread-1", user_id="ou-user")
    assert {await asyncio.to_thread((uploads / result.rsplit("/", 1)[-1]).read_bytes) for result in results} == set(payloads)


async def test_receive_file_renames_around_planted_symlink(tmp_path, monkeypatch) -> None:
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    await asyncio.to_thread(paths.ensure_thread_dirs, "thread-1", user_id="ou-user")
    uploads = paths.sandbox_uploads_dir("thread-1", user_id="ou-user")
    outside = tmp_path / "outside.pdf"
    await asyncio.to_thread((uploads / "report.pdf").symlink_to, outside)
    monkeypatch.setattr("app.channels.feishu.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.feishu.get_sandbox_provider", lambda: _MountedProvider())

    result = await _channel_with_file(b"DATA", "report.pdf")._receive_single_file(
        "message-1",
        "file-key",
        "file",
        "thread-1",
        user_id="ou-user",
    )

    assert result == "/mnt/user-data/uploads/report_1.pdf"
    assert not await asyncio.to_thread(outside.exists)
    assert await asyncio.to_thread((uploads / "report.pdf").is_symlink)
    assert await asyncio.to_thread((uploads / "report_1.pdf").read_bytes) == b"DATA"
