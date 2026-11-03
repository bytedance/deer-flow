"""Real filesystem publication and remote-sandbox synchronization of retained bytes."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api import AgentRunError

from app.gateway.extension_artifacts import MAX_BYTES, import_snapshot, write_import_snapshot

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined imports require POSIX")


@pytest.fixture(autouse=True)
def configuration(tmp_path, monkeypatch):
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    try:
        yield
    finally:
        reset_app_config()


def test_import_preserves_bytes_and_rejects_replaced_files_and_symlinks(tmp_path, monkeypatch):
    from deerflow.config.paths import get_paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    content = b"\x00\xff" * (MAX_BYTES // 2)
    result = write_import_snapshot("alice", "thread", "plugin", "报告.pdf", content)
    target = get_paths().sandbox_uploads_dir("thread", user_id="alice") / result["filename"]
    assert target.read_bytes() == content
    assert write_import_snapshot("alice", "thread", "plugin", "报告.pdf", content) == result
    target.unlink()
    outside = tmp_path / "private"
    outside.write_bytes(b"private")
    target.symlink_to(outside)
    with pytest.raises(AgentRunError):
        write_import_snapshot("alice", "thread", "plugin", "报告.pdf", content)
    assert outside.read_bytes() == b"private"
    assert not list(target.parent.glob(".upload-*.part"))


def test_import_rejects_directory_redirection_and_cleans_failed_publication(tmp_path, monkeypatch):
    from deerflow.config.paths import get_paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    write_import_snapshot("alice", "thread", "plugin", "first.txt", b"first")
    uploads = get_paths().sandbox_uploads_dir("thread", user_id="alice")
    original = uploads.with_name("original-uploads")
    uploads.rename(original)
    outside = tmp_path / "outside"
    outside.mkdir()
    uploads.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AgentRunError):
        write_import_snapshot("alice", "thread", "plugin", "second.txt", b"second")
    assert list(outside.iterdir()) == []
    uploads.unlink()
    original.rename(uploads)

    def fail(*args, **kwargs):
        raise OSError("Publication failed")

    monkeypatch.setattr("app.gateway.extension_artifacts.os.link", fail)
    with pytest.raises(AgentRunError):
        write_import_snapshot("alice", "thread", "plugin", "second.txt", b"second")
    assert [item.read_bytes() for item in uploads.iterdir()] == [b"first"]


@pytest.mark.asyncio
async def test_remote_import_retries_the_same_bytes_after_a_lost_sync_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    calls = []

    def sync(sandbox, filename, content):
        calls.append(("/mnt/user-data/uploads/" + filename, content))
        if len(calls) == 1:
            raise OSError("Lost remote acknowledgement")

    lease = SimpleNamespace(denied=False, sandbox=SimpleNamespace(update_file=sync), release=AsyncMock())
    monkeypatch.setattr("deerflow.sandbox.artifact_snapshot.publish_snapshot", sync)
    monkeypatch.setattr("app.gateway.extension_artifacts.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    acquire = AsyncMock(return_value=lease)
    monkeypatch.setattr("app.gateway.extension_artifacts.try_acquire_sandbox_for_request", acquire)
    with pytest.raises(OSError):
        await import_snapshot(None, "alice", "thread", "plugin", "report.pdf", b"\x00\xff")
    result = await import_snapshot(None, "alice", "thread", "plugin", "report.pdf", b"\x00\xff")
    assert calls == [(result["path"], b"\x00\xff")] * 2
    assert acquire.await_count == lease.release.await_count == 2


@pytest.mark.asyncio
async def test_remote_import_cancellation_drains_io_before_releasing_lease(tmp_path, monkeypatch):
    import threading

    from deerflow.utils.file_io import await_drained

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    entered = threading.Event()
    finish = threading.Event()
    exited = threading.Event()

    def sync(sandbox, filename, content):
        entered.set()
        finish.wait(5)
        exited.set()

    async def release():
        assert exited.is_set()

    lease = SimpleNamespace(denied=False, sandbox=SimpleNamespace(update_file=sync), release=AsyncMock(side_effect=release))
    monkeypatch.setattr("deerflow.sandbox.artifact_snapshot.publish_snapshot", sync)
    monkeypatch.setattr("app.gateway.extension_artifacts.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("app.gateway.extension_artifacts.try_acquire_sandbox_for_request", AsyncMock(return_value=lease))
    task = asyncio.create_task(await_drained(import_snapshot(None, "alice", "thread", "plugin", "report.pdf", b"bytes")))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        assert lease.release.await_count == 0
    finally:
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert lease.release.await_count == 1
