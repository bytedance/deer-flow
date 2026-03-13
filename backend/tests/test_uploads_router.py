import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import UploadFile

from src.gateway.routers import uploads


def test_upload_files_saves_to_local_disk_immediately(tmp_path):
    """Upload saves to local disk immediately and returns fast."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "_background_sync"),  # Don't actually run background
    ):
        file = UploadFile(filename="notes.txt", file=BytesIO(b"hello uploads"))
        result = uploads.upload_files("thread-1", files=[file])

    assert result.success is True
    assert len(result.files) == 1
    assert result.files[0]["filename"] == "notes.txt"
    # File is on local disk immediately
    assert (thread_uploads_dir / "notes.txt").read_bytes() == b"hello uploads"


def test_upload_files_returns_markdown_paths_for_pdf(tmp_path):
    """Upload returns expected markdown paths for convertible files."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "_background_sync"),
    ):
        file = UploadFile(filename="report.pdf", file=BytesIO(b"pdf-bytes"))
        result = uploads.upload_files("thread-1", files=[file])

    assert result.success is True
    file_info = result.files[0]
    assert file_info["filename"] == "report.pdf"
    assert file_info["markdown_file"] == "report.md"
    assert file_info["markdown_virtual_path"] == "/mnt/user-data/uploads/report.md"


def test_upload_files_rejects_dotdot_and_dot_filenames(tmp_path):
    """Path traversal filenames are rejected or normalized."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    with (
        patch.object(uploads, "get_uploads_dir", return_value=thread_uploads_dir),
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "_background_sync"),
    ):
        # These filenames must be rejected outright
        for bad_name in ["..", "."]:
            file = UploadFile(filename=bad_name, file=BytesIO(b"data"))
            result = uploads.upload_files("thread-local", files=[file])
            assert result.success is True
            assert result.files == [], f"Expected no files for unsafe filename {bad_name!r}"

        # Path-traversal prefixes are stripped to the basename and accepted safely
        file = UploadFile(filename="../etc/passwd", file=BytesIO(b"data"))
        result = uploads.upload_files("thread-local", files=[file])
        assert result.success is True
        assert len(result.files) == 1
        assert result.files[0]["filename"] == "passwd"

    # Only the safely normalised file should exist
    assert [f.name for f in thread_uploads_dir.iterdir()] == ["passwd"]


def test_background_sync_uploads_to_storage_and_converts(tmp_path):
    """Background sync uploads to R2 and converts to markdown."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    file_path = thread_uploads_dir / "doc.pdf"
    file_path.write_bytes(b"pdf-content")

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    mock_provider = MagicMock()
    mock_provider.get_existing.return_value = None

    def fake_convert(fp: Path) -> Path:
        md = fp.with_suffix(".md")
        md.write_text("converted", encoding="utf-8")
        return md

    with (
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "get_sandbox_provider", return_value=mock_provider),
        patch.object(uploads, "_convert_file_to_markdown_sync", side_effect=fake_convert),
    ):
        uploads._background_sync("t1", "doc.pdf", b"pdf-content", file_path, ".pdf")

    # Original file uploaded to storage
    mock_storage.write.assert_any_call("threads/t1/uploads/doc.pdf", b"pdf-content")
    # Markdown version uploaded too
    mock_storage.write.assert_any_call("threads/t1/uploads/doc.md", b"converted")


def test_background_sync_syncs_to_existing_sandbox(tmp_path):
    """Background sync pushes files to existing E2B sandbox."""
    thread_uploads_dir = tmp_path / "uploads"
    thread_uploads_dir.mkdir(parents=True)

    file_path = thread_uploads_dir / "data.csv"
    file_path.write_bytes(b"csv-data")

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    sandbox = MagicMock()
    mock_provider = MagicMock()
    mock_provider.get_existing.return_value = "e2b-123"
    mock_provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "get_sandbox_provider", return_value=mock_provider),
    ):
        uploads._background_sync("t1", "data.csv", b"csv-data", file_path, ".csv")

    sandbox.update_file.assert_called_once_with("/mnt/user-data/uploads/data.csv", b"csv-data")


def test_background_sync_skips_local_sandbox(tmp_path):
    """Background sync does not push to local sandbox."""
    file_path = tmp_path / "data.csv"
    file_path.write_bytes(b"csv-data")

    mock_storage = MagicMock()
    mock_storage.upload_key.side_effect = lambda tid, fn: f"threads/{tid}/uploads/{fn}"

    mock_provider = MagicMock()
    mock_provider.get_existing.return_value = "local"
    sandbox = MagicMock()
    mock_provider.get.return_value = sandbox

    with (
        patch.object(uploads, "get_storage", return_value=mock_storage),
        patch.object(uploads, "get_sandbox_provider", return_value=mock_provider),
    ):
        uploads._background_sync("t1", "data.csv", b"csv-data", file_path, ".csv")

    sandbox.update_file.assert_not_called()
