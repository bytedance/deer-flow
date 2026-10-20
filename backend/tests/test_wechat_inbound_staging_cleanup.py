"""WeChat staging ownership ends on ingestion, rejection, failure or cancellation."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def staging(tmp_path, monkeypatch):
    from app.channels.message_bus import MessageBus
    from app.channels.wechat import WechatChannel, _encrypt_aes_128_ecb
    from deerflow.config.paths import Paths

    paths = Paths(tmp_path / "uploads")
    monkeypatch.setattr("deerflow.uploads.manager.get_paths", lambda: paths)
    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "test", "state_dir": str(tmp_path / "wechat")})
    key = b"1234567890abcdef"
    channel._download_cdn_bytes = AsyncMock(return_value=_encrypt_aes_128_ecb(b"attachment", key))
    raw = {
        "message_type": 1,
        "message_id": "message-1",
        "from_user_id": "wx-user",
        "item_list": [{"type": 4, "file_item": {"file_name": "report.pdf", "aeskey": key.hex(), "media": {"full_url": "https://cdn.weixin.qq.com/file"}}}],
    }
    return channel, raw


async def _queued_message(staging):
    channel, raw = staging
    await channel._handle_update(raw)
    msg = channel.bus.get_inbound_nowait()
    channel.bus.inbound_task_done()
    return msg


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["prepare", "read", "write", "unsafe_name"])
async def test_ingestion_failure_releases_owned_staging(staging, monkeypatch, failure):
    from app.channels.manager import INBOUND_FILE_READERS, _ingest_inbound_files

    msg = await _queued_message(staging)
    path = Path(msg.files[0]["path"])
    if failure == "read":
        monkeypatch.setitem(INBOUND_FILE_READERS, "wechat", AsyncMock(side_effect=OSError("read failed")))
    elif failure == "unsafe_name":
        msg.files[0]["filename"] = ".."
    else:
        target = "ensure_uploads_dir" if failure == "prepare" else "write_upload_file_no_symlink"
        monkeypatch.setattr(f"deerflow.uploads.manager.{target}", Mock(side_effect=OSError("upload failed")))
    if failure == "prepare":
        with pytest.raises(OSError, match="upload failed"):
            await _ingest_inbound_files("thread", msg, user_id="owner")
    else:
        assert await _ingest_inbound_files("thread", msg, user_id="owner") == []
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_cleanup_uses_allocated_directory_not_mutable_file_path(staging, tmp_path):
    from app.channels.manager import _ingest_inbound_files

    msg = await _queued_message(staging)
    owned = Path(msg.files[0]["path"])
    foreign = tmp_path / "foreign" / "report.pdf"
    foreign.parent.mkdir()
    foreign.write_bytes(b"unrelated")
    msg.files[0]["path"] = str(foreign)
    assert len(await _ingest_inbound_files("thread", msg, user_id="owner")) == 1
    assert not owned.parent.exists()
    assert foreign.read_bytes() == b"unrelated"


@pytest.mark.asyncio
async def test_unowned_local_path_is_not_removed(staging, tmp_path):
    from app.channels.manager import _ingest_inbound_files
    from app.channels.message_bus import InboundMessage

    foreign = tmp_path / "inbound-foreign" / "report.pdf"
    foreign.parent.mkdir()
    foreign.write_bytes(b"unrelated")
    msg = InboundMessage(channel_name="wechat", chat_id="chat", user_id="user", text="", files=[{"path": str(foreign), "filename": foreign.name, "_cleanup": str(foreign.parent)}])
    assert len(await _ingest_inbound_files("thread", msg, user_id="owner")) == 1
    assert foreign.read_bytes() == b"unrelated"


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["duplicate", "rejected", "handler_error", "queued_shutdown"])
async def test_manager_releases_staging_without_ingestion(staging, disposition):
    from app.channels.manager import ChannelManager

    channel, raw = staging
    await channel._handle_update(raw)
    paths = list(channel._download_dir().glob("inbound-*"))
    assert len(paths) == 1
    manager = ChannelManager(bus=channel.bus, store=Mock())
    manager._is_duplicate_inbound = AsyncMock(return_value=disposition == "duplicate")
    manager._dispatch_message = AsyncMock(side_effect=RuntimeError("handler failed") if disposition == "handler_error" else None)
    if disposition == "queued_shutdown":
        manager._shutdown_grace_period_seconds = 0
        await manager.stop()
    else:
        await manager._worker_loop(0)
    assert not paths[0].exists()
    await asyncio.wait_for(channel.bus.join_inbound(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["queue_closed", "queue_full", "identity", "publication"])
async def test_adapter_retains_cleanup_until_publication_succeeds(staging, failure):
    from app.channels.message_bus import InboundMessage, MessageBus

    channel, raw = staging
    if failure == "queue_closed":
        channel.bus.close_inbound()
    elif failure == "queue_full":
        channel.bus = MessageBus(inbound_queue_maxsize=1)
        await channel.bus.publish_inbound(InboundMessage(channel_name="test", chat_id="chat", user_id="user", text="full"))
    elif failure == "identity":
        channel._attach_connection_identity = AsyncMock(side_effect=RuntimeError("identity failed"))
    else:
        channel.bus.publish_inbound = AsyncMock(side_effect=RuntimeError("publication failed"))
    if failure in {"identity", "publication"}:
        with pytest.raises(RuntimeError, match="failed"):
            await channel._handle_update(raw)
    else:
        await channel._handle_update(raw)
    assert list(channel._download_dir().iterdir()) == []


@pytest.mark.asyncio
async def test_partial_extraction_failure_releases_earlier_attachments(staging):
    channel, raw = staging
    extract = channel._extract_file_item
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second attachment failed")
        return await extract(*args, **kwargs)

    channel._extract_file_item = fail_second
    raw["item_list"] *= 2
    with pytest.raises(RuntimeError, match="second attachment failed"):
        await channel._handle_update(raw)
    assert list(channel._download_dir().iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["staging", "reading", "cleanup"])
async def test_cancellation_drains_file_io_before_releasing_staging(staging, monkeypatch, phase):
    from app.channels.manager import _ingest_inbound_files

    channel, raw = staging
    started = threading.Event()
    release = threading.Event()
    if phase == "staging":
        stage = channel._stage_downloaded_file

        def blocked_stage(*args):
            path = stage(*args)
            started.set()
            assert release.wait(5)
            return path

        channel._stage_downloaded_file = blocked_stage
        operation = channel._handle_update(raw)
    else:
        if phase == "cleanup":
            import shutil

            remove = shutil.rmtree

            def blocked_remove(*args, **kwargs):
                started.set()
                assert release.wait(5)
                return remove(*args, **kwargs)

            monkeypatch.setattr("app.channels.wechat.shutil.rmtree", blocked_remove)
        msg = await _queued_message(staging)
        source = Path(msg.files[0]["path"])
        read = Path.read_bytes

        def blocked_read(path):
            if phase == "reading" and path == source:
                started.set()
                assert release.wait(5)
            return read(path)

        monkeypatch.setattr(Path, "read_bytes", blocked_read)
        operation = _ingest_inbound_files("thread", msg, user_id="owner")
    task = asyncio.create_task(operation)
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation must drain the worker before cleanup"
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert list(channel._download_dir().iterdir()) == []


@pytest.mark.parametrize("filename", ["../keep.txt", "sub/report.pdf", "sub\\report.pdf", "", ".", "..", "bad\x00name.pdf"])
def test_staging_rejects_non_basename_paths(staging, filename):
    channel, _ = staging
    downloads = channel._download_dir()
    downloads.mkdir(parents=True)
    sibling = downloads / "keep.txt"
    sibling.write_bytes(b"keep")
    assert channel._stage_downloaded_file(filename, b"overwrite") is None
    assert sibling.read_bytes() == b"keep"
    assert list(downloads.iterdir()) == [sibling]


@pytest.mark.asyncio
async def test_cleanup_failure_preserves_primary_error_and_releases_other_files(staging, monkeypatch):
    from app.channels.manager import _ingest_inbound_files
    from app.channels.message_bus import INBOUND_FILE_CLEANUP_KEY

    channel, raw = staging
    raw["item_list"] *= 2
    msg = await _queued_message(staging)
    paths = [Path(file["path"]) for file in msg.files]
    assert len(paths) == 2
    cleanup = msg.files[0][INBOUND_FILE_CLEANUP_KEY]
    msg.files[0][INBOUND_FILE_CLEANUP_KEY] = Mock(side_effect=OSError("cleanup failed"))
    monkeypatch.setattr("deerflow.uploads.manager.ensure_uploads_dir", Mock(side_effect=OSError("prepare failed")))
    monkeypatch.setattr("app.channels.message_bus.logger.warning", Mock(side_effect=RuntimeError("logging failed")))
    try:
        with pytest.raises(OSError, match="prepare failed"):
            await _ingest_inbound_files("thread", msg, user_id="owner")
        assert paths[0].exists()
        assert not paths[1].parent.exists()
        assert all(INBOUND_FILE_CLEANUP_KEY not in file for file in msg.files)
    finally:
        cleanup()
