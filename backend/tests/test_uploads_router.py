"""Tests for uploads router — thread-first persistence and sandbox sync."""

import asyncio
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import UploadFile

from src.gateway.routers import uploads


def _enter_auth_patches(stack: ExitStack) -> None:
    """Enter context managers that disable auth/rate-limit/quota checks."""
    stack.enter_context(patch.object(uploads, "check_user_api_rate", lambda *a, **kw: None))
    stack.enter_context(patch.object(uploads, "verify_thread_ownership", lambda *a, **kw: None))
    stack.enter_context(patch.object(uploads, "_check_upload_quota", lambda *a, **kw: None))
    stack.enter_context(patch.object(uploads, "_record_upload", lambda **kw: None))


def test_upload_files_writes_thread_storage_and_skips_local_sandbox_sync(tmp_path):
    """Local sandbox: files are written to thread dir, sandbox.update_file is NOT called."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with ExitStack() as stack:
        _enter_auth_patches(stack)
        stack.enter_context(patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir))
        stack.enter_context(patch.object(uploads, "get_sandbox_provider", return_value=provider))

        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = asyncio.run(
            uploads.upload_files(
                "thread-local",
                current_user={"id": "test-user"},
                files=[file],
            )
        )

    assert result.success is True
    assert len(result.files) == 1
    assert result.files[0]["filename"] == "notes.txt"
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"hello uploads"

    sandbox.update_file.assert_not_called()


def test_upload_files_syncs_non_local_sandbox_and_marks_markdown_file(tmp_path):
    """Non-local sandbox: files are written to thread dir AND synced to sandbox."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "aio-1"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    async def fake_convert(file_path: Path) -> Path:
        md_path = file_path.with_suffix(".md")
        md_path.write_text("converted", encoding="utf-8")
        return md_path

    with ExitStack() as stack:
        _enter_auth_patches(stack)
        stack.enter_context(patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir))
        stack.enter_context(patch.object(uploads, "get_sandbox_provider", return_value=provider))
        stack.enter_context(patch.object(uploads, "convert_file_to_markdown", AsyncMock(side_effect=fake_convert)))

        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = asyncio.run(
            uploads.upload_files(
                "thread-aio",
                current_user={"id": "test-user"},
                files=[file],
            )
        )

    assert result.success is True
    assert len(result.files) == 1
    file_info = result.files[0]
    assert file_info["filename"] == "report.pdf"
    assert file_info["markdown_file"] == "report.md"

    assert (thread_uploads_dir / "report.pdf").read_bytes() == b"pdf-bytes"
    assert (thread_uploads_dir / "report.md").read_text(encoding="utf-8") == "converted"

    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.pdf", b"pdf-bytes")
    sandbox.update_file.assert_any_call("/mnt/user-data/uploads/report.md", b"converted")


def test_upload_files_rejects_dotdot_and_dot_filenames(tmp_path):
    """Unsafe filenames '.' and '..' are rejected; path-traversal prefixes are stripped."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    provider = MagicMock()
    provider.acquire.return_value = "local"
    sandbox = MagicMock()
    provider.get.return_value = sandbox

    with ExitStack() as stack:
        _enter_auth_patches(stack)
        stack.enter_context(patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir))
        stack.enter_context(patch.object(uploads, "get_sandbox_provider", return_value=provider))

        # These filenames must be rejected outright
        for bad_name in ["..", "."]:
            file = UploadFile(filename=bad_name, file=BytesIO(b"data"))
            result = asyncio.run(
                uploads.upload_files(
                    "thread-local",
                    current_user={"id": "test-user"},
                    files=[file],
                )
            )
            assert result.success is True
            assert result.files == [], f"Expected no files for unsafe filename {bad_name!r}"

        # Path-traversal prefixes are stripped to the basename and accepted safely
        file = UploadFile(filename="../etc/secret.txt", file=BytesIO(b"data"))
        result = asyncio.run(
            uploads.upload_files(
                "thread-local",
                current_user={"id": "test-user"},
                files=[file],
            )
        )
        assert result.success is True
        assert len(result.files) == 1
        assert result.files[0]["filename"] == "secret.txt"

    # Only the safely normalised file should exist
    assert [f.name for f in thread_uploads_dir.iterdir()] == ["secret.txt"]
