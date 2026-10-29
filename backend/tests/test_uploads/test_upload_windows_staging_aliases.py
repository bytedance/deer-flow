"""Reserved upload names must reject Win32 aliases before any batch side effects."""

import asyncio
import os
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import uploads
from deerflow.uploads.manager import cleanup_stale_upload_staging_files, list_files_in_dir, normalize_filename, write_upload_file_no_symlink

ALIASES = [".upload-notes.part.", ".upload-notes.part ", ".upload-notes.part.. ", ".upload-notes.part .", ".UPLOAD-NOTES.PART", ".Upload-NoTeS.Part", ".UPLOAD-NOTES.PART.", ".Upload-NoTeS.Part ."]


@pytest.mark.parametrize("filename", ALIASES)
def test_normalize_filename_rejects_windows_staging_alias(filename):
    with pytest.raises(ValueError, match="reserved upload staging"):
        normalize_filename(filename)


@pytest.mark.parametrize("filename", ALIASES)
@pytest.mark.parametrize("prefix", ["", "folder/", "folder\\", "C:\\users\\"])
@pytest.mark.parametrize("batch", ["single", "reserved_first", "reserved_last"])
def test_http_rejects_windows_staging_alias_before_starting_batch(tmp_path, filename, prefix, batch):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    existing = uploads_dir / "existing.txt"
    existing.write_bytes(b"existing document")
    app = make_authed_test_app()
    app.include_router(uploads.router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    reserved = ("files", (prefix + filename, b"reserved document"))
    normal = ("files", ("normal.txt", b"normal document"))
    files = [reserved] if batch == "single" else [reserved, normal] if batch == "reserved_first" else [normal, reserved]
    provider = MagicMock()
    provider.uses_thread_data_mounts = True

    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=uploads_dir) as ensure_dir,
        patch.object(uploads, "get_sandbox_provider", return_value=provider) as get_provider,
        TestClient(app) as client,
    ):
        response = client.post("/api/threads/thread-alias/uploads", files=files)

    assert response.status_code == 400
    assert "reserved upload staging" in response.json()["detail"]
    assert "Rename" in response.json()["detail"]
    ensure_dir.assert_not_called()
    get_provider.assert_not_called()
    assert [path.name for path in uploads_dir.iterdir()] == ["existing.txt"]
    assert existing.read_bytes() == b"existing document"


@pytest.mark.parametrize("filename", ALIASES)
@pytest.mark.parametrize("reserved_first", [True, False])
def test_adapter_rejects_windows_staging_alias_before_reading_bytes(tmp_path, filename, reserved_first):
    normal = UploadFile(filename="normal.txt", file=BytesIO(b"normal document"))
    reserved = UploadFile(filename=filename, file=BytesIO(b"reserved document"))
    files = [reserved, normal] if reserved_first else [normal, reserved]
    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    with (
        patch.object(uploads, "ensure_uploads_dir", return_value=tmp_path) as ensure_dir,
        patch.object(uploads, "get_sandbox_provider", return_value=provider) as get_provider,
        pytest.raises(HTTPException) as exc_info,
    ):
        asyncio.run(call_unwrapped(uploads.upload_files, "thread-alias", request=MagicMock(), files=files, config=SimpleNamespace()))

    assert exc_info.value.status_code == 400
    assert "reserved upload staging" in exc_info.value.detail
    assert "Rename" in exc_info.value.detail
    ensure_dir.assert_not_called()
    get_provider.assert_not_called()
    assert all(file.file.tell() == 0 for file in files)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Requires native Win32 filename aliasing")
@pytest.mark.parametrize("filename", ALIASES)
def test_native_windows_alias_rejection_preserves_existing_file(tmp_path, filename):
    canonical = tmp_path / ".upload-notes.part"
    canonical.write_bytes(b"existing staging bytes")
    alias = tmp_path / filename
    # These reads use the real Windows filesystem, with no Path mocks.
    assert alias.read_bytes() == b"existing staging bytes"
    with pytest.raises(ValueError, match="reserved upload staging"):
        write_upload_file_no_symlink(tmp_path, filename, b"new user document")
    assert canonical.read_bytes() == b"existing staging bytes"
    assert [path.name for path in tmp_path.iterdir()] == [".upload-notes.part"]


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot store literal trailing dots or spaces")
@pytest.mark.parametrize("filename", ALIASES)
def test_posix_legacy_alias_files_remain_visible_and_are_not_swept(tmp_path, filename):
    # Each alias gets its own directory so case variants cannot collide on macOS.
    uploads_dir = tmp_path / "threads" / "thread-alias" / "user-data" / "uploads"
    uploads_dir.mkdir(parents=True)
    legacy_file = uploads_dir / filename
    legacy_file.write_bytes(b"legacy user document")
    assert cleanup_stale_upload_staging_files(tmp_path) == 0
    assert [item["filename"] for item in list_files_in_dir(uploads_dir)["files"]] == [filename]
    assert legacy_file.read_bytes() == b"legacy user document"
