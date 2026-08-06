import asyncio
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import uploads
from deerflow.sandbox.sandbox import Sandbox
from deerflow.uploads.layout import conversion_path_for_upload
from deerflow.uploads.lease import UploadNameLease
from deerflow.uploads.manager import create_upload_staging_file, delete_file_safe, publish_upload_bytes_leased


class ChunkedUpload:
    def __init__(self, filename: str, chunks: list[bytes]):
        self.filename = filename
        self._chunks = list(chunks)
        self.read_calls: list[int | None] = []

    async def read(self, size: int | None = None) -> bytes:
        self.read_calls.append(size)
        if size is None:
            raise AssertionError("upload must be read with an explicit chunk size")
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def _mounted_provider() -> MagicMock:
    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    return provider


def _symlink_to_or_skip(link_path: Path, target_path: Path) -> None:
    try:
        link_path.symlink_to(target_path)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is not available")
        raise


def _fake_owned_conversion(content_by_source: dict[str, str] | None = None):
    async def fake_convert(file_path: Path, *, publication=None) -> Path:
        assert publication is not None
        assert publication.path == file_path
        assert publication.is_active
        md_path = conversion_path_for_upload(file_path)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        if content_by_source is not None and file_path.name in content_by_source:
            text = content_by_source[file_path.name]
        else:
            text = f"converted-from:{file_path.name}"
        md_path.write_text(text, encoding="utf-8")
        return md_path

    return fake_convert


def test_sandbox_remove_file_uses_provider_virtual_path_resolution():
    commands: list[str] = []

    class FakeSandbox:
        @staticmethod
        def _resolve_path(path: str) -> str:
            assert path == "/mnt/user-data/uploads/report final.pdf"
            return "/home/sandbox/uploads/report final.pdf"

        @staticmethod
        def execute_command(command: str) -> str:
            commands.append(command)
            return "__DEERFLOW_REMOVE_FILE_OK_abc123__"

    with patch("deerflow.sandbox.sandbox.secrets.token_hex", return_value="abc123"):
        Sandbox.remove_file(FakeSandbox(), "/mnt/user-data/uploads/report final.pdf")

    assert commands == ["rm -f -- '/home/sandbox/uploads/report final.pdf' && printf '%s\\n' __DEERFLOW_REMOVE_FILE_OK_abc123__"]


def test_sandbox_remove_file_rejects_error_output_containing_legacy_marker():
    class FakeSandbox:
        @staticmethod
        def execute_command(_command: str) -> str:
            return "rm: cannot remove '__DEERFLOW_REMOVE_FILE_OK__': Permission denied"

    with patch("deerflow.sandbox.sandbox.secrets.token_hex", return_value="abc123"):
        with pytest.raises(OSError, match="did not confirm"):
            Sandbox.remove_file(FakeSandbox(), "/mnt/user-data/uploads/__DEERFLOW_REMOVE_FILE_OK__")


def test_cleanup_uses_publication_identity_not_reused_path(tmp_path):
    publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
    try:
        publication.path.unlink()
        publication.path.write_bytes(b"new")

        uploads._cleanup_published_uploads([publication], [])

        assert (tmp_path / "report.pdf").read_bytes() == b"new"
    finally:
        publication.release()


def test_upload_lease_is_held_through_response_postprocessing(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    postprocess_started = threading.Event()
    allow_postprocess = threading.Event()

    def pause_postprocessing(paths):
        postprocess_started.set()
        assert allow_postprocess.wait(5)

    async def run_lifecycle():
        upload_task = asyncio.create_task(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))],
                config=SimpleNamespace(),
            )
        )
        assert await asyncio.to_thread(postprocess_started.wait, 5)
        deletion = asyncio.create_task(asyncio.to_thread(delete_file_safe, thread_uploads_dir, "report.pdf"))
        await asyncio.sleep(0.05)
        assert not deletion.done()
        allow_postprocess.set()
        result = await upload_task
        await deletion
        return result

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"report.pdf": "converted"})),
        ),
        patch.object(uploads, "_make_uploaded_paths_sandbox_readable", side_effect=pause_postprocessing),
    ):
        result = asyncio.run(run_lifecycle())

    assert result.success is True
    assert result.files[0].markdown_file == "report.pdf.md"
    assert not (thread_uploads_dir / "report.pdf").exists()
    assert not conversion_path_for_upload(thread_uploads_dir / "report.pdf").exists()


def test_sandbox_sync_failure_rolls_back_published_generation(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = MagicMock()
    sandbox.update_file.side_effect = RuntimeError("sync failed")
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                call_unwrapped(
                    uploads.upload_files,
                    "thread-aio",
                    request=MagicMock(),
                    files=[UploadFile(filename="notes.txt", file=BytesIO(b"payload"))],
                    config=SimpleNamespace(),
                )
            )

    assert exc_info.value.status_code == 500
    assert not (thread_uploads_dir / "notes.txt").exists()


def test_partial_sandbox_sync_failure_removes_all_attempted_remote_paths(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire_async = AsyncMock(return_value="remote-1")
    sandbox = MagicMock()
    synced_paths: list[str] = []

    def update_file(virtual_path: str, _data: bytes) -> None:
        if virtual_path.endswith("second.txt"):
            raise RuntimeError("second sync failed")
        synced_paths.append(virtual_path)

    sandbox.update_file.side_effect = update_file
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                call_unwrapped(
                    uploads.upload_files,
                    "thread-remote",
                    request=MagicMock(),
                    files=[
                        UploadFile(filename="first.txt", file=BytesIO(b"first")),
                        UploadFile(filename="second.txt", file=BytesIO(b"second")),
                    ],
                    config=SimpleNamespace(),
                )
            )

    assert exc_info.value.status_code == 500
    assert synced_paths == ["/mnt/user-data/uploads/first.txt"]
    assert [record.args[0] for record in sandbox.remove_file.call_args_list] == [
        "/mnt/user-data/uploads/second.txt",
        "/mnt/user-data/uploads/first.txt",
    ]
    assert not (thread_uploads_dir / "first.txt").exists()
    assert not (thread_uploads_dir / "second.txt").exists()


def test_post_commit_sandbox_error_removes_attempted_remote_path(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire_async = AsyncMock(return_value="remote-1")
    remote_files: dict[str, bytes] = {}
    removed_paths: list[str] = []

    class Sandbox:
        def update_file(self, virtual_path: str, data: bytes) -> None:
            remote_files[virtual_path] = data
            raise RuntimeError("transport failed after commit")

        def remove_file(self, virtual_path: str) -> None:
            removed_paths.append(virtual_path)
            remote_files.pop(virtual_path, None)

    provider.get.return_value = Sandbox()

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        with pytest.raises(HTTPException):
            asyncio.run(
                call_unwrapped(
                    uploads.upload_files,
                    "thread-remote",
                    request=MagicMock(),
                    files=[UploadFile(filename="notes.txt", file=BytesIO(b"payload"))],
                    config=SimpleNamespace(),
                )
            )

    assert remote_files == {}
    assert removed_paths == ["/mnt/user-data/uploads/notes.txt"]
    assert not (thread_uploads_dir / "notes.txt").exists()


@pytest.mark.asyncio
async def test_cancellation_during_staging_creation_drains_and_aborts(tmp_path):
    staging_created = threading.Event()
    allow_create_to_return = threading.Event()
    real_create = create_upload_staging_file

    def paused_create(base_dir: Path):
        staged = real_create(base_dir)
        staging_created.set()
        assert allow_create_to_return.wait(5)
        return staged

    with patch.object(uploads, "create_upload_staging_file", side_effect=paused_create):
        task = asyncio.create_task(
            uploads._write_upload_file_with_limits(
                UploadFile(filename="notes.txt", file=BytesIO(b"payload")),
                uploads_dir=tmp_path,
                display_filename="notes.txt",
                max_single_file_size=1024,
                max_total_size=1024,
                total_size=0,
            )
        )
        assert await asyncio.to_thread(staging_created.wait, 5)
        try:
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done()
        finally:
            allow_create_to_return.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert list(tmp_path.glob(".upload-*.part")) == []


@pytest.mark.asyncio
async def test_cancellation_during_final_release_returns_committed_success(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire_async = AsyncMock(return_value="remote-1")
    remote_files: dict[str, bytes] = {}

    class Sandbox:
        def update_file(self, virtual_path: str, data: bytes) -> None:
            remote_files[virtual_path] = data

        def remove_file(self, virtual_path: str) -> None:
            remote_files.pop(virtual_path, None)

    provider.get.return_value = Sandbox()
    release_started = threading.Event()
    allow_release = threading.Event()
    real_release = uploads._release_publications

    def paused_release(publications):
        release_started.set()
        assert allow_release.wait(5)
        real_release(publications)

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_release_publications", side_effect=paused_release),
    ):
        task = asyncio.create_task(
            call_unwrapped(
                uploads.upload_files,
                "thread-remote",
                request=MagicMock(),
                files=[UploadFile(filename="notes.txt", file=BytesIO(b"payload"))],
                config=SimpleNamespace(),
            )
        )
        assert await asyncio.to_thread(release_started.wait, 5)
        try:
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done()
        finally:
            allow_release.set()
        result = await task

    assert result.success is True
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"payload"
    assert remote_files == {"/mnt/user-data/uploads/notes.txt": b"payload"}


@pytest.mark.asyncio
async def test_cancellation_after_remote_sync_still_removes_the_completed_copy(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire_async = AsyncMock(return_value="remote-1")
    sandbox = MagicMock()
    sync_started = threading.Event()
    allow_sync = threading.Event()

    def update_file(_virtual_path: str, _data: bytes) -> None:
        sync_started.set()
        assert allow_sync.wait(5)

    sandbox.update_file.side_effect = update_file
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        upload_task = asyncio.create_task(
            call_unwrapped(
                uploads.upload_files,
                "thread-remote",
                request=MagicMock(),
                files=[UploadFile(filename="notes.txt", file=BytesIO(b"payload"))],
                config=SimpleNamespace(),
            )
        )
        assert await asyncio.to_thread(sync_started.wait, 5)
        upload_task.cancel()
        allow_sync.set()
        with pytest.raises(asyncio.CancelledError):
            await upload_task

    sandbox.remove_file.assert_called_once_with("/mnt/user-data/uploads/notes.txt")
    assert not (thread_uploads_dir / "notes.txt").exists()


@pytest.mark.asyncio
async def test_busy_publication_uses_suffix_without_waiting_for_lease(tmp_path):
    first = UploadNameLease.acquire(tmp_path, "report.pdf")
    staged = create_upload_staging_file(tmp_path)
    staged.handle.write(b"second")
    publication_task = asyncio.create_task(uploads._publish_staged_upload_cancellation_safe(staged, "report.pdf"))
    second = None
    try:
        second = await asyncio.wait_for(publication_task, timeout=2)
        assert first.is_active
    finally:
        if first.is_active:
            first.release()
        if second is not None:
            second.release()

    assert second is not None
    assert second.path.name == "report_1.pdf"


@pytest.mark.asyncio
async def test_waiting_delete_cannot_starve_general_io_lease_release(tmp_path, monkeypatch):
    import deerflow.utils.file_io as file_io_module

    publication = publish_upload_bytes_leased(tmp_path, "notes.txt", b"payload")
    single_worker = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(file_io_module, "_FILE_IO_EXECUTOR", single_worker)

    with patch.object(uploads, "get_uploads_dir", return_value=tmp_path):
        deletion = asyncio.create_task(call_unwrapped(uploads.delete_uploaded_file, "thread-delete", "notes.txt", request=MagicMock()))
        await asyncio.sleep(0.05)
        release = asyncio.create_task(uploads._run_file_io_commit(publication.release))
        try:
            await asyncio.wait_for(asyncio.shield(release), timeout=0.2)
            await asyncio.wait_for(deletion, timeout=2)
        finally:
            if publication.is_active:
                publication.release()
            await release
            await deletion
            single_worker.shutdown(wait=True)

    assert not (tmp_path / "notes.txt").exists()


def test_upload_files_writes_thread_storage_and_skips_local_sandbox_sync(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    assert len(result.files) == 1
    assert result.files[0].filename == "notes.txt"
    assert result.files[0].size == len(b"hello uploads")
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"hello uploads"

    sandbox.update_file.assert_not_called()


def test_upload_and_list_response_models_expose_size_as_int(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    (thread_uploads_dir / "notes.txt").write_bytes(b"hello uploads")

    paths = MagicMock()
    paths.sandbox_uploads_dir.return_value = thread_uploads_dir

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_paths", return_value=paths),
    ):
        result = asyncio.run(call_unwrapped(uploads.list_uploaded_files, "thread-local", request=MagicMock()))

    assert result.count == 1
    assert result.files[0].filename == "notes.txt"
    assert result.files[0].size == len(b"hello uploads")


def test_upload_openapi_schema_exposes_file_size_as_integer():
    upload_schema = uploads.UploadResponse.model_json_schema()
    list_schema = uploads.UploadListResponse.model_json_schema()

    assert upload_schema["$defs"]["UploadedFileInfo"]["properties"]["size"]["type"] == "integer"
    assert list_schema["$defs"]["UploadedFileInfo"]["properties"]["size"]["type"] == "integer"


def test_upload_files_auto_renames_duplicate_form_filenames(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="data.txt", file=BytesIO(b"first")),
                    UploadFile(filename="data.txt", file=BytesIO(b"second")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert [file_info.filename for file_info in result.files] == ["data.txt", "data_1.txt"]
    assert result.files[0].original_filename is None
    assert result.files[1].original_filename == "data.txt"
    assert (thread_uploads_dir / "data.txt").read_bytes() == b"first"
    assert (thread_uploads_dir / "data_1.txt").read_bytes() == b"second"


def test_separate_upload_requests_never_replace_same_name(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    async def upload(payload: bytes):
        return await call_unwrapped(
            uploads.upload_files,
            "thread-local",
            request=MagicMock(),
            files=[UploadFile(filename="report.txt", file=BytesIO(payload))],
            config=SimpleNamespace(),
        )

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
    ):
        first = asyncio.run(upload(b"first"))
        second = asyncio.run(upload(b"second"))

    assert [first.files[0].filename, second.files[0].filename] == ["report.txt", "report_1.txt"]
    assert (thread_uploads_dir / "report.txt").read_bytes() == b"first"
    assert (thread_uploads_dir / "report_1.txt").read_bytes() == b"second"


def test_concurrent_upload_requests_preserve_all_payloads(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    payloads = [f"payload-{index}".encode() for index in range(8)]

    async def upload(payload: bytes):
        return await call_unwrapped(
            uploads.upload_files,
            "thread-local",
            request=MagicMock(),
            files=[UploadFile(filename="same.bin", file=BytesIO(payload))],
            config=SimpleNamespace(),
        )

    async def run_all():
        return await asyncio.gather(*(upload(payload) for payload in payloads))

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
    ):
        results = asyncio.run(run_all())

    paths = [thread_uploads_dir / result.files[0].filename for result in results]
    assert len({path.name for path in paths}) == len(payloads)
    assert {path.read_bytes() for path in paths} == set(payloads)


def test_upload_files_skips_acquire_when_thread_data_is_mounted(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.acquire_async = AsyncMock()

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-mounted", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"hello uploads"
    provider.acquire.assert_not_called()
    provider.acquire_async.assert_not_awaited()
    provider.get.assert_not_called()


def test_upload_files_does_not_auto_convert_documents_by_default(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=False),
        patch.object(uploads, "convert_uploaded_file_to_markdown", AsyncMock()) as convert_mock,
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    assert len(result.files) == 1
    assert result.files[0].filename == "report.pdf"
    assert result.files[0].markdown_file is None
    convert_mock.assert_not_called()
    assert not conversion_path_for_upload(thread_uploads_dir / "report.pdf").exists()


def test_upload_files_syncs_non_local_sandbox_and_marks_markdown_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"report.pdf": "converted"})),
        ),
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    assert len(result.files) == 1
    file_info = result.files[0]
    assert file_info.filename == "report.pdf"
    assert file_info.markdown_file == "report.pdf.md"
    assert file_info.markdown_virtual_path == "/mnt/user-data/.upload-conversions/report.pdf.md"
    assert file_info.markdown_artifact_url == ("/api/threads/thread-aio/artifacts/mnt/user-data/.upload-conversions/report.pdf.md")

    assert (thread_uploads_dir / "report.pdf").read_bytes() == b"pdf-bytes"
    conversion = conversion_path_for_upload(thread_uploads_dir / "report.pdf")
    assert conversion.read_text(encoding="utf-8") == "converted"

    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.pdf", b"pdf-bytes")
    sandbox.update_file.assert_any_call("/mnt/user-data/.upload-conversions/report.pdf.md", b"converted")


def test_upload_files_makes_non_local_files_sandbox_writable(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"report.pdf": "converted"})),
        ),
        patch.object(uploads, "_make_file_sandbox_writable") as make_writable,
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    make_writable.assert_any_call(thread_uploads_dir / "report.pdf")
    make_writable.assert_any_call(conversion_path_for_upload(thread_uploads_dir / "report.pdf"))


def test_upload_files_does_not_adjust_permissions_for_local_sandbox(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.needs_upload_permission_adjustment = False
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_make_file_sandbox_writable") as make_writable,
        patch.object(uploads, "_make_file_sandbox_readable") as make_readable,
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    make_writable.assert_not_called()
    # Readable adjustment is now always applied regardless of sandbox type
    make_readable.assert_called_once()
    called_path = make_readable.call_args[0][0]
    assert called_path.name == "notes.txt"


def test_upload_files_acquires_non_local_sandbox_before_writing(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    def acquire_before_writes(thread_id: str, *, user_id: str | None = None) -> str:
        assert list(thread_uploads_dir.iterdir()) == []
        assert user_id == "owner-upload"
        return "aio-1"

    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(side_effect=acquire_before_writes)

    with (
        patch.object(uploads, "get_effective_user_id", return_value="owner-upload"),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    provider.acquire.assert_not_called()
    provider.acquire_async.assert_awaited_once_with("thread-aio", user_id="owner-upload")
    sandbox.update_file.assert_called_once_with("/mnt/user-data/uploads/notes.txt", b"hello uploads")


def test_upload_files_fails_before_writing_when_non_local_sandbox_unavailable(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(side_effect=RuntimeError("sandbox unavailable"))
    file = ChunkedUpload("notes.txt", [b"hello uploads"])

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        with pytest.raises(RuntimeError, match="sandbox unavailable"):
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert list(thread_uploads_dir.iterdir()) == []
    assert file.read_calls == []
    provider.acquire.assert_not_called()
    provider.get.assert_not_called()


def test_upload_files_rejects_too_many_files_before_writing(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_get_upload_limits", return_value=uploads.UploadLimits(max_files=1, max_file_size=10, max_total_size=20)),
    ):
        files = [
            ChunkedUpload("one.txt", [b"one"]),
            ChunkedUpload("two.txt", [b"two"]),
        ]
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=files, config=SimpleNamespace()))

    assert exc_info.value.status_code == 413
    assert list(thread_uploads_dir.iterdir()) == []
    assert files[0].read_calls == []
    assert files[1].read_calls == []


def test_upload_files_rejects_oversized_single_file_and_removes_partial_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = _mounted_provider()
    file = ChunkedUpload("big.txt", [b"123456"])

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_get_upload_limits", return_value=uploads.UploadLimits(max_files=10, max_file_size=5, max_total_size=20)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert exc_info.value.status_code == 413
    assert not (thread_uploads_dir / "big.txt").exists()
    assert file.read_calls == [8192]
    provider.acquire.assert_not_called()


def test_upload_files_rejects_total_size_over_limit_and_cleans_request_files(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_get_upload_limits", return_value=uploads.UploadLimits(max_files=10, max_file_size=10, max_total_size=5)),
    ):
        files = [
            ChunkedUpload("first.txt", [b"123"]),
            ChunkedUpload("second.txt", [b"456"]),
        ]
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=files, config=SimpleNamespace()))

    assert exc_info.value.status_code == 413
    assert not (thread_uploads_dir / "first.txt").exists()
    assert not (thread_uploads_dir / "second.txt").exists()


def test_upload_files_does_not_sync_non_local_sandbox_when_total_size_exceeds_limit(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_effective_user_id", return_value="owner-upload"),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_get_upload_limits", return_value=uploads.UploadLimits(max_files=10, max_file_size=10, max_total_size=5)),
    ):
        files = [
            ChunkedUpload("first.txt", [b"123"]),
            ChunkedUpload("second.txt", [b"456"]),
        ]
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=files, config=SimpleNamespace()))

    assert exc_info.value.status_code == 413
    provider.acquire.assert_not_called()
    provider.acquire_async.assert_awaited_once_with("thread-aio", user_id="owner-upload")
    provider.get.assert_called_once_with("aio-1")
    sandbox.update_file.assert_not_called()


def test_upload_files_keeps_and_syncs_primary_when_conversion_fails(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.uses_thread_data_mounts = False
    provider.acquire.side_effect = AssertionError("upload route should use acquire_async")
    provider.acquire_async = AsyncMock(return_value="aio-1")
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_effective_user_id", return_value="owner-upload"),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=RuntimeError("conversion failed")),
        ),
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-aio",
                request=MagicMock(),
                files=[file],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert result.files[0].filename == "report.pdf"
    assert result.files[0].markdown_file is None
    provider.acquire.assert_not_called()
    provider.acquire_async.assert_awaited_once_with("thread-aio", user_id="owner-upload")
    provider.get.assert_called_once_with("aio-1")
    sandbox.update_file.assert_called_once_with("/mnt/user-data/uploads/report.pdf", b"pdf-bytes")
    assert (thread_uploads_dir / "report.pdf").read_bytes() == b"pdf-bytes"


def test_make_file_sandbox_writable_adds_write_bits_for_regular_files(tmp_path):
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"pdf-bytes")
    os_chmod_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    file_path.chmod(os_chmod_mode)

    uploads._make_file_sandbox_writable(file_path)

    updated_mode = stat.S_IMODE(file_path.stat().st_mode)
    assert updated_mode & stat.S_IWUSR
    assert updated_mode & stat.S_IWGRP
    assert updated_mode & stat.S_IWOTH


def test_make_file_sandbox_writable_skips_symlinks(tmp_path):
    file_path = tmp_path / "target-link.txt"
    file_path.write_text("hello", encoding="utf-8")
    symlink_stat = MagicMock(st_mode=stat.S_IFLNK)

    with (
        patch.object(uploads.os, "lstat", return_value=symlink_stat),
        patch.object(uploads.os, "chmod") as chmod,
    ):
        uploads._make_file_sandbox_writable(file_path)

    chmod.assert_not_called()


def test_make_file_sandbox_readable_adds_read_bits_for_regular_files(tmp_path):
    file_path = tmp_path / "data.csv"
    file_path.write_bytes(b"csv-data")
    # Simulate the 0o600 permissions set by open_upload_file_no_symlink
    file_path.chmod(0o600)

    uploads._make_file_sandbox_readable(file_path)

    updated_mode = stat.S_IMODE(file_path.stat().st_mode)
    assert updated_mode & stat.S_IRUSR
    assert updated_mode & stat.S_IRGRP
    assert updated_mode & stat.S_IROTH


def test_make_file_sandbox_readable_skips_symlinks(tmp_path):
    file_path = tmp_path / "target-link.txt"
    file_path.write_text("hello", encoding="utf-8")
    symlink_stat = MagicMock(st_mode=stat.S_IFLNK)

    with (
        patch.object(uploads.os, "lstat", return_value=symlink_stat),
        patch.object(uploads.os, "chmod") as chmod,
    ):
        uploads._make_file_sandbox_readable(file_path)

    chmod.assert_not_called()


def test_upload_files_adjusts_read_permissions_for_mounted_non_local_sandbox(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    # AIO sandbox with LocalContainerBackend: uses_thread_data_mounts=True
    # but needs_upload_permission_adjustment=True (default)
    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    provider.needs_upload_permission_adjustment = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_make_file_sandbox_readable") as make_readable,
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-aio", request=MagicMock(), files=[file], config=SimpleNamespace()))

    assert result.success is True
    make_readable.assert_called_once()
    called_path = make_readable.call_args[0][0]
    assert called_path.name == "notes.txt"


def test_upload_files_renames_portable_aliases_within_one_batch(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = _mounted_provider()

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-aliases",
                request=MagicMock(),
                files=[
                    UploadFile(filename="Report.txt", file=BytesIO(b"first")),
                    UploadFile(filename="report.txt", file=BytesIO(b"second")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert [file.filename for file in result.files] == ["Report.txt", "report_1.txt"]
    assert (thread_uploads_dir / "Report.txt").read_bytes() == b"first"
    assert (thread_uploads_dir / "report_1.txt").read_bytes() == b"second"


@pytest.mark.asyncio
async def test_inverse_portable_alias_gateway_batches_do_not_deadlock(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    provider = _mounted_provider()
    first_publications = asyncio.Barrier(2)
    real_publish = uploads._publish_staged_upload_cancellation_safe

    async def pause_after_each_batch_publishes_first(staged, filename, reserved_coordination_keys=None):
        publication = await real_publish(staged, filename, reserved_coordination_keys)
        if filename in {"A.txt", "b.txt"}:
            await first_publications.wait()
        return publication

    async def run_batch(files):
        return await call_unwrapped(
            uploads.upload_files,
            "thread-aliases",
            request=MagicMock(),
            files=files,
            config=SimpleNamespace(),
        )

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
        patch.object(uploads, "_publish_staged_upload_cancellation_safe", side_effect=pause_after_each_batch_publishes_first),
    ):
        result_one, result_two = await asyncio.wait_for(
            asyncio.gather(
                run_batch(
                    [
                        UploadFile(filename="A.txt", file=BytesIO(b"A")),
                        UploadFile(filename="B.txt", file=BytesIO(b"B")),
                    ]
                ),
                run_batch(
                    [
                        UploadFile(filename="b.txt", file=BytesIO(b"b")),
                        UploadFile(filename="a.txt", file=BytesIO(b"a")),
                    ]
                ),
            ),
            timeout=5,
        )

    assert [file.filename for file in result_one.files] == ["A.txt", "B_1.txt"]
    assert [file.filename for file in result_two.files] == ["b.txt", "a_1.txt"]


def test_upload_files_rejects_dotdot_and_dot_filenames(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        # These filenames must be rejected outright
        for bad_name in ["..", "."]:
            file = UploadFile(filename=bad_name, file=BytesIO(b"data"))
            result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))
            assert result.success is True
            assert result.files == [], f"Expected no files for unsafe filename {bad_name!r}"

        # Path-traversal prefixes are stripped to the basename and accepted safely
        file = UploadFile(filename="../etc/passwd", file=BytesIO(b"data"))
        result = asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=[file], config=SimpleNamespace()))
        assert result.success is True
        assert len(result.files) == 1
        assert result.files[0].filename == "passwd"

    # Only the safely normalised file should exist
    assert [f.name for f in thread_uploads_dir.iterdir()] == ["passwd"]


def test_upload_files_renames_around_preexisting_symlink_destination(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("protected", encoding="utf-8")
    _symlink_to_or_skip(thread_uploads_dir / "victim.txt", outside_file)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="victim.txt", file=BytesIO(b"attacker upload"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert result.files[0].filename == "victim_1.txt"
    assert result.files[0].original_filename == "victim.txt"
    assert outside_file.read_text(encoding="utf-8") == "protected"
    assert (thread_uploads_dir / "victim.txt").is_symlink()
    assert (thread_uploads_dir / "victim_1.txt").read_bytes() == b"attacker upload"


def test_upload_files_renames_around_dangling_symlink_destination(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    missing_target = tmp_path / "missing-target.txt"
    _symlink_to_or_skip(thread_uploads_dir / "victim.txt", missing_target)

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="victim.txt", file=BytesIO(b"attacker upload"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert result.files[0].filename == "victim_1.txt"
    assert not missing_target.exists()
    assert (thread_uploads_dir / "victim.txt").is_symlink()
    assert (thread_uploads_dir / "victim_1.txt").read_bytes() == b"attacker upload"


def test_upload_files_renames_around_hardlinked_destination_without_truncating(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("protected", encoding="utf-8")
    os.link(outside_file, thread_uploads_dir / "victim.txt")

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="victim.txt", file=BytesIO(b"attacker upload"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert result.files[0].filename == "victim_1.txt"
    assert outside_file.read_text(encoding="utf-8") == "protected"
    assert (thread_uploads_dir / "victim.txt").read_text(encoding="utf-8") == "protected"
    assert (thread_uploads_dir / "victim_1.txt").read_bytes() == b"attacker upload"


def test_upload_files_renames_existing_regular_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    existing_file = thread_uploads_dir / "notes.txt"
    existing_file.write_bytes(b"old upload")
    assert existing_file.stat().st_nlink == 1

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"new upload"))
        result = asyncio.run(uploads.upload_files("thread-local", files=[file]))

    assert result.success is True
    assert [file_info.filename for file_info in result.files] == ["notes_1.txt"]
    assert existing_file.read_bytes() == b"old upload"
    assert (thread_uploads_dir / "notes_1.txt").read_bytes() == b"new upload"
    assert existing_file.stat().st_nlink == 1


def test_upload_files_oversized_replacement_preserves_existing_regular_file(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    existing_file = thread_uploads_dir / "a.txt"
    existing_file.write_bytes(b"original bytes")

    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=provider),
    ):
        file = ChunkedUpload("a.txt", [b"tiny", b"x" * 8])

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                call_unwrapped(
                    uploads.upload_files,
                    "thread-local",
                    request=MagicMock(),
                    files=[file],
                    config=SimpleNamespace(uploads={"max_file_size": 10}),
                )
            )

    assert exc_info.value.status_code == 413
    assert existing_file.read_bytes() == b"original bytes"
    assert [path.name for path in thread_uploads_dir.iterdir()] == ["a.txt"]


def test_delete_uploaded_file_removes_owned_conversion_and_preserves_user_markdown(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    primary = thread_uploads_dir / "report.pdf"
    primary.write_bytes(b"pdf-bytes")
    user_markdown = thread_uploads_dir / "report.md"
    user_markdown.write_text("user", encoding="utf-8")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_text("converted", encoding="utf-8")

    with patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir):
        result = asyncio.run(call_unwrapped(uploads.delete_uploaded_file, "thread-aio", "report.pdf", request=MagicMock()))

    assert result == {"success": True, "message": "Deleted report.pdf"}
    assert not primary.exists()
    assert not conversion.exists()
    assert user_markdown.read_text(encoding="utf-8") == "user"


@pytest.mark.skipif(os.name == "nt", reason="POSIX legacy filenames are not representable on Windows")
def test_delete_uploaded_file_accepts_listed_legacy_posix_filename(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)
    legacy = thread_uploads_dir / "CON"
    legacy.write_bytes(b"legacy")

    with patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir):
        result = asyncio.run(
            call_unwrapped(
                uploads.delete_uploaded_file,
                "thread-legacy",
                legacy.name,
                request=MagicMock(),
            )
        )

    assert result == {"success": True, "message": "Deleted CON"}
    assert not legacy.exists()


def test_auto_convert_documents_enabled_defaults_to_false_on_config_errors():
    class BrokenConfig:
        def __getattribute__(self, name):
            if name == "uploads":
                raise RuntimeError("boom")
            return super().__getattribute__(name)

    assert uploads._auto_convert_documents_enabled(BrokenConfig()) is False


def test_auto_convert_documents_enabled_reads_dict_backed_uploads_config():
    cfg = MagicMock()
    cfg.uploads = {"auto_convert_documents": True}

    assert uploads._auto_convert_documents_enabled(cfg) is True


def test_auto_convert_documents_enabled_accepts_boolean_and_string_truthy_values():
    false_cfg = MagicMock()
    false_cfg.uploads = MagicMock(auto_convert_documents=False)

    true_cfg = MagicMock()
    true_cfg.uploads = MagicMock(auto_convert_documents=True)

    string_true_cfg = MagicMock()
    string_true_cfg.uploads = MagicMock(auto_convert_documents="YES")

    string_false_cfg = MagicMock()
    string_false_cfg.uploads = MagicMock(auto_convert_documents="false")

    assert uploads._auto_convert_documents_enabled(false_cfg) is False
    assert uploads._auto_convert_documents_enabled(true_cfg) is True
    assert uploads._auto_convert_documents_enabled(string_true_cfg) is True
    assert uploads._auto_convert_documents_enabled(string_false_cfg) is False


def test_upload_limits_endpoint_reads_uploads_config():
    cfg = MagicMock()
    cfg.uploads = {
        "max_files": 15,
        "max_file_size": "1048576",
        "max_total_size": 2097152,
    }

    result = asyncio.run(call_unwrapped(uploads.get_upload_limits, "thread-local", request=MagicMock(), config=cfg))

    assert result.max_files == 15
    assert result.max_file_size == 1048576
    assert result.max_total_size == 2097152


def test_upload_limits_endpoint_requires_thread_access():
    cfg = MagicMock()
    cfg.uploads = {}
    app = make_authed_test_app(owner_check_passes=False)
    app.state.config = cfg
    app.dependency_overrides[get_config] = lambda: cfg
    app.include_router(uploads.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-local/uploads/limits")

    assert response.status_code == 404


def test_upload_limits_accept_legacy_config_keys():
    cfg = MagicMock()
    cfg.uploads = {
        "max_file_count": 7,
        "max_single_file_size": 123,
        "max_total_size": 456,
    }

    limits = uploads._get_upload_limits(cfg)

    assert limits == uploads.UploadLimits(max_files=7, max_file_size=123, max_total_size=456)


def test_upload_files_uses_configured_file_count_limit(tmp_path):
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    cfg = MagicMock()
    cfg.uploads = {"max_files": 1}

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
    ):
        files = [
            ChunkedUpload("one.txt", [b"one"]),
            ChunkedUpload("two.txt", [b"two"]),
        ]
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(call_unwrapped(uploads.upload_files, "thread-local", request=MagicMock(), files=files, config=cfg))

    assert exc_info.value.status_code == 413


def test_upload_files_converted_markdown_does_not_overwrite_user_markdown(tmp_path):
    """Owned conversion output must not clobber a same-request Markdown upload."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"notes.docx": "FROM_DOCX"})),
        ),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="notes.md", file=BytesIO(b"USER_MARKDOWN")),
                    UploadFile(filename="notes.docx", file=BytesIO(b"DOCX")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert [f.filename for f in result.files] == ["notes.md", "notes.docx"]
    # User upload preserved
    assert (thread_uploads_dir / "notes.md").read_bytes() == b"USER_MARKDOWN"
    assert result.files[1].markdown_file == "notes.docx.md"
    assert conversion_path_for_upload(thread_uploads_dir / "notes.docx").read_text(encoding="utf-8") == "FROM_DOCX"


def test_upload_files_two_convertibles_get_distinct_markdown_companions(tmp_path):
    """Two convertible files sharing a stem must not share one .md path."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"a.docx": "FROM_DOCX", "a.pdf": "FROM_PDF"})),
        ),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="a.docx", file=BytesIO(b"DOCX")),
                    UploadFile(filename="a.pdf", file=BytesIO(b"PDF")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert result.files[0].markdown_file == "a.docx.md"
    assert result.files[1].markdown_file == "a.pdf.md"
    assert conversion_path_for_upload(thread_uploads_dir / "a.docx").read_text(encoding="utf-8") == "FROM_DOCX"
    assert conversion_path_for_upload(thread_uploads_dir / "a.pdf").read_text(encoding="utf-8") == "FROM_PDF"


def test_upload_files_user_markdown_after_convertible_keeps_its_name(tmp_path):
    """Generated output uses a separate namespace from a later user Markdown."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=_fake_owned_conversion({"notes.docx": "FROM_DOCX"})),
        ),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="notes.docx", file=BytesIO(b"DOCX")),
                    UploadFile(filename="notes.md", file=BytesIO(b"USER_MARKDOWN")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert result.files[0].filename == "notes.docx"
    assert result.files[0].markdown_file == "notes.docx.md"
    assert result.files[1].filename == "notes.md"
    assert result.files[1].original_filename is None
    assert (thread_uploads_dir / "notes.md").read_bytes() == b"USER_MARKDOWN"
    assert conversion_path_for_upload(thread_uploads_dir / "notes.docx").read_text(encoding="utf-8") == "FROM_DOCX"


def test_upload_files_failed_conversion_releases_the_claimed_markdown_name(tmp_path):
    """A conversion that writes nothing must not reserve stem.md against later uploads."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(uploads, "convert_uploaded_file_to_markdown", AsyncMock(return_value=None)),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="notes.docx", file=BytesIO(b"DOCX")),
                    UploadFile(filename="notes.md", file=BytesIO(b"USER_MARKDOWN")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert result.files[0].markdown_file is None
    assert result.files[1].filename == "notes.md"
    assert result.files[1].original_filename is None
    assert (thread_uploads_dir / "notes.md").read_bytes() == b"USER_MARKDOWN"
    assert not conversion_path_for_upload(thread_uploads_dir / "notes.docx").exists()


def test_upload_files_failed_conversion_does_not_push_the_next_companion_to_suffix(tmp_path):
    """The second victim of a stale claim: a later convertible's companion."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    async def convert_failing_on_docx(file_path: Path, *, publication=None) -> Path | None:
        assert publication is not None
        assert publication.path == file_path
        assert publication.is_active
        if file_path.suffix.lower() == ".docx":
            return None
        md_path = conversion_path_for_upload(file_path)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(f"FROM:{file_path.name}", encoding="utf-8")
        return md_path

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "ensure_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_sandbox_provider", return_value=_mounted_provider()),
        patch.object(uploads, "_auto_convert_documents_enabled", return_value=True),
        patch.object(
            uploads,
            "convert_uploaded_file_to_markdown",
            AsyncMock(side_effect=convert_failing_on_docx),
        ),
    ):
        result = asyncio.run(
            call_unwrapped(
                uploads.upload_files,
                "thread-local",
                request=MagicMock(),
                files=[
                    UploadFile(filename="notes.docx", file=BytesIO(b"DOCX")),
                    UploadFile(filename="notes.pdf", file=BytesIO(b"PDF")),
                ],
                config=SimpleNamespace(),
            )
        )

    assert result.success is True
    assert result.files[0].markdown_file is None
    assert result.files[1].markdown_file == "notes.pdf.md"
    assert conversion_path_for_upload(thread_uploads_dir / "notes.pdf").read_text(encoding="utf-8") == "FROM:notes.pdf"
