"""Tests for deerflow.uploads.manager — shared upload management logic."""

import errno
import os
from unittest.mock import patch

import pytest

from deerflow.uploads.manager import (
    PathTraversalError,
    UnsafeUploadPathError,
    claim_unique_filename,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    validate_path_traversal,
    write_upload_file_no_symlink,
)

# ---------------------------------------------------------------------------
# normalize_filename
# ---------------------------------------------------------------------------


class TestNormalizeFilename:
    def test_safe_filename(self):
        assert normalize_filename("report.pdf") == "report.pdf"

    def test_strips_path_components(self):
        assert normalize_filename("../../etc/passwd") == "passwd"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_filename("")

    def test_rejects_dot_dot(self):
        with pytest.raises(ValueError, match="unsafe"):
            normalize_filename("..")

    def test_strips_separators(self):
        assert normalize_filename("path/to/file.txt") == "file.txt"

    def test_dot_only(self):
        with pytest.raises(ValueError, match="unsafe"):
            normalize_filename(".")


# ---------------------------------------------------------------------------
# claim_unique_filename
# ---------------------------------------------------------------------------


class TestDeduplicateFilename:
    def test_no_collision(self):
        seen: set[str] = set()
        assert claim_unique_filename("data.txt", seen) == "data.txt"
        assert "data.txt" in seen

    def test_single_collision(self):
        seen = {"data.txt"}
        assert claim_unique_filename("data.txt", seen) == "data_1.txt"
        assert "data_1.txt" in seen

    def test_triple_collision(self):
        seen = {"data.txt", "data_1.txt", "data_2.txt"}
        assert claim_unique_filename("data.txt", seen) == "data_3.txt"
        assert "data_3.txt" in seen

    def test_mutates_seen(self):
        seen: set[str] = set()
        claim_unique_filename("a.txt", seen)
        claim_unique_filename("a.txt", seen)
        assert seen == {"a.txt", "a_1.txt"}


# ---------------------------------------------------------------------------
# validate_path_traversal
# ---------------------------------------------------------------------------


class TestValidatePathTraversal:
    def test_inside_base_ok(self, tmp_path):
        child = tmp_path / "file.txt"
        child.touch()
        validate_path_traversal(child, tmp_path)  # no exception

    def test_outside_base_raises(self, tmp_path):
        outside = tmp_path / ".." / "evil.txt"
        with pytest.raises(PathTraversalError, match="traversal"):
            validate_path_traversal(outside, tmp_path)

    def test_symlink_escape(self, tmp_path):
        target = tmp_path.parent / "secret.txt"
        target.touch()
        link = tmp_path / "escape"
        try:
            link.symlink_to(target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("symlink creation requires Developer Mode or elevated privileges on Windows")
            raise
        with pytest.raises(PathTraversalError, match="traversal"):
            validate_path_traversal(link, tmp_path)


# ---------------------------------------------------------------------------
# write_upload_file_no_symlink
# ---------------------------------------------------------------------------


class TestWriteUploadFileNoSymlink:
    def test_writes_new_file(self, tmp_path):
        dest = write_upload_file_no_symlink(tmp_path, "notes.txt", b"hello")

        assert dest == tmp_path / "notes.txt"
        assert dest.read_bytes() == b"hello"

    def test_overwrites_existing_regular_file_with_single_link(self, tmp_path):
        dest = tmp_path / "notes.txt"
        dest.write_bytes(b"old contents")
        assert os.stat(dest).st_nlink == 1

        result = write_upload_file_no_symlink(tmp_path, "notes.txt", b"new contents")

        assert result == dest
        assert dest.read_bytes() == b"new contents"
        assert os.stat(dest).st_nlink == 1

    def test_fails_closed_without_no_follow_support(self, tmp_path, monkeypatch):
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)

        with pytest.raises(UnsafeUploadPathError, match="O_NOFOLLOW"):
            write_upload_file_no_symlink(tmp_path, "notes.txt", b"hello")

        assert not (tmp_path / "notes.txt").exists()

    def test_open_uses_nonblocking_flag_when_available(self, tmp_path):
        with patch("deerflow.uploads.manager.os.open", side_effect=OSError(errno.ENXIO, "no reader")) as open_mock:
            with pytest.raises(UnsafeUploadPathError, match="Unsafe upload destination"):
                write_upload_file_no_symlink(tmp_path, "pipe.txt", b"hello")

        flags = open_mock.call_args.args[1]
        assert flags & os.O_NONBLOCK

    @pytest.mark.parametrize("open_errno", [errno.ENXIO, errno.EAGAIN])
    def test_nonblocking_special_file_open_errors_are_unsafe(self, tmp_path, open_errno):
        with patch("deerflow.uploads.manager.os.open", side_effect=OSError(open_errno, "would block")):
            with pytest.raises(UnsafeUploadPathError, match="Unsafe upload destination"):
                write_upload_file_no_symlink(tmp_path, "pipe.txt", b"hello")

        assert not (tmp_path / "pipe.txt").exists()


# ---------------------------------------------------------------------------
# list_files_in_dir
# ---------------------------------------------------------------------------


class TestListFilesInDir:
    def test_empty_dir(self, tmp_path):
        result = list_files_in_dir(tmp_path)
        assert result == {"files": [], "count": 0}

    def test_nonexistent_dir(self, tmp_path):
        result = list_files_in_dir(tmp_path / "nope")
        assert result == {"files": [], "count": 0}

    def test_multiple_files_sorted(self, tmp_path):
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "a.txt").write_text("a")
        result = list_files_in_dir(tmp_path)
        assert result["count"] == 2
        assert result["files"][0]["filename"] == "a.txt"
        assert result["files"][1]["filename"] == "b.txt"
        for f in result["files"]:
            assert set(f.keys()) == {"filename", "size", "path", "extension", "modified"}

    def test_ignores_subdirectories(self, tmp_path):
        (tmp_path / "file.txt").write_text("data")
        (tmp_path / "subdir").mkdir()
        result = list_files_in_dir(tmp_path)
        assert result["count"] == 1
        assert result["files"][0]["filename"] == "file.txt"


# ---------------------------------------------------------------------------
# delete_file_safe
# ---------------------------------------------------------------------------


class TestDeleteFileSafe:
    def test_delete_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("data")
        result = delete_file_safe(tmp_path, "test.txt")
        assert result["success"] is True
        assert not f.exists()

    def test_delete_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            delete_file_safe(tmp_path, "nope.txt")

    def test_delete_traversal_raises(self, tmp_path):
        with pytest.raises(PathTraversalError, match="traversal"):
            delete_file_safe(tmp_path, "../outside.txt")
