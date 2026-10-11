"""Tests for deerflow.uploads.manager — shared upload management logic."""

import errno
import logging
import os
import shutil
import stat
import time
from datetime import timedelta
from unittest.mock import patch

import pytest

from deerflow.uploads.manager import (
    PathTraversalError,
    UnsafeUploadPathError,
    apply_upload_sandbox_permits,
    claim_unique_filename,
    cleanup_stale_upload_staging_files,
    copy_upload_file_no_symlink,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    validate_path_traversal,
    validate_upload_destination,
    write_upload_file_no_symlink,
)


@pytest.mark.skipif(not (hasattr(os, "O_NOFOLLOW") and hasattr(os, "fchmod")), reason="POSIX-only: O_NOFOLLOW + fchmod")
def test_apply_upload_sandbox_permits_propagates_permission_errors(tmp_path):
    upload = tmp_path / "attachment.bin"
    upload.write_bytes(b"attachment")
    upload.chmod(0o600)

    with patch.object(os, "fchmod", side_effect=PermissionError("permission denied")):
        with pytest.raises(PermissionError, match="permission denied"):
            apply_upload_sandbox_permits(upload, stat.S_IRGRP | stat.S_IROTH)

    assert stat.S_IMODE(upload.stat().st_mode) == 0o600


def test_apply_upload_sandbox_permits_fallback_propagates_permission_errors(tmp_path, monkeypatch):
    upload = tmp_path / "attachment.bin"
    upload.write_bytes(b"attachment")
    upload.chmod(0o600)
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)

    with patch.object(os, "chmod", side_effect=PermissionError("permission denied")):
        with pytest.raises(PermissionError, match="permission denied"):
            apply_upload_sandbox_permits(upload, stat.S_IRGRP | stat.S_IROTH)


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

    def test_rejects_embedded_nul(self):
        with pytest.raises(ValueError, match="NUL"):
            normalize_filename("report\x00.pdf")

    @pytest.mark.parametrize("filename", [".upload-notes.part", ".upload-.part", "folder/.upload-notes.part"])
    def test_rejects_reserved_staging_names(self, filename):
        with pytest.raises(ValueError, match="reserved upload staging"):
            normalize_filename(filename)

    @pytest.mark.parametrize("filename", [".upload-notes.txt", "notes.part", ".env", ".UPLOAD-notes.txt", "notes.PART"])
    def test_keeps_non_staging_names(self, filename):
        assert normalize_filename(filename) == filename

    def test_reserved_name_rejected_before_writing_upload(self, tmp_path):
        with pytest.raises(ValueError, match="reserved upload staging"):
            write_upload_file_no_symlink(tmp_path, ".upload-notes.part", b"user document")
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize(
        "filename",
        ["CON", "con.txt", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9", "COM¹", "com².txt", "COM³.log", "LPT¹", "lpt².md", "LPT³.pdf", "file.txt.", "file.txt ", "a.", "folder/CON"],
    )
    def test_rejects_windows_incompatible_names(self, filename):
        with pytest.raises(ValueError, match="not portable to Windows"):
            normalize_filename(filename)

    @pytest.mark.parametrize("filename", ["CONIN$", "conin$", "CONOUT$", "conout$", "CONIN$.txt", "folder/CONOUT$.log"])
    def test_rejects_windows_console_device_names(self, filename):
        with pytest.raises(ValueError, match="reserved Windows device name"):
            normalize_filename(filename)

    @pytest.mark.parametrize("filename", ["NUL .txt", "con  .log", "COM1 .txt", "lpt²  .md", "CONIN$ .txt", "conout$  .log"])
    def test_rejects_windows_device_names_with_spaces_before_extension(self, filename):
        with pytest.raises(ValueError, match="reserved Windows device name"):
            normalize_filename(filename)

    @pytest.mark.parametrize("filename", ["report .txt", "NULnotes .txt", "COM¹notes .txt", "NUL\u00a0.txt"])
    def test_preserves_spaces_in_ordinary_filename_stems(self, filename):
        assert normalize_filename(filename) == filename

    @pytest.mark.parametrize("filename", ["CONIN", "CONOUT", "CONIN$notes.txt", "CONOUT$notes.log"])
    def test_allows_names_resembling_console_devices(self, filename):
        assert normalize_filename(filename) == filename

    @pytest.mark.parametrize("filename", ["report.pdf", "contour.txt", "console.log", "COM0", "COM10", "COM⁴.txt", "LPT⁵", "COM¹notes.txt", "LPT²0.md", ".gitignore"])
    def test_allows_portable_names(self, filename):
        assert normalize_filename(filename) == filename

    def test_reserved_parent_is_stripped_with_the_directory(self):
        assert normalize_filename("CON/notes.md") == "notes.md"


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

    def test_case_insensitive_collision_including_suffix(self):
        seen = {"Report.txt", "report_1.TXT"}
        assert claim_unique_filename("report.txt", seen) == "report_2.txt"
        assert "report_2.txt" in seen

    def test_triple_collision(self):
        seen = {"data.txt", "data_1.txt", "data_2.txt"}
        assert claim_unique_filename("data.txt", seen) == "data_3.txt"
        assert "data_3.txt" in seen

    def test_mutates_seen(self):
        seen: set[str] = set()
        claim_unique_filename("a.txt", seen)
        claim_unique_filename("a.txt", seen)
        assert seen == {"a.txt", "a_1.txt"}

    def test_max_length_name_stays_within_filename_limit(self):
        # A 255-byte name passes normalize_filename; the deduplicated name
        # must not exceed that limit, or the write path rejects it.
        name = "a" * 251 + ".txt"
        seen = {name}
        deduped = claim_unique_filename(name, seen)
        assert deduped != name
        assert deduped.endswith("_1.txt")
        assert len(deduped.encode("utf-8")) <= 255
        # The truncated result must round-trip through normalize_filename.
        assert normalize_filename(deduped) == deduped

    def test_max_length_collisions_stay_unique_across_truncation(self):
        name = "a" * 251 + ".txt"
        seen = {name}
        first = claim_unique_filename(name, seen)
        second = claim_unique_filename(name, seen)
        assert first != second
        assert len(second.encode("utf-8")) <= 255

    def test_multibyte_stem_is_truncated_on_a_codepoint_boundary(self):
        # 85 CJK chars × 3 bytes = 255 bytes.
        name = "深" * 85
        seen = {name}
        deduped = claim_unique_filename(name, seen)
        assert len(deduped.encode("utf-8")) <= 255
        assert deduped.endswith("_1")
        # No replacement characters / decode artifacts.
        deduped.encode("utf-8").decode("utf-8")

    def test_short_names_keep_existing_dedupe_shape(self):
        seen = {"data.txt"}
        assert claim_unique_filename("data.txt", seen) == "data_1.txt"


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
    @pytest.mark.parametrize("without_nofollow", [False, True])
    def test_exclusive_write_treats_existing_hardlink_as_collision(self, tmp_path, monkeypatch, without_nofollow):
        if without_nofollow:
            monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
        source = tmp_path / "source.txt"
        source.write_bytes(b"existing upload")
        os.link(source, tmp_path / "notes.txt")

        with pytest.raises(FileExistsError):
            write_upload_file_no_symlink(tmp_path, "notes.txt", b"new attachment", exclusive=True)
        # The default replacement path still rejects hardlinks outright.
        with pytest.raises(UnsafeUploadPathError, match="multiple links"):
            write_upload_file_no_symlink(tmp_path, "notes.txt", b"replacement")

        assert source.read_bytes() == b"existing upload"
        assert (tmp_path / "notes.txt").read_bytes() == b"existing upload"

    @pytest.mark.parametrize("without_nofollow", [False, True])
    def test_exclusive_write_preserves_existing_file(self, tmp_path, monkeypatch, without_nofollow):
        if without_nofollow:
            monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
        dest = tmp_path / "notes.txt"
        dest.write_bytes(b"previous upload")

        with pytest.raises(FileExistsError):
            write_upload_file_no_symlink(tmp_path, "notes.txt", b"new attachment", exclusive=True)

        assert dest.read_bytes() == b"previous upload"

    @pytest.mark.parametrize("without_nofollow", [False, True])
    def test_exclusive_write_creates_new_file(self, tmp_path, monkeypatch, without_nofollow):
        if without_nofollow:
            monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)

        dest = write_upload_file_no_symlink(tmp_path, "notes.txt", b"new attachment", exclusive=True)

        assert dest == tmp_path / "notes.txt"
        assert dest.read_bytes() == b"new attachment"

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

    def test_fallback_without_no_follow_support_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)

        # When O_NOFOLLOW is absent (Windows), the function falls back to
        # a dual-lstat + fstat approach and succeeds.
        result = write_upload_file_no_symlink(tmp_path, "notes.txt", b"hello")
        assert result == tmp_path / "notes.txt"
        assert (tmp_path / "notes.txt").read_bytes() == b"hello"

    def test_open_uses_nonblocking_flag_when_available(self, tmp_path):
        if not hasattr(os, "O_NONBLOCK"):
            pytest.skip("O_NONBLOCK not available on this platform")
        with patch("deerflow.uploads.manager.os.open", side_effect=OSError(errno.ENXIO, "no reader")) as open_mock:
            with pytest.raises(UnsafeUploadPathError, match="Unsafe upload destination"):
                write_upload_file_no_symlink(tmp_path, "pipe.txt", b"hello")

        flags = open_mock.call_args.args[1]
        assert flags & os.O_NONBLOCK

    @pytest.mark.parametrize("open_errno", [errno.ENXIO, errno.EAGAIN])
    def test_nonblocking_special_file_open_errors_are_unsafe(self, tmp_path, open_errno):
        if not hasattr(os, "O_NONBLOCK"):
            pytest.skip("O_NONBLOCK not available on this platform")
        with patch("deerflow.uploads.manager.os.open", side_effect=OSError(open_errno, "would block")):
            with pytest.raises(UnsafeUploadPathError, match="Unsafe upload destination"):
                write_upload_file_no_symlink(tmp_path, "pipe.txt", b"hello")

        assert not (tmp_path / "pipe.txt").exists()


# ---------------------------------------------------------------------------
# copy_upload_file_no_symlink
# ---------------------------------------------------------------------------


class TestCopyUploadFileNoSymlink:
    def test_copies_content_mode_and_timestamps(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        src = tmp_path / "notes.txt"
        src.write_bytes(b"hello")
        os.chmod(src, 0o640)
        os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

        dest = copy_upload_file_no_symlink(uploads, "notes.txt", src)

        assert dest == uploads / "notes.txt"
        assert dest.read_bytes() == b"hello"
        if os.chmod in os.supports_fd:
            assert stat.S_IMODE(os.stat(dest).st_mode) == 0o640
        if os.utime in os.supports_fd:
            assert os.stat(dest).st_mtime_ns == 1_700_000_000_000_000_000

    def test_overwrites_existing_regular_file(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        (uploads / "notes.txt").write_bytes(b"old contents")
        src = tmp_path / "notes.txt"
        src.write_bytes(b"new contents")

        dest = copy_upload_file_no_symlink(uploads, "notes.txt", src)

        assert dest.read_bytes() == b"new contents"

    def test_rejects_symlink_destination(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"original")
        link = uploads / "notes.txt"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("symlink creation requires Developer Mode or elevated privileges on Windows")
            raise
        src = tmp_path / "notes.txt"
        src.write_bytes(b"attacker-chosen target")

        with pytest.raises(UnsafeUploadPathError):
            copy_upload_file_no_symlink(uploads, "notes.txt", src)

        assert outside.read_bytes() == b"original"
        assert link.is_symlink()

    def test_rejects_copying_a_file_onto_itself(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        src = uploads / "notes.txt"
        src.write_bytes(b"IMPORTANT")

        with pytest.raises(shutil.SameFileError):
            copy_upload_file_no_symlink(uploads, "notes.txt", src)

        assert src.read_bytes() == b"IMPORTANT"

    def test_rejects_a_hardlink_to_the_destination(self, tmp_path):
        """Identity, not path text: another name for the same inode is the same file."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        dest = uploads / "notes.txt"
        dest.write_bytes(b"IMPORTANT")
        src = uploads / "same-inode.txt"
        try:
            os.link(dest, src)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"hardlinks unavailable on this platform: {exc}")

        with pytest.raises(shutil.SameFileError):
            copy_upload_file_no_symlink(uploads, "notes.txt", src)

        assert dest.read_bytes() == b"IMPORTANT"

    def test_missing_source_leaves_existing_destination_untouched(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        (uploads / "notes.txt").write_bytes(b"keep me")

        with pytest.raises(FileNotFoundError):
            copy_upload_file_no_symlink(uploads, "notes.txt", tmp_path / "missing.txt")

        assert (uploads / "notes.txt").read_bytes() == b"keep me"


# ---------------------------------------------------------------------------
# list_files_in_dir
# ---------------------------------------------------------------------------


class _VanishingDirEntry:
    """DirEntry stand-in whose stat() raises, simulating a file removed mid-scan."""

    def __init__(self, real, error):
        self._real = real
        self._error = error

    @property
    def name(self):
        return self._real.name

    @property
    def path(self):
        return self._real.path

    def is_file(self, follow_symlinks=False):
        return True

    def stat(self, follow_symlinks=False):
        raise self._error


class _StaticScandir:
    """Context manager mimicking os.scandir over a fixed entry list."""

    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc_info):
        return False


class TestListFilesInDir:
    def test_empty_dir(self, tmp_path):
        result = list_files_in_dir(tmp_path)
        assert result == {"files": [], "count": 0}

    def test_nonexistent_dir(self, tmp_path):
        result = list_files_in_dir(tmp_path / "nope")
        assert result == {"files": [], "count": 0}

    @pytest.mark.parametrize("replacement", ["removed", "file"])
    def test_directory_replaced_after_is_dir_check(self, tmp_path, monkeypatch, caplog, replacement):
        directory = tmp_path / "uploads"
        directory.mkdir()
        real_scandir = os.scandir

        def replace_before_scandir(path):
            assert path == directory
            directory.rmdir()
            if replacement == "file":
                directory.write_text("replacement", encoding="utf-8")
            return real_scandir(path)

        monkeypatch.setattr(os, "scandir", replace_before_scandir)

        with caplog.at_level(logging.DEBUG, logger="deerflow.uploads.manager"):
            assert list_files_in_dir(directory) == {"files": [], "count": 0}

        assert (
            "deerflow.uploads.manager",
            logging.DEBUG,
            f"Uploads directory vanished mid-scan, keeping partial snapshot of 0 entries: {directory}",
        ) in caplog.record_tuples

    @pytest.mark.parametrize("error_code", [errno.EACCES, errno.EIO])
    def test_scandir_operational_error_still_propagates(self, tmp_path, monkeypatch, error_code):
        def fail_scandir(path):
            raise OSError(error_code, os.strerror(error_code), str(path))

        monkeypatch.setattr(os, "scandir", fail_scandir)

        with pytest.raises(OSError) as excinfo:
            list_files_in_dir(tmp_path)

        assert excinfo.value.errno == error_code

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

    @pytest.mark.parametrize("error_code", [errno.ENOENT, errno.ENOTDIR, errno.ELOOP])
    def test_skips_entries_vanishing_mid_scan(self, tmp_path, monkeypatch, caplog, error_code):
        (tmp_path / "kept.txt").write_text("kept")
        (tmp_path / "gone.txt").write_text("gone")
        with os.scandir(tmp_path) as it:
            real_entries = {e.name: e for e in it}
        vanished = _VanishingDirEntry(
            real_entries["gone.txt"],
            OSError(error_code, os.strerror(error_code), str(tmp_path / "gone.txt")),
        )
        monkeypatch.setattr(os, "scandir", lambda path: _StaticScandir([real_entries["kept.txt"], vanished]))

        with caplog.at_level(logging.DEBUG, logger="deerflow.uploads.manager"):
            result = list_files_in_dir(tmp_path)

        assert result["count"] == 1
        assert result["files"][0]["filename"] == "kept.txt"
        assert any("vanished mid-scan" in record.message and str(tmp_path / "gone.txt") in record.message for record in caplog.records)

    def test_stat_permission_error_still_propagates(self, tmp_path, monkeypatch):
        (tmp_path / "locked.txt").write_text("locked")
        with os.scandir(tmp_path) as it:
            real_entry = next(iter(it))
        locked = _VanishingDirEntry(real_entry, PermissionError(errno.EACCES, "Permission denied", str(tmp_path / "locked.txt")))
        monkeypatch.setattr(os, "scandir", lambda path: _StaticScandir([locked]))

        with pytest.raises(PermissionError):
            list_files_in_dir(tmp_path)


# ---------------------------------------------------------------------------
# cleanup_stale_upload_staging_files
# ---------------------------------------------------------------------------


def _set_age(path, age: timedelta) -> None:
    """Backdate *path*'s mtime so the cleanup sees it as *age* old."""
    timestamp = time.time() - age.total_seconds()
    os.utime(path, (timestamp, timestamp))


class TestCleanupStaleUploadStagingFiles:
    def test_removes_only_stale_staging_files_from_all_upload_layouts(self, tmp_path):
        legacy_uploads = tmp_path / "threads" / "thread-legacy" / "user-data" / "uploads"
        user_uploads = tmp_path / "users" / "owner-1" / "threads" / "thread-owned" / "user-data" / "uploads"
        unrelated_uploads = tmp_path / "misc" / "thread-other" / "user-data" / "uploads"
        for uploads_dir in (legacy_uploads, user_uploads, unrelated_uploads):
            uploads_dir.mkdir(parents=True)

        (legacy_uploads / ".upload-old.part").write_text("legacy partial")
        (user_uploads / ".upload-new.part").write_text("user partial")
        (unrelated_uploads / ".upload-ignore.part").write_text("outside layout")
        (legacy_uploads / ".env").write_text("intentional dotfile")
        (legacy_uploads / ".upload-note.txt").write_text("intentional upload")
        (legacy_uploads / "draft.part").write_text("intentional upload")
        for path in (
            legacy_uploads / ".upload-old.part",
            user_uploads / ".upload-new.part",
            unrelated_uploads / ".upload-ignore.part",
            legacy_uploads / ".env",
            legacy_uploads / ".upload-note.txt",
            legacy_uploads / "draft.part",
        ):
            _set_age(path, timedelta(days=2))

        removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 2
        assert not (legacy_uploads / ".upload-old.part").exists()
        assert not (user_uploads / ".upload-new.part").exists()
        assert (unrelated_uploads / ".upload-ignore.part").exists()
        assert (legacy_uploads / ".env").exists()
        assert (legacy_uploads / ".upload-note.txt").exists()
        assert (legacy_uploads / "draft.part").exists()

    def test_keeps_staging_files_younger_than_the_default_guard(self, tmp_path):
        """On a volume shared by several Gateway replicas, a young ``.part`` may be
        an upload another replica is still writing; only old ones are orphans."""
        uploads_dir = tmp_path / "users" / "owner-1" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads_dir.mkdir(parents=True)
        fresh = uploads_dir / ".upload-fresh.part"
        recent = uploads_dir / ".upload-recent.part"
        old = uploads_dir / ".upload-old.part"
        for path in (fresh, recent, old):
            path.write_text("partial")
        _set_age(recent, timedelta(hours=23))
        _set_age(old, timedelta(hours=25))

        removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 1
        assert fresh.exists()
        assert recent.exists()
        assert not old.exists()

    def test_min_age_is_configurable(self, tmp_path):
        uploads_dir = tmp_path / "threads" / "thread-1" / "user-data" / "uploads"
        uploads_dir.mkdir(parents=True)
        young = uploads_dir / ".upload-young.part"
        old = uploads_dir / ".upload-old.part"
        for path in (young, old):
            path.write_text("partial")
        _set_age(young, timedelta(minutes=1))
        _set_age(old, timedelta(minutes=10))

        removed = cleanup_stale_upload_staging_files(tmp_path, min_age=timedelta(minutes=5))

        assert removed == 1
        assert young.exists()
        assert not old.exists()

    def test_keeps_staging_file_when_its_age_cannot_be_read(self, tmp_path, caplog):
        uploads_dir = tmp_path / "threads" / "thread-1" / "user-data" / "uploads"
        uploads_dir.mkdir(parents=True)
        old = uploads_dir / ".upload-old.part"
        old.write_text("partial")
        _set_age(old, timedelta(days=2))

        with (
            patch("deerflow.uploads.manager._staging_entry_stat", side_effect=PermissionError(errno.EACCES, "denied")),
            caplog.at_level("WARNING", logger="deerflow.uploads.manager"),
        ):
            removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 0
        assert old.exists()
        assert any("keeping it" in record.getMessage() for record in caplog.records)

    def test_removes_published_alias_at_any_age_but_keeps_lone_young_part(self, tmp_path):
        """A crash between the commit's ``os.link`` and the staged-name removal
        leaves the final file and its ``.part`` alias sharing one inode. The
        alias is reclaimed on the next startup regardless of age, or the
        destination would fail the multi-link check on its next replacement;
        a lone young part next to it is still treated as in flight."""
        uploads_dir = tmp_path / "users" / "owner-1" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads_dir.mkdir(parents=True)
        published = uploads_dir / "notes.txt"
        published.write_bytes(b"published bytes")
        alias = uploads_dir / ".upload-abc123.part"
        try:
            os.link(published, alias)
        except OSError as exc:  # pragma: no cover - filesystems without hard links
            pytest.skip(f"hard links unsupported here: {exc}")
        in_flight = uploads_dir / ".upload-inflight.part"
        in_flight.write_bytes(b"partial")
        with pytest.raises(UnsafeUploadPathError, match="multiple links"):
            validate_upload_destination(uploads_dir, "notes.txt")

        removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 1
        assert not alias.exists()
        assert in_flight.exists()
        assert published.read_bytes() == b"published bytes"
        assert os.lstat(published).st_nlink == 1
        assert validate_upload_destination(uploads_dir, "notes.txt") == published
        replacement = tmp_path / "replacement.txt"
        replacement.write_bytes(b"replacement bytes")
        assert copy_upload_file_no_symlink(uploads_dir, "notes.txt", replacement) == published
        assert published.read_bytes() == b"replacement bytes"

    def test_skips_staging_file_that_vanished_before_its_age_was_read(self, tmp_path, caplog):
        uploads_dir = tmp_path / "threads" / "thread-1" / "user-data" / "uploads"
        uploads_dir.mkdir(parents=True)
        (uploads_dir / ".upload-gone.part").write_text("partial")

        with (
            patch("deerflow.uploads.manager._staging_entry_stat", side_effect=FileNotFoundError),
            caplog.at_level("WARNING", logger="deerflow.uploads.manager"),
        ):
            removed = cleanup_stale_upload_staging_files(tmp_path)

        assert removed == 0
        assert caplog.records == []


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

    def test_delete_keeps_the_converted_markdown(self, tmp_path):
        """Companion ownership cannot be proven from the name, so nothing is guessed at."""
        (tmp_path / "a.docx").write_bytes(b"DOCX")
        (tmp_path / "a.md").write_text("converted from the docx", encoding="utf-8")
        (tmp_path / "a.pdf").write_bytes(b"PDF")
        (tmp_path / "a_1.md").write_text("converted from the pdf", encoding="utf-8")

        result = delete_file_safe(tmp_path, "a.pdf")

        assert result["success"] is True
        assert not (tmp_path / "a.pdf").exists()
        # a.md belongs to a.docx; deleting a.pdf used to remove it.
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == "converted from the docx"
        assert (tmp_path / "a_1.md").read_text(encoding="utf-8") == "converted from the pdf"

    def test_delete_symlink_to_sibling_upload_keeps_target(self, tmp_path):
        """A symlink planted in the uploads dir must not delete the upload it aliases."""
        victim = tmp_path / "victim.pdf"
        victim.write_bytes(b"pdf-bytes")
        companion = tmp_path / "victim.md"
        companion.write_text("converted", encoding="utf-8")
        alias = tmp_path / "alias.pdf"
        try:
            alias.symlink_to(victim.name)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("symlink creation requires Developer Mode or elevated privileges on Windows")
            raise

        with pytest.raises(FileNotFoundError):
            delete_file_safe(tmp_path, "alias.pdf")

        assert victim.read_bytes() == b"pdf-bytes"
        assert companion.exists()
        assert alias.is_symlink()
