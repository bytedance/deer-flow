"""Tests for deerflow.uploads.manager — shared upload management logic."""

import pytest

from deerflow.uploads.manager import (
    PathTraversalError,
    claim_unique_filename,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    validate_path_traversal,
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
        link.symlink_to(target)
        with pytest.raises(PathTraversalError, match="traversal"):
            validate_path_traversal(link, tmp_path)


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
