"""Cancellation at the real upload consumer must not abandon filesystem owners."""

import asyncio
import hashlib
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from httpx import ASGITransport, AsyncClient

from app.gateway import upload_ingestion
from app.gateway.routers import uploads
from deerflow.utils.file_io import run_file_io


class _Upload:
    def __init__(self, name, payload):
        self.filename = name
        self._chunks = [payload, b""]

    async def read(self, size):
        return self._chunks.pop(0)


@pytest.mark.parametrize("stage", ["prepare", "write", "commit", "directory", "companion", "sync"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_upload_worker_ownership_survives_request_cancellation(tmp_path, monkeypatch, stage, cancelled):
    """Pause native work at each ownership handoff; retain uncancelled controls."""
    directory = tmp_path / "uploads"
    directory.mkdir()
    existing = directory / "keep.txt"
    existing.write_bytes(b"another request")
    remote = tmp_path / "remote"
    remote.mkdir()
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()
    temporaries, conversion_dirs, worker_errors = [], [], []
    released_before_worker = []
    convert = stage in {"directory", "companion"}
    filename = "report.pdf" if convert else "report.txt"
    provider = SimpleNamespace(uses_thread_data_mounts=stage != "sync")
    monkeypatch.setattr(uploads, "ensure_uploads_dir", lambda *args, **kwargs: directory)
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(uploads, "_auto_convert_documents_enabled", lambda _: convert)

    def sync_file(name, content):
        (remote / Path(name).name).write_bytes(content)

    async def release_lease():
        released_before_worker.append(entered.is_set() and not settled.is_set())

    lease = SimpleNamespace(sandbox=SimpleNamespace(update_file=sync_file), sandbox_id="synthetic", denied=False, release=release_lease)
    monkeypatch.setattr(uploads, "try_acquire_sandbox_for_request", AsyncMock(return_value=lease))

    async def convert_file(source, output_path):
        assert source.read_bytes() == b"owned bytes"
        await run_file_io(output_path.write_text, "converted bytes", encoding="utf-8")
        return output_path

    monkeypatch.setattr(uploads, "convert_file_to_markdown", convert_file)
    prepare = uploads._prepare_upload_destination

    def remember_temp(*args, **kwargs):
        temporary = prepare(*args, **kwargs)
        temporaries.append(temporary)
        return temporary

    monkeypatch.setattr(uploads, "_prepare_upload_destination", remember_temp)

    def pause(call, *, after=False):
        def worker(*args, **kwargs):
            try:
                value = call(*args, **kwargs) if after else None
                entered.set()
                assert release.wait(10), "test did not release the native worker"
                return value if after else call(*args, **kwargs)
            except BaseException as error:
                worker_errors.append(error)
                raise
            finally:
                settled.set()

        return worker

    if stage == "prepare":
        monkeypatch.setattr(uploads, "_prepare_upload_destination", pause(remember_temp, after=True))
    elif stage == "write":
        monkeypatch.setattr(uploads, "_write_upload_chunk", pause(uploads._write_upload_chunk))
    elif stage == "commit":
        # The native hard link already exists, but its returned owner has not
        # reached the coroutine that records it for rejected-request cleanup.
        monkeypatch.setattr(uploads, "_commit_upload_temp_no_overwrite", pause(uploads._commit_upload_temp_no_overwrite, after=True))
    elif stage == "directory":
        mkdtemp = upload_ingestion.tempfile.mkdtemp

        def make_directory(*args, **kwargs):
            path = Path(mkdtemp(*args, **kwargs, dir=tmp_path))
            conversion_dirs.append(path)
            return str(path)

        monkeypatch.setattr(upload_ingestion.tempfile, "mkdtemp", pause(make_directory, after=True))
    elif stage == "companion":
        link = uploads._link_staged_no_overwrite

        def publish(*args, **kwargs):
            if args[2].endswith(".md"):
                return pause(link, after=True)(*args, **kwargs)
            return link(*args, **kwargs)

        monkeypatch.setattr(uploads, "_link_staged_no_overwrite", publish)
    else:
        monkeypatch.setattr(uploads, "_sync_upload_to_sandbox", pause(uploads._sync_upload_to_sandbox))

    async def scenario():
        task = asyncio.create_task(call_unwrapped(uploads.upload_files, "thread-owner", request=MagicMock(), files=[_Upload(filename, b"owned bytes")], config=SimpleNamespace()))
        try:
            assert await asyncio.to_thread(entered.wait, 10), "owning upload did not reach the worker"
            if cancelled:
                task.cancel()
                # Give both the owning coroutine and any shield/drain task
                # their ready turns, then deliver a second host cancellation.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
            release.set()
            if cancelled:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await task
                assert result.success
                assert result.files[0].filename == filename
            assert await asyncio.to_thread(settled.wait, 10)
            assert existing.read_bytes() == b"another request"
            assert all(temporary.handle.closed for temporary in temporaries), "lost staged handle"
            assert all(not temporary.temp_path.exists() for temporary in temporaries), "lost staged name"
            assert all(not path.exists() for path in conversion_dirs), "lost private conversion directory"
            assert worker_errors == [], "cleanup raced a still-running native worker"
            assert not any(directory.glob(".upload-*.part")), "hidden staged companion was abandoned"
            if cancelled and stage != "sync":
                assert list(directory.iterdir()) == [existing], "cancelled ingestion left published files"
            else:
                assert (directory / filename).read_bytes() == b"owned bytes"
                if convert:
                    assert (directory / "report.md").read_text() == "converted bytes"
            if stage == "sync":
                assert released_before_worker == [False], "sandbox lease released before sync worker ended"
                assert (remote / filename).read_bytes() == b"owned bytes"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            assert await asyncio.to_thread(settled.wait, 10)
            # The red baseline intentionally leaks resources. Reclaim only
            # the test's captures after all consumer-boundary assertions.
            for temporary in temporaries:
                if not temporary.handle.closed:
                    temporary.handle.close()
                temporary.temp_path.unlink(missing_ok=True)
            for path in conversion_dirs:
                shutil.rmtree(path, ignore_errors=True)

    asyncio.run(scenario())


@pytest.fixture
def local_uploads(tmp_path, monkeypatch):
    directory = tmp_path / "uploads"
    directory.mkdir()
    provider = SimpleNamespace(uses_thread_data_mounts=True)
    monkeypatch.setattr(uploads, "ensure_uploads_dir", lambda *args, **kwargs: directory)
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(uploads, "_auto_convert_documents_enabled", lambda _: False)
    return directory, provider


@pytest.mark.parametrize("stage", ["prepare", "commit"])
def test_multipart_http_cancellation_reclaims_native_files(local_uploads, monkeypatch, stage):
    directory, _ = local_uploads
    app = make_authed_test_app()
    app.include_router(uploads.router)
    app.dependency_overrides[uploads.get_config] = lambda: SimpleNamespace()
    entered, release = threading.Event(), threading.Event()
    captured = []
    name = "_prepare_upload_destination" if stage == "prepare" else "_commit_upload_temp_no_overwrite"
    native = getattr(uploads, name)

    def pause_after_native(*args, **kwargs):
        result = native(*args, **kwargs)
        captured.append(result)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(uploads, name, pause_after_native)

    async def scenario():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.post("/api/threads/http-owner/uploads", files={"files": ("payload.txt", b"http bytes")}))
            try:
                assert await asyncio.to_thread(entered.wait, 10)
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert list(directory.iterdir()) == []
                if stage == "prepare":
                    assert captured[0].handle.closed
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_waiting_for_network_chunks_is_cancellable_and_retry_is_clean(local_uploads):
    directory, _ = local_uploads
    survivor = directory / "keep.txt"
    survivor.write_bytes(b"someone else's file")

    async def scenario():
        waiting, network = asyncio.Event(), asyncio.Event()

        class PendingUpload:
            filename = "second.txt"

            async def read(self, size):
                waiting.set()
                await network.wait()
                return b""

        task = asyncio.create_task(call_unwrapped(uploads.upload_files, "network-owner", request=MagicMock(), files=[_Upload("first.txt", b"first bytes"), PendingUpload()], config=SimpleNamespace()))
        try:
            await asyncio.wait_for(waiting.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert not network.is_set(), "cancellation must not wait for more request bytes"
            assert list(directory.iterdir()) == [survivor]
            retry = await call_unwrapped(uploads.upload_files, "network-owner", request=MagicMock(), files=[_Upload("first.txt", b"retry bytes")], config=SimpleNamespace())
            assert retry.files[0].filename == "first.txt"
            assert (directory / "first.txt").read_bytes() == b"retry bytes"
            assert survivor.read_bytes() == b"someone else's file"
        finally:
            network.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancelled_write_failure_preserves_cancellation_and_cleans_staging(local_uploads, monkeypatch):
    directory, _ = local_uploads
    entered, release, settled = threading.Event(), threading.Event(), threading.Event()

    def fail_write(*args):
        entered.set()
        try:
            assert release.wait(10)
            raise OSError("synthetic disk write failure")
        finally:
            settled.set()

    monkeypatch.setattr(uploads, "_write_upload_chunk", fail_write)

    async def scenario():
        task = asyncio.create_task(call_unwrapped(uploads.upload_files, "failed-owner", request=MagicMock(), files=[_Upload("fail.txt", b"bytes")], config=SimpleNamespace()))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert settled.is_set()
            assert list(directory.iterdir()) == []
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["cancel", "missing_client"])
def test_context_entry_releases_a_late_or_unusable_lease(local_uploads, monkeypatch, failure):
    _, provider = local_uploads
    provider.uses_thread_data_mounts = False

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        holder = SimpleNamespace(sandbox=object() if failure == "cancel" else None, sandbox_id="synthetic", denied=False, release=AsyncMock())

        async def acquire(*args, **kwargs):
            entered.set()
            await release.wait()
            return holder

        monkeypatch.setattr(uploads, "try_acquire_sandbox_for_request", acquire)

        async def enter():
            async with upload_ingestion.ThreadUploadIngestionService(request=None, thread_id="lease-owner", user_id="u", app_config=SimpleNamespace()):
                pytest.fail("failed/cancelled entry must not yield")

        task = asyncio.create_task(enter())
        try:
            await entered.wait()
            if failure == "cancel":
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
            release.set()
            if failure == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(uploads.HTTPException) as error:
                    await task
                assert error.value.status_code == 500
            holder.release.assert_awaited_once()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_request_close_drains_release_under_repeated_cancellation():
    async def scenario():
        entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def release_lease():
            entered.set()
            await release.wait()
            closed.set()

        service = upload_ingestion.ThreadUploadIngestionService(request=None, thread_id="close-owner", user_id="u", app_config=SimpleNamespace())
        service._sandbox_lease = SimpleNamespace(release=release_lease)
        task = asyncio.create_task(service.aclose())
        try:
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set(), "request holder escaped its release"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["close", "staging_unlink", "published_unlink", "companion_unlink"])
@pytest.mark.parametrize("broken_logging", [False, True])
@pytest.mark.parametrize("outcome", ["cancel", "cancel_repeated", "too_large"])
def test_rejected_request_preserves_outcome_when_cleanup_fails(local_uploads, monkeypatch, failure, broken_logging, outcome):
    """Exercise cleanup failures through the real multi-file upload consumer."""
    directory, _ = local_uploads
    survivor = directory / "keep.txt"
    survivor.write_bytes(b"another request")
    monkeypatch.setattr(uploads, "_auto_convert_documents_enabled", lambda _: True)
    monkeypatch.setattr(uploads, "_get_upload_limits", lambda _: SimpleNamespace(max_files=10, max_file_size=20, max_total_size=100))
    captured, record_attempts, diagnostics = [], [], []
    cleanup_entered, cleanup_release = threading.Event(), threading.Event()
    prepare = uploads._prepare_upload_destination
    native_unlink, native_path_unlink = uploads.os.unlink, Path.unlink
    first_record = hashlib.sha256(b"first.pdf").hexdigest() + ".json"
    second_record = hashlib.sha256(b"second.pdf").hexdigest() + ".json"

    def fail_cleanup(message):
        if outcome == "cancel_repeated":
            cleanup_entered.set()
            assert cleanup_release.wait(10), "test did not release the cleanup worker"
        raise OSError(message)

    class FailingClose:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def close(self):
            self.handle.close()
            fail_cleanup("synthetic staged close/flush failure")

    def capture_pending(directory, name):
        staged = prepare(directory, name)
        if name == "pending.txt":
            captured.append(staged)
            if failure == "close":
                staged.handle = FailingClose(staged.handle)
        return staged

    def unlink(path, *args, **kwargs):
        if failure == "staging_unlink" and captured and Path(path) == captured[0].temp_path:
            fail_cleanup("synthetic staging unlink failure")
        if failure == "published_unlink" and Path(path) == directory / "second.pdf":
            fail_cleanup("synthetic published unlink failure")
        return native_unlink(path, *args, **kwargs)

    def unlink_record(path, *args, **kwargs):
        if path.parent == directory.parent / "upload-companions":
            record_attempts.append(path.name)
            if failure == "companion_unlink" and path.name == first_record:
                fail_cleanup("synthetic companion unlink failure")
        return native_path_unlink(path, *args, **kwargs)

    def warn(message, *args, **kwargs):
        diagnostics.append(message)
        if broken_logging:
            raise RuntimeError("synthetic logging handler failure")

    async def convert(source, output_path):
        await run_file_io(output_path.write_bytes, b"converted bytes")
        return output_path

    monkeypatch.setattr(uploads, "_prepare_upload_destination", capture_pending)
    monkeypatch.setattr(uploads, "convert_file_to_markdown", convert)
    monkeypatch.setattr(uploads.os, "unlink", unlink)
    monkeypatch.setattr(Path, "unlink", unlink_record)
    monkeypatch.setattr(uploads.logger, "warning", warn)
    monkeypatch.setattr(upload_ingestion.logger, "warning", warn)
    error_log = MagicMock()
    monkeypatch.setattr(uploads.logger, "error", error_log)

    async def scenario():
        waiting, network = asyncio.Event(), asyncio.Event()

        class PendingUpload:
            filename = "pending.txt"

            async def read(self, size):
                waiting.set()
                if outcome == "too_large":
                    return b"x" * 30
                await network.wait()
                return b""

        files = [_Upload("first.pdf", b"first"), _Upload("second.pdf", b"second"), PendingUpload()]
        task = asyncio.create_task(call_unwrapped(uploads.upload_files, "cleanup-owner", request=MagicMock(), files=files, config=SimpleNamespace()))
        try:
            await asyncio.wait_for(waiting.wait(), 10)
            if outcome != "too_large":
                task.cancel("client disconnected")
                if outcome == "cancel_repeated":
                    assert await asyncio.to_thread(cleanup_entered.wait, 10)
                    task.cancel("host shutdown")
                    await asyncio.sleep(0)
                    task.cancel("repeated host shutdown")
                    cleanup_release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled()
            else:
                with pytest.raises(uploads.HTTPException) as error:
                    await task
                assert error.value.status_code == 413
            error_log.assert_not_called()
            assert diagnostics, "cleanup failure was not reported"
            assert record_attempts == [first_record, second_record], "one failed cleanup skipped the remaining companion"
            assert captured[0].handle.closed
            expected = {survivor}
            if failure == "staging_unlink":
                expected.add(captured[0].temp_path)
            if failure == "published_unlink":
                expected.add(directory / "second.pdf")
            assert set(directory.iterdir()) == expected
            assert survivor.read_bytes() == b"another request"
        finally:
            cleanup_release.set()
            network.set()
            await asyncio.gather(task, return_exceptions=True)
            for staged in captured:
                if not staged.handle.closed:
                    staged.handle.close()
                if staged.temp_path.exists():
                    native_unlink(staged.temp_path)

    asyncio.run(scenario())


def test_failed_lease_release_logging_preserves_request_cancellation(local_uploads, monkeypatch):
    directory, provider = local_uploads
    provider.uses_thread_data_mounts = False
    lease = SimpleNamespace(sandbox=object(), sandbox_id="synthetic", denied=False, release=AsyncMock(side_effect=OSError("synthetic lease release failure")))
    monkeypatch.setattr(uploads, "try_acquire_sandbox_for_request", AsyncMock(return_value=lease))
    monkeypatch.setattr(upload_ingestion.logger, "warning", MagicMock(side_effect=RuntimeError("synthetic logging handler failure")))

    async def scenario():
        waiting, network = asyncio.Event(), asyncio.Event()

        class PendingUpload:
            filename = "pending.txt"

            async def read(self, size):
                waiting.set()
                await network.wait()
                return b""

        task = asyncio.create_task(call_unwrapped(uploads.upload_files, "lease-owner", request=MagicMock(), files=[PendingUpload()], config=SimpleNamespace()))
        try:
            await asyncio.wait_for(waiting.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            lease.release.assert_awaited_once()
            assert list(directory.iterdir()) == []
        finally:
            network.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
