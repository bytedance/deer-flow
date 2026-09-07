"""Regression anchor: DingTalk ``receive_file`` must not block the event loop.

``_receive_single_file`` prepares the thread directories, resolves the uploads
dir, scans it for the uniqueness claim, and writes the attachment — all blocking
filesystem IO that must run inside ``asyncio.to_thread`` (and sandbox sync must
go through ``acquire_async`` + an offloaded ``update_file``). This anchor drives
the real ``receive_file`` under the strict Blockbuster gate; if any of that
regresses back onto the event loop, Blockbuster raises ``BlockingError``.

The ``Paths`` construction is offloaded only because ``Paths.__init__`` resolves
paths synchronously; the surface under test (``receive_file``'s persist path) is
exercised on the event loop, not bypassed. The download itself is mocked — the
network leg is httpx-async and not the subject here.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


class _BlockingRemoteSandbox:
    def __init__(self) -> None:
        self.update_started = threading.Event()
        self.allow_update = threading.Event()
        self.closed = False
        self.updates: list[tuple[str, bytes]] = []
        self.released_scopes: list[str] = []

    def update_file(self, path: str, content: bytes) -> None:
        self.update_started.set()
        assert self.allow_update.wait(timeout=2)
        assert not self.closed
        self.updates.append((path, content))

    def release_command_scope(self, scope_id: str) -> None:
        self.released_scopes.append(scope_id)


class _BlockingRemoteProvider:
    def __init__(self) -> None:
        self.sandbox = _BlockingRemoteSandbox()
        self.release_calls: list[str] = []

    async def acquire_async(self, thread_id=None, *, user_id=None):
        return "remote-sandbox"

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == "remote-sandbox" else None

    def release(self, sandbox_id: str) -> None:
        self.release_calls.append(sandbox_id)
        self.sandbox.closed = True


async def test_receive_file_persist_does_not_block_event_loop(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)

    async def _acquire_async(thread_id, user_id=None):
        return "local"

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(acquire_async=_acquire_async, get=lambda sid: None),
    )

    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")

    msg = channel._make_inbound(
        chat_id="c",
        user_id="u",
        text="hi",
        thread_ts="m",
        files=[{"type": "file", "download_code": "dc", "filename": "a.pdf"}],
    )
    out = await channel.receive_file(msg, "t1", user_id="default")

    assert "/uploads/a.pdf" in out.text
    assert out.files == []


async def test_cancelled_receive_file_holds_sandbox_lease_until_remote_sync_finishes(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths
    from deerflow.sandbox.lease import discard_sandbox_lease_manager, get_sandbox_lease_manager

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    provider = _BlockingRemoteProvider()
    manager = get_sandbox_lease_manager(provider)
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)
    monkeypatch.setattr("app.channels.dingtalk.get_sandbox_provider", lambda: provider)

    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")

    await manager.acquire_async("active-run", "thread-1", user_id="ou-user")
    receive_task = asyncio.create_task(
        channel._receive_single_file(
            "download-code",
            "file",
            "report.pdf",
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
