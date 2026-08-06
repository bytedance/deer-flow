"""Tests for deerflow.uploads.manager — shared upload management logic."""

import errno
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from deerflow.uploads.layout import (
    artifact_url_for_virtual_path,
    conversion_path_for_upload,
    conversion_virtual_path,
)
from deerflow.uploads.manager import (
    AtomicUploadPublishError,
    PathTraversalError,
    UnsafeUploadPathError,
    claim_unique_filename,
    cleanup_stale_upload_staging_files,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    publish_upload_bytes,
    publish_upload_copy,
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
# upload publication
# ---------------------------------------------------------------------------


class TestUploadPublication:
    def test_compatibility_wrapper_writes_new_file(self, tmp_path):
        dest = write_upload_file_no_symlink(tmp_path, "notes.txt", b"hello")

        assert dest == tmp_path / "notes.txt"
        assert dest.read_bytes() == b"hello"

    def test_existing_regular_file_is_renamed_not_overwritten(self, tmp_path):
        dest = tmp_path / "notes.txt"
        dest.write_bytes(b"old contents")
        assert os.stat(dest).st_nlink == 1

        result = publish_upload_bytes(tmp_path, "notes.txt", b"new contents")

        assert result == tmp_path / "notes_1.txt"
        assert dest.read_bytes() == b"old contents"
        assert result.read_bytes() == b"new contents"
        assert os.stat(dest).st_nlink == 1

    def test_existing_symlink_is_preserved_and_skipped(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"protected")
        planted = tmp_path / "notes.txt"
        planted.symlink_to(outside)

        result = publish_upload_bytes(tmp_path, "notes.txt", b"new")

        assert result == tmp_path / "notes_1.txt"
        assert planted.is_symlink()
        assert outside.read_bytes() == b"protected"
        assert result.read_bytes() == b"new"

    def test_existing_hard_link_is_preserved_and_skipped(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"protected")
        planted = tmp_path / "notes.txt"
        os.link(outside, planted)

        result = publish_upload_bytes(tmp_path, "notes.txt", b"new")

        assert result == tmp_path / "notes_1.txt"
        assert outside.read_bytes() == b"protected"
        assert planted.read_bytes() == b"protected"
        assert result.read_bytes() == b"new"

    def test_existing_directory_is_preserved_and_skipped(self, tmp_path):
        planted = tmp_path / "notes.txt"
        planted.mkdir()

        result = publish_upload_bytes(tmp_path, "notes.txt", b"new")

        assert result == tmp_path / "notes_1.txt"
        assert planted.is_dir()
        assert result.read_bytes() == b"new"

    def test_parallel_publication_preserves_every_payload(self, tmp_path):
        payloads = [f"payload-{i}".encode() for i in range(12)]

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            paths = list(pool.map(lambda payload: publish_upload_bytes(tmp_path, "same.txt", payload), payloads))

        assert {path.name for path in paths} == {
            "same.txt",
            *(f"same_{i}.txt" for i in range(1, len(payloads))),
        }
        assert {path.read_bytes() for path in paths} == set(payloads)
        assert not list(tmp_path.glob(".upload-*.part"))

    def test_unsupported_atomic_publish_fails_and_cleans_stage(self, tmp_path):
        with patch(
            "deerflow.uploads.manager.os.link",
            side_effect=OSError(errno.EOPNOTSUPP, "hard links unsupported"),
        ):
            with pytest.raises(AtomicUploadPublishError, match="atomic no-replace"):
                publish_upload_bytes(tmp_path, "same.txt", b"payload")

        assert not (tmp_path / "same.txt").exists()
        assert not list(tmp_path.glob(".upload-*.part"))

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("archive.tar.gz", "archive.tar_1.gz"),
            ("README", "README_1"),
            (".env", ".env_1"),
        ],
    )
    def test_suffix_is_inserted_before_final_extension(self, tmp_path, name, expected):
        (tmp_path / name).write_bytes(b"old")

        result = publish_upload_bytes(tmp_path, name, b"new")

        assert result.name == expected
        assert result.read_bytes() == b"new"

    def test_collision_suffix_keeps_filename_within_255_utf8_bytes(self, tmp_path):
        name = f"{'é' * 125}.txt"
        assert len(name.encode("utf-8")) == 254
        (tmp_path / name).write_bytes(b"old")

        result = publish_upload_bytes(tmp_path, name, b"new")

        assert result.name.endswith("_1.txt")
        assert len(result.name.encode("utf-8")) <= 255
        assert result.read_bytes() == b"new"

    def test_publish_upload_copy_stages_complete_source(self, tmp_path):
        source = tmp_path / "source.bin"
        source.write_bytes(b"source bytes")
        uploads = tmp_path / "uploads"
        uploads.mkdir()

        result = publish_upload_copy(uploads, "copied.bin", source)

        assert result == uploads / "copied.bin"
        assert result.read_bytes() == b"source bytes"
        assert not list(uploads.glob(".upload-*.part"))


class TestUploadLayout:
    def test_conversion_layout_uses_full_primary_name(self, tmp_path):
        upload = tmp_path / "user-data" / "uploads" / "report.pdf"

        assert conversion_path_for_upload(upload) == tmp_path / "user-data" / ".upload-conversions" / "report.pdf.md"
        assert conversion_virtual_path("report.pdf") == "/mnt/user-data/.upload-conversions/report.pdf.md"
        assert artifact_url_for_virtual_path("thread-1", conversion_virtual_path("report #1.pdf")) == ("/api/threads/thread-1/artifacts/mnt/user-data/.upload-conversions/report%20%231.pdf.md")


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

    def test_filters_only_upload_staging_files(self, tmp_path):
        (tmp_path / ".env").write_text("intentional dotfile")
        (tmp_path / ".upload-active.part").write_text("partial")
        (tmp_path / ".upload-note.txt").write_text("intentional upload")
        (tmp_path / "draft.part").write_text("intentional upload")
        (tmp_path / "visible.txt").write_text("visible")

        result = list_files_in_dir(tmp_path)

        assert result["count"] == 4
        assert [f["filename"] for f in result["files"]] == [".env", ".upload-note.txt", "draft.part", "visible.txt"]


# ---------------------------------------------------------------------------
# cleanup_stale_upload_staging_files
# ---------------------------------------------------------------------------


class TestCleanupStaleUploadStagingFiles:
    def test_removes_only_stale_staging_files_from_all_upload_layouts(self, tmp_path):
        legacy_uploads = tmp_path / "threads" / "thread-legacy" / "user-data" / "uploads"
        user_uploads = tmp_path / "users" / "owner-1" / "threads" / "thread-owned" / "user-data" / "uploads"
        legacy_conversions = legacy_uploads.parent / ".upload-conversions"
        user_conversions = user_uploads.parent / ".upload-conversions"
        unrelated_uploads = tmp_path / "misc" / "thread-other" / "user-data" / "uploads"
        for uploads_dir in (
            legacy_uploads,
            user_uploads,
            legacy_conversions,
            user_conversions,
            unrelated_uploads,
        ):
            uploads_dir.mkdir(parents=True)

        (legacy_uploads / ".upload-old.part").write_text("legacy partial")
        (user_uploads / ".upload-new.part").write_text("user partial")
        (legacy_conversions / ".upload-converted-old.part").write_text("legacy conversion partial")
        (user_conversions / ".upload-converted-new.part").write_text("user conversion partial")
        (unrelated_uploads / ".upload-ignore.part").write_text("outside layout")
        (legacy_uploads / ".env").write_text("intentional dotfile")
        (legacy_uploads / ".upload-note.txt").write_text("intentional upload")
        (legacy_uploads / "draft.part").write_text("intentional upload")

        removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 4
        assert not (legacy_uploads / ".upload-old.part").exists()
        assert not (user_uploads / ".upload-new.part").exists()
        assert not (legacy_conversions / ".upload-converted-old.part").exists()
        assert not (user_conversions / ".upload-converted-new.part").exists()
        assert (unrelated_uploads / ".upload-ignore.part").exists()
        assert (legacy_uploads / ".env").exists()
        assert (legacy_uploads / ".upload-note.txt").exists()
        assert (legacy_uploads / "draft.part").exists()

    def test_does_not_follow_symlinked_conversion_directory(self, tmp_path):
        user_data = tmp_path / "threads" / "thread-legacy" / "user-data"
        (user_data / "uploads").mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        staged = outside / ".upload-outside.part"
        staged.write_text("outside")
        (user_data / ".upload-conversions").symlink_to(outside, target_is_directory=True)

        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        assert staged.read_text() == "outside"


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

    def test_delete_rejects_path_components(self, tmp_path):
        primary = tmp_path / "report.pdf"
        primary.write_bytes(b"PDF")

        with pytest.raises(PathTraversalError, match="traversal"):
            delete_file_safe(tmp_path, "folder/report.pdf")

        assert primary.exists()

    def test_delete_rejects_symlink_instead_of_unlinking_target(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("protected", encoding="utf-8")
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        planted = uploads / "report.pdf"
        planted.symlink_to(outside)

        with pytest.raises(UnsafeUploadPathError):
            delete_file_safe(uploads, "report.pdf")

        assert planted.is_symlink()
        assert outside.read_text(encoding="utf-8") == "protected"

    def test_delete_removes_owned_conversion_but_preserves_legacy_sibling(self, tmp_path):
        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"PDF")
        legacy_or_user = uploads / "report.md"
        legacy_or_user.write_text("user markdown", encoding="utf-8")
        owned = conversion_path_for_upload(primary)
        owned.parent.mkdir()
        owned.write_text("generated", encoding="utf-8")

        delete_file_safe(uploads, "report.pdf")

        assert not primary.exists()
        assert not owned.exists()
        assert legacy_or_user.read_text(encoding="utf-8") == "user markdown"
