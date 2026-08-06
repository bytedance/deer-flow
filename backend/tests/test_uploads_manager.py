"""Tests for deerflow.uploads.manager — shared upload management logic."""

import errno
import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty
from typing import Any
from unittest.mock import patch

import pytest

from deerflow.uploads.layout import (
    artifact_url_for_virtual_path,
    conversion_path_for_upload,
    conversion_virtual_path,
)
from deerflow.uploads.lease import UploadNameLease
from deerflow.uploads.manager import (
    AtomicUploadPublishError,
    PathTraversalError,
    UnsafeUploadPathError,
    abort_staged_upload,
    claim_unique_filename,
    cleanup_stale_upload_staging_files,
    create_upload_staging_file,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    publish_staged_upload,
    publish_upload_bytes,
    publish_upload_bytes_leased,
    publish_upload_copy,
    rollback_published_upload,
    validate_path_traversal,
    write_upload_file_no_symlink,
)


def _delete_upload_in_process(
    uploads_dir: str,
    filename: str,
    started: Any,
    finished: Any,
    errors: Any,
) -> None:
    try:
        started.set()
        delete_file_safe(Path(uploads_dir), filename)
    except BaseException as exc:  # pragma: no cover - surfaced in the parent
        errors.put(repr(exc))
    finally:
        finished.set()


def _hold_staged_upload_in_process(
    uploads_dir: str,
    started: Any,
    release: Any,
    staged_paths: Any,
    errors: Any,
) -> None:
    staged = None
    try:
        staged = create_upload_staging_file(Path(uploads_dir))
        staged.handle.write(b"in progress")
        staged.handle.flush()
        staged_paths.put(str(staged.path))
        started.set()
        if not release.wait(5):
            raise TimeoutError("parent did not release the staged upload")
    except BaseException as exc:  # pragma: no cover - surfaced in the parent
        errors.put(repr(exc))
    finally:
        if staged is not None:
            try:
                abort_staged_upload(staged)
            except BaseException as exc:  # pragma: no cover - surfaced in the parent
                errors.put(repr(exc))


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
    def test_unrelated_names_that_shared_a_legacy_stripe_do_not_block(self, tmp_path):
        first = UploadNameLease.acquire(tmp_path, "f0.txt")
        second = None
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(UploadNameLease.acquire, tmp_path, "f15.txt")
            second = future.result(timeout=1)
        finally:
            first.release()
            if second is not None:
                second.release()
            pool.shutdown()

    def test_windows_lock_retries_until_the_holder_releases(self, monkeypatch):
        import deerflow.uploads.lease as lease_module

        attempts = 0

        class FakeMsvcrt:
            LK_NBLCK = 1

            @staticmethod
            def locking(_fd, mode, _length):
                nonlocal attempts
                assert mode == FakeMsvcrt.LK_NBLCK
                attempts += 1
                if attempts < 3:
                    raise OSError(errno.EACCES, "locked")

        class FakeLockFile:
            @staticmethod
            def fileno():
                return 7

            @staticmethod
            def seek(_offset):
                return None

        monkeypatch.setattr(lease_module, "fcntl", None)
        monkeypatch.setattr(lease_module, "msvcrt", FakeMsvcrt, raising=False)
        monkeypatch.setattr(lease_module.time, "sleep", lambda _seconds: None)

        lease_module._lock_file(FakeLockFile())

        assert attempts == 3

    def test_reserved_staging_name_is_rejected_before_stage_creation(self, tmp_path):
        with patch("deerflow.uploads.manager.create_upload_staging_file") as create_stage:
            with pytest.raises(ValueError, match="reserved"):
                publish_upload_bytes(tmp_path, ".upload-user.part", b"payload")

        create_stage.assert_not_called()

    def test_leased_publication_blocks_delete_until_release(self, tmp_path):
        publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
        started = threading.Event()
        finished = threading.Event()

        def delete():
            started.set()
            delete_file_safe(tmp_path, "report.pdf")
            finished.set()

        worker = threading.Thread(target=delete)
        worker.start()
        try:
            assert started.wait(1)
            assert not finished.wait(0.1)
        finally:
            publication.release()
            worker.join(2)

        assert finished.is_set()

    def test_leased_publication_blocks_delete_across_processes(self, tmp_path):
        publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
        context = multiprocessing.get_context("spawn")
        started = context.Event()
        finished = context.Event()
        errors = context.Queue()
        worker = context.Process(
            target=_delete_upload_in_process,
            args=(str(tmp_path), "report.pdf", started, finished, errors),
        )
        worker.start()
        try:
            assert started.wait(10)
            assert not finished.wait(0.2)
        finally:
            publication.release()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(2)

        assert worker.exitcode == 0
        try:
            child_error = errors.get_nowait()
        except Empty:
            child_error = None
        assert child_error is None
        assert finished.is_set()

    def test_lease_for_one_filename_does_not_block_another(self, tmp_path):
        publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                other = pool.submit(publish_upload_bytes, tmp_path, "notes.txt", b"new")
                assert other.result(timeout=1) == tmp_path / "notes.txt"
        finally:
            publication.release()

    def test_held_existing_name_does_not_block_next_collision_candidate(self, tmp_path):
        first = publish_upload_bytes_leased(tmp_path, "report.pdf", b"first")
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(publish_upload_bytes_leased, tmp_path, "report.pdf", b"second")
        second = None
        timed_out = False
        try:
            second = future.result(timeout=1)
        except TimeoutError:
            timed_out = True
        finally:
            first.release()
            if second is None:
                second = future.result(timeout=2)
            if second is not None:
                second.release()
            pool.shutdown()

        assert not timed_out
        assert second is not None
        assert second.path == tmp_path / "report_1.pdf"
        assert second.path.read_bytes() == b"second"

    def test_rollback_does_not_remove_reused_path(self, tmp_path):
        publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
        try:
            publication.path.unlink()
            publication.path.write_bytes(b"new")
            rollback_published_upload(publication)
        finally:
            publication.release()

        assert (tmp_path / "report.pdf").read_bytes() == b"new"

    def test_staging_unlink_failure_is_not_reported_as_success(self, tmp_path):
        staged = create_upload_staging_file(tmp_path)
        staged.handle.write(b"payload")
        real_unlink = Path.unlink

        def fail_only_for_stage(path, *args, **kwargs):
            if path == staged.path:
                raise OSError("cannot unlink stage")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", autospec=True, side_effect=fail_only_for_stage):
            with pytest.raises(AtomicUploadPublishError, match="staging"):
                publish_staged_upload(staged, "report.pdf")

        assert not (tmp_path / "report.pdf").exists()

    def test_abort_unlinks_stage_when_close_raises(self, tmp_path):
        staged = create_upload_staging_file(tmp_path)

        class CloseFailingHandle:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            @property
            def closed(self):
                return self._wrapped.closed

            def close(self):
                self._wrapped.close()
                raise OSError("close failed")

        staged.handle = CloseFailingHandle(staged.handle)
        with pytest.raises(OSError, match="close failed"):
            abort_staged_upload(staged)

        assert not staged.path.exists()

    def test_abort_releases_stage_lease_when_unlink_raises(self, tmp_path):
        staged = create_upload_staging_file(tmp_path)

        with patch.object(Path, "unlink", autospec=True, side_effect=OSError("unlink failed")):
            with pytest.raises(OSError, match="unlink failed"):
                abort_staged_upload(staged)

        assert not staged.lease.is_active
        staged.path.unlink()

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
    def test_skips_stage_held_by_another_process(self, tmp_path):
        uploads = tmp_path / "threads" / "thread-live" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        context = multiprocessing.get_context("spawn")
        started = context.Event()
        release = context.Event()
        staged_paths = context.Queue()
        errors = context.Queue()
        worker = context.Process(
            target=_hold_staged_upload_in_process,
            args=(str(uploads), started, release, staged_paths, errors),
        )
        worker.start()
        try:
            assert started.wait(5)
            staged_path = Path(staged_paths.get(timeout=1))

            assert cleanup_stale_upload_staging_files(tmp_path) == 0
            assert staged_path.exists()
        finally:
            release.set()
            worker.join(timeout=5)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)

        assert worker.exitcode == 0
        with pytest.raises(Empty):
            errors.get_nowait()

    def test_skips_live_stage_and_removes_it_after_lease_is_abandoned(self, tmp_path):
        uploads = tmp_path / "threads" / "thread-live" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        staged = create_upload_staging_file(uploads)
        staged.handle.write(b"in progress")

        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        assert staged.path.exists()

        staged.handle.close()
        staged.lease.release()
        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert not staged.path.exists()

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

    def test_delete_from_nonexistent_directory_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="ghost.txt"):
            delete_file_safe(tmp_path / "missing-uploads", "ghost.txt")

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
