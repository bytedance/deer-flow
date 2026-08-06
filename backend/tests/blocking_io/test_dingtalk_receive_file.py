"""Regression anchor: DingTalk ``receive_file`` must not block the event loop.

``_receive_single_file`` prepares the thread directories, resolves the uploads
dir, stages the attachment, and publishes it without replacing an existing name
— all blocking filesystem IO that must run inside ``asyncio.to_thread`` (and
sandbox sync must go through ``acquire_async`` + an offloaded ``update_file``).
This anchor drives the real ``receive_file`` under the strict Blockbuster gate;
if any of that regresses back onto the event loop, Blockbuster raises
``BlockingError``.

The ``Paths`` construction is offloaded only because ``Paths.__init__`` resolves
paths synchronously; the surface under test (``receive_file``'s persist path) is
exercised on the event loop, not bypassed. The download itself is mocked — the
network leg is httpx-async and not the subject here.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_receive_file_persist_does_not_block_event_loop(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)

    async def _acquire_async(thread_id, user_id=None):
        raise AssertionError("mounted uploads must not acquire a sandbox")

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(
            uses_thread_data_mounts=True,
            acquire_async=_acquire_async,
            get=lambda sid: (_ for _ in ()).throw(AssertionError("mounted uploads must not look up a sandbox")),
        ),
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
    uploaded = paths.sandbox_uploads_dir("t1", user_id="default") / "a.pdf"
    assert (await asyncio.to_thread(uploaded.stat)).st_mode & 0o044 == 0o044


async def test_receive_file_rejects_symlinked_upload_directory(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    await asyncio.to_thread(paths.ensure_thread_dirs, "t1", user_id="default")
    uploads = paths.sandbox_uploads_dir("t1", user_id="default")
    outside = tmp_path / "outside"
    await asyncio.to_thread(outside.mkdir)
    await asyncio.to_thread(uploads.rmdir)
    await asyncio.to_thread(uploads.symlink_to, outside, target_is_directory=True)
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)

    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")

    result = await channel._receive_single_file("dc", "file", "a.pdf", "t1", user_id="default")

    assert result == ""
    assert not await asyncio.to_thread((outside / "a.pdf").exists)


async def test_receive_file_holds_name_lease_through_remote_sync(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths
    from deerflow.uploads.manager import delete_file_safe

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)
    sync_started = threading.Event()
    allow_sync = threading.Event()

    class PausedSandbox:
        def update_file(self, path, content):
            sync_started.set()
            assert allow_sync.wait(5)

    async def acquire_async(thread_id, user_id=None):
        return "remote"

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(acquire_async=acquire_async, get=lambda sandbox_id: PausedSandbox()),
    )
    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")

    receive = asyncio.create_task(channel._receive_single_file("dc", "file", "a.pdf", "t1", user_id="default"))
    assert await asyncio.to_thread(sync_started.wait, 5)
    uploads = paths.sandbox_uploads_dir("t1", user_id="default")
    deletion = asyncio.create_task(asyncio.to_thread(delete_file_safe, uploads, "a.pdf"))
    await asyncio.sleep(0.05)
    assert not deletion.done()
    allow_sync.set()

    assert await receive == "/mnt/user-data/uploads/a.pdf"
    await deletion
    assert not await asyncio.to_thread((uploads / "a.pdf").exists)


async def test_receive_file_cancellation_drains_remote_sync_before_releasing_lease(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)
    sync_started = threading.Event()
    allow_sync = threading.Event()

    class PausedSandbox:
        def __init__(self):
            self.removals = []

        def update_file(self, _path, _content):
            sync_started.set()
            assert allow_sync.wait(5)

        def remove_file(self, path):
            self.removals.append(path)

    sandbox = PausedSandbox()

    async def acquire_async(_thread_id, user_id=None):
        return "remote"

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(acquire_async=acquire_async, get=lambda _sandbox_id: sandbox),
    )
    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")
    receive = asyncio.create_task(channel._receive_single_file("dc", "file", "a.pdf", "t1", user_id="default"))
    assert await asyncio.to_thread(sync_started.wait, 5)
    uploads = paths.sandbox_uploads_dir("t1", user_id="default")
    receive.cancel()
    try:
        await asyncio.sleep(0.05)
        assert not receive.done()
    finally:
        allow_sync.set()
        with suppress(asyncio.CancelledError):
            await receive

    assert not await asyncio.to_thread((uploads / "a.pdf").exists)
    assert sandbox.removals == ["/mnt/user-data/uploads/a.pdf"]
