"""An unsafe upload must stay a skip even when its capture cannot be discarded.

``upload_files`` rejects a destination that resolves outside the uploads
directory and moves on to the next file. On Windows the staged conversion
capture can still be locked at that point, so an unguarded discard turned the
skip into a ``PermissionError`` for the whole batch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.client import DeerFlowClient
from deerflow.uploads.manager import UnsafeUploadPathError


@pytest.fixture
def upload_case(monkeypatch, tmp_path):
    import deerflow.client as client_module

    uploads = tmp_path / "thread/user-data/uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(client_module, "ensure_uploads_dir", lambda *_args, **_kwargs: uploads)
    return DeerFlowClient.__new__(DeerFlowClient), uploads, client_module


def test_unsafe_upload_stays_a_skip_when_discarding_its_capture_fails(upload_case, tmp_path, monkeypatch):
    client, uploads, client_module = upload_case

    unsafe = tmp_path / "unsafe.pdf"
    unsafe.write_bytes(b"%PDF unsafe")
    keep = tmp_path / "keep.txt"
    keep.write_bytes(b"keep me")

    real_publish = client_module.publish_upload_copy

    def publish(uploads_dir, dest_name, src_path, **_kwargs):
        if Path(src_path).name == unsafe.name:
            raise UnsafeUploadPathError("destination escapes the uploads directory")
        return real_publish(uploads_dir, dest_name, src_path, **_kwargs)

    monkeypatch.setattr(client_module, "publish_upload_copy", publish)

    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if "deerflow-upload-source-" in str(self):
            raise PermissionError("capture is still open")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    result = client.upload_files("skip-thread", [unsafe, keep])

    assert result["skipped_files"] == [unsafe.name]
    assert [item["filename"] for item in result["files"]] == [keep.name]
    assert (uploads / keep.name).read_bytes() == b"keep me"


def test_successful_upload_survives_a_capture_it_cannot_discard(upload_case, tmp_path, monkeypatch):
    """A locked capture must not replace a completed upload or drop later files."""
    client, uploads, _client_module = upload_case

    convertible = tmp_path / "report.pdf"
    convertible.write_bytes(b"%PDF report")
    keep = tmp_path / "keep.txt"
    keep.write_bytes(b"keep me")

    real_unlink = Path.unlink

    def unlink(self, *args, **kwargs):
        if "deerflow-upload-source-" in str(self):
            raise PermissionError("capture is still open")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    result = client.upload_files("successful-thread", [convertible, keep])

    assert result["skipped_files"] == []
    assert [item["filename"] for item in result["files"]] == [convertible.name, keep.name]
    assert (uploads / keep.name).read_bytes() == b"keep me"


def test_capture_directory_cleanup_failure_does_not_fail_the_batch(upload_case, tmp_path, monkeypatch):
    """The ``finally`` rmtree must not replace an outcome the batch already decided."""
    import tempfile

    client, _uploads, _client_module = upload_case

    convertible = tmp_path / "report.pdf"
    convertible.write_bytes(b"%PDF report")

    real_rmtree = tempfile.TemporaryDirectory._rmtree.__func__

    def rmtree(cls, name, ignore_errors=False, repeated=False):
        # A locked capture: exactly what CPython's onexc re-raises when the
        # directory's cleanup is not told to ignore errors.
        if "deerflow-upload-source-" in str(name) and not ignore_errors:
            raise PermissionError("capture directory is still open")
        return real_rmtree(cls, name, ignore_errors=ignore_errors, repeated=repeated)

    monkeypatch.setattr(tempfile.TemporaryDirectory, "_rmtree", classmethod(rmtree))

    result = client.upload_files("cleanup-thread", [convertible])

    assert [item["filename"] for item in result["files"]] == [convertible.name]
