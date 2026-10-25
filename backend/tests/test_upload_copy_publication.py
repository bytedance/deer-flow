"""Upload publication rejects substituted staging paths and preserves outcomes."""

import os
import shutil
from pathlib import Path

import pytest
from support.symlinks import symlink_or_skip

from deerflow.uploads.manager import UnsafeUploadPathError, copy_upload_file_no_replace


@pytest.fixture
def upload_paths(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = tmp_path / "notes.txt"
    source.write_bytes(b"uploaded content")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must not be published")
    return uploads, source, outside


def replace_staging(staging, outside, replacement):
    try:
        staging.unlink()
    except PermissionError:
        if os.name == "nt":
            pytest.skip("host prevents replacing an open staging file")
        raise
    if replacement == "symlink":
        symlink_or_skip(staging, outside)
    else:
        staging.write_bytes(b"substituted content")


@pytest.mark.parametrize("replacement", ["symlink", "regular"])
@pytest.mark.parametrize("nofollow", [True, False])
def test_rejects_staging_replaced_during_copy(upload_paths, monkeypatch, replacement, nofollow):
    uploads, source, outside = upload_paths
    real_copy = shutil.copyfileobj
    monkeypatch.setattr(os, "supports_follow_symlinks", {os.link} if nofollow else set())

    def copy_and_swap(src, dst):
        real_copy(src, dst)
        staging = next(uploads.glob(".upload-*.part"))
        replace_staging(staging, outside, replacement)

    monkeypatch.setattr(shutil, "copyfileobj", copy_and_swap)
    with pytest.raises(UnsafeUploadPathError):
        copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert not os.path.lexists(uploads / "notes.txt")
    assert outside.read_bytes() == b"must not be published"
    assert outside.stat().st_nlink == 1
    assert list(uploads.iterdir()) == []


@pytest.mark.parametrize("replacement", ["symlink", "regular"])
@pytest.mark.parametrize("nofollow", [True, False])
def test_rejects_staging_replaced_at_link(upload_paths, monkeypatch, replacement, nofollow):
    uploads, source, outside = upload_paths
    real_link = os.link
    if nofollow and real_link not in os.supports_follow_symlinks:
        pytest.skip("host does not support no-follow hard links")
    calls = []

    def swap_and_link(staging, dest, **kwargs):
        replace_staging(staging, outside, replacement)
        calls.append(kwargs)
        real_link(staging, dest, **kwargs)

    monkeypatch.setattr(os, "link", swap_and_link)
    monkeypatch.setattr(os, "supports_follow_symlinks", {swap_and_link} if nofollow else set())
    with pytest.raises(UnsafeUploadPathError):
        copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert calls == [{"follow_symlinks": False} if nofollow else {}]
    assert not os.path.lexists(uploads / "notes.txt")
    assert outside.read_bytes() == b"must not be published"
    assert outside.stat().st_nlink == 1
    assert list(uploads.iterdir()) == []


@pytest.mark.parametrize("nofollow", [True, False])
def test_publishes_with_supported_link_options(upload_paths, monkeypatch, nofollow):
    uploads, source, _outside = upload_paths
    real_link = os.link
    if nofollow and real_link not in os.supports_follow_symlinks:
        pytest.skip("host does not support no-follow hard links")
    calls = []

    def record_link(staging, dest, **kwargs):
        calls.append(kwargs)
        real_link(staging, dest, **kwargs)

    monkeypatch.setattr(os, "link", record_link)
    monkeypatch.setattr(os, "supports_follow_symlinks", {record_link} if nofollow else set())
    dest = copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert dest.read_bytes() == b"uploaded content"
    if os.name != "nt":
        # Windows never decrements the link count when the staged name is removed,
        # so a freshly published upload reads back as ``st_nlink == 2`` there.
        assert dest.stat().st_nlink == 1
    assert calls == [{"follow_symlinks": False} if nofollow else {}]


def test_cleanup_directory_swap_does_not_mask_success(upload_paths, monkeypatch, caplog):
    uploads, source, _outside = upload_paths
    real_link = os.link
    planted = []

    def publish_and_swap(staging, dest, **kwargs):
        real_link(staging, dest, **kwargs)
        try:
            staging.unlink()
        except PermissionError:
            if os.name == "nt":
                pytest.skip("host prevents replacing an open staging file")
            raise
        staging.mkdir()
        planted.append(staging)

    monkeypatch.setattr(os, "link", publish_and_swap)
    dest = copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert dest.read_bytes() == b"uploaded content"
    assert planted[0].is_dir()
    assert "Failed to remove upload staging file" in caplog.text


def test_cleanup_error_does_not_mask_copy_failure(upload_paths, monkeypatch, caplog):
    uploads, source, _outside = upload_paths
    real_unlink = Path.unlink

    def fail_copy(src, dst):
        dst.write(b"partial")
        raise OSError("original copy failure")

    def fail_cleanup(path, *args, **kwargs):
        if path.name.startswith(".upload-"):
            raise PermissionError("cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(OSError, match="original copy failure"):
        copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert not (uploads / "notes.txt").exists()
    assert "Failed to remove upload staging file" in caplog.text


def test_cleanup_error_does_not_mask_collision(upload_paths, monkeypatch, caplog):
    uploads, source, _outside = upload_paths
    dest = uploads / "notes.txt"
    dest.write_bytes(b"keep existing upload")
    real_unlink = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.name.startswith(".upload-"):
            raise PermissionError("cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(FileExistsError):
        copy_upload_file_no_replace(uploads, "notes.txt", source)

    assert dest.read_bytes() == b"keep existing upload"
    assert "Failed to remove upload staging file" in caplog.text


@pytest.mark.parametrize("collisions", [0, 2])
def test_publication_retry_uses_original_seed(upload_paths, collisions):
    from deerflow.uploads.manager import publish_upload_copy

    uploads, source, _outside = upload_paths
    seen = {"notes.txt", "notes_1.txt"}
    for index in range(1, collisions + 1):
        (uploads / f"notes_{index}.txt").write_bytes(f"existing-{index}".encode())

    dest = publish_upload_copy(uploads, "notes_1.txt", source, claim_seed="notes.txt", seen_names=seen)

    assert dest.name == f"notes_{collisions + 1}.txt"
    assert dest.read_bytes() == b"uploaded content"
    assert dest.name in seen
    for index in range(1, collisions + 1):
        assert (uploads / f"notes_{index}.txt").read_bytes() == f"existing-{index}".encode()
    assert not list(uploads.glob(".upload-*.part"))


def test_publication_retry_preserves_noncollision_errors(upload_paths, monkeypatch):
    from deerflow.uploads import manager

    uploads, source, _outside = upload_paths

    def fail_link(*args, **kwargs):
        raise PermissionError("publication denied")

    monkeypatch.setattr(manager.os, "link", fail_link)
    with pytest.raises(PermissionError, match="publication denied"):
        manager.publish_upload_copy(uploads, "notes.txt", source, claim_seed="notes.txt", seen_names={"notes.txt"})
    assert list(uploads.iterdir()) == []
