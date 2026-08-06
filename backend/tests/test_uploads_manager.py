"""Tests for deerflow.uploads.manager — shared upload management logic."""

import asyncio
import errno
import multiprocessing
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty
from typing import Any
from unittest.mock import patch

import pytest

from deerflow.uploads.async_helpers import release_published_upload_async
from deerflow.uploads.layout import (
    artifact_url_for_virtual_path,
    conversion_dir_for_uploads,
    conversion_path_for_upload,
    conversion_virtual_path,
)
from deerflow.uploads.lease import UploadIdentity, UploadNameLease
from deerflow.uploads.manager import (
    AtomicUploadPublishError,
    PathTraversalError,
    RemoteDeletionCompensatedError,
    UnsafeUploadPathError,
    abort_staged_upload,
    claim_unique_filename,
    cleanup_stale_upload_staging_files,
    create_upload_staging_file,
    delete_file_safe,
    list_files_in_dir,
    normalize_filename,
    publish_staged_upload,
    publish_staged_upload_leased,
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


def _try_upload_lease_in_process(uploads_dir: str, filename: str, outcomes: Any) -> None:
    try:
        lease = UploadNameLease.try_acquire(Path(uploads_dir), filename)
        outcomes.put(lease is not None)
        if lease is not None:
            lease.release()
    except BaseException as exc:  # pragma: no cover - surfaced in the parent
        outcomes.put(repr(exc))


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

    @pytest.mark.parametrize(
        "filename",
        [
            "paper<system>.pdf",
            "report--- BEGIN USER INPUT ---draft.pdf",
            "report--- END USER INPUT ---draft.pdf",
        ],
    )
    def test_rejects_names_that_cannot_be_exposed_losslessly_to_the_agent(self, filename):
        with pytest.raises(ValueError, match="reserved model-context token"):
            normalize_filename(filename)

    def test_rejects_nul_before_any_filesystem_operation(self):
        with pytest.raises(ValueError, match="NUL"):
            normalize_filename("bad\0name.pdf")

    @pytest.mark.parametrize(
        "filename",
        [
            "report.pdf.",
            "report.pdf ",
            "CON",
            "nul.txt",
            "report:stream.pdf",
            "report?.pdf",
        ],
    )
    def test_rejects_windows_reserved_filenames(self, filename):
        with pytest.raises(ValueError, match="Windows"):
            normalize_filename(filename)


@pytest.mark.parametrize(
    ("first_name", "alias_name"),
    [
        ("Report.pdf", "report.pdf"),
        ("caf\u00e9.pdf", "cafe\u0301.pdf"),
    ],
)
def test_portable_filesystem_aliases_share_one_generation_lease(tmp_path, first_name, alias_name):
    first = UploadNameLease.acquire(tmp_path, first_name)
    alias_acquired = threading.Event()

    def acquire_alias():
        lease = UploadNameLease.acquire(tmp_path, alias_name)
        alias_acquired.set()
        return lease

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(acquire_alias)
        try:
            assert not alias_acquired.wait(0.1)
        finally:
            first.release()
        alias = future.result(timeout=5)
        alias.release()


def test_nonblocking_lease_treats_busy_windows_alias_as_collision(tmp_path):
    first = UploadNameLease.acquire(tmp_path, "report.pdf")
    try:
        assert UploadNameLease.try_acquire(tmp_path, "REPORT.PDF. ") is None
    finally:
        first.release()


def test_nonblocking_lease_observes_busy_portable_alias_across_processes(tmp_path):
    first = UploadNameLease.acquire(tmp_path, "Report.pdf")
    context = multiprocessing.get_context("spawn")
    outcomes = context.Queue()
    worker = context.Process(
        target=_try_upload_lease_in_process,
        args=(str(tmp_path), "report.pdf", outcomes),
    )
    worker.start()
    try:
        outcome = outcomes.get(timeout=5)
        worker.join(5)
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        first.release()

    assert worker.exitcode == 0
    assert outcome is False


@pytest.mark.parametrize(
    ("first_name", "alias_name", "expected_alias_name"),
    [
        ("Report.pdf", "report.pdf", "report_1.pdf"),
        ("caf\u00e9.pdf", "cafe\u0301.pdf", "cafe\u0301_1.pdf"),
    ],
)
def test_batch_portable_alias_reservation_chooses_distinct_name(
    tmp_path,
    first_name,
    alias_name,
    expected_alias_name,
):
    reserved_keys: set[str] = set()
    publications = []
    try:
        for filename, payload in [(first_name, b"first"), (alias_name, b"second")]:
            staged = create_upload_staging_file(tmp_path)
            staged.handle.write(payload)
            publications.append(
                publish_staged_upload_leased(
                    staged,
                    filename,
                    reserved_coordination_keys=reserved_keys,
                )
            )
    finally:
        for publication in reversed(publications):
            publication.release()

    assert [publication.path.name for publication in publications] == [first_name, expected_alias_name]
    assert {publication.path.read_bytes() for publication in publications} == {b"first", b"second"}


@pytest.mark.asyncio
async def test_release_commit_delays_and_swallows_new_cancellation(tmp_path, monkeypatch):
    publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"payload")
    release_started = threading.Event()
    allow_release = threading.Event()
    real_release = UploadNameLease.release

    def paused_release(lease):
        release_started.set()
        assert allow_release.wait(5)
        real_release(lease)

    monkeypatch.setattr(UploadNameLease, "release", paused_release)
    task = asyncio.create_task(release_published_upload_async(publication))
    assert await asyncio.to_thread(release_started.wait, 5)
    try:
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
    finally:
        allow_release.set()

    await task
    assert not publication.is_active


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

    def test_unrelated_publication_survives_pending_deletion_finalization(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        journal = upload_manager_module._staged_deletion_remote_journal(staged_path)
        journal.write_text("{}", encoding="utf-8")
        transaction_dir = staged_path.parent.parent
        primary_dir = staged_path.parent
        stage_lease.release()

        reached_primary_scan = threading.Event()
        resume_primary_scan = threading.Event()
        real_scandir = upload_manager_module.os.scandir
        paused = False
        pause_lock = threading.Lock()

        def pause_first_primary_scan(path):
            nonlocal paused
            should_pause = False
            with pause_lock:
                if Path(path) == primary_dir and not paused:
                    paused = True
                    should_pause = True
            if should_pause:
                reached_primary_scan.set()
                assert resume_primary_scan.wait(2)
            return real_scandir(path)

        with patch.object(upload_manager_module.os, "scandir", side_effect=pause_first_primary_scan):
            with ThreadPoolExecutor(max_workers=1) as pool:
                publication = pool.submit(publish_upload_bytes, uploads, "notes.txt", b"new")
                assert reached_primary_scan.wait(2)
                journal.unlink()
                assert cleanup_stale_upload_staging_files(tmp_path) == 1
                assert not transaction_dir.exists()
                resume_primary_scan.set()
                assert publication.result(timeout=2) == uploads / "notes.txt"

        assert (uploads / "notes.txt").read_bytes() == b"new"

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

    def test_rollback_does_not_unlink_replacement_after_identity_check(self, tmp_path):
        publication = publish_upload_bytes_leased(tmp_path, "report.pdf", b"old")
        real_matches = UploadIdentity.matches
        replaced = False

        def replace_after_match(identity, path):
            nonlocal replaced
            matches = real_matches(identity, path)
            if matches and path == publication.path and not replaced:
                replaced = True
                path.unlink()
                path.write_bytes(b"new")
            return matches

        try:
            with patch.object(UploadIdentity, "matches", autospec=True, side_effect=replace_after_match):
                rollback_published_upload(publication)
        finally:
            publication.release()

        assert publication.path.read_bytes() == b"new"

    def test_rollback_preserves_primary_when_conversion_removal_fails(self, tmp_path):
        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        publication = publish_upload_bytes_leased(uploads, "report.pdf", b"old")
        owned_conversion = conversion_path_for_upload(publication.path)
        owned_conversion.parent.mkdir(exist_ok=True)
        owned_conversion.write_text("generated", encoding="utf-8")
        real_unlink = Path.unlink

        def fail_conversion_unlink(path, *args, **kwargs):
            if path.name == ".conversion" and path.parent.name.startswith(".upload-delete-"):
                raise OSError("cannot unlink conversion")
            return real_unlink(path, *args, **kwargs)

        try:
            with patch.object(Path, "unlink", autospec=True, side_effect=fail_conversion_unlink):
                with pytest.raises(OSError, match="cannot unlink conversion"):
                    rollback_published_upload(publication)
        finally:
            publication.release()

        assert publication.path.read_bytes() == b"old"
        assert owned_conversion.read_text(encoding="utf-8") == "generated"
        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert publication.path.read_bytes() == b"old"
        assert owned_conversion.read_text(encoding="utf-8") == "generated"
        assert not list(owned_conversion.parent.glob(".upload-delete-*.part"))

    def test_successful_rollback_removes_deletion_transaction_directory(self, tmp_path):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        publication = publish_upload_bytes_leased(uploads, "report.pdf", b"old")
        conversion_dir = conversion_path_for_upload(publication.path).parent
        try:
            rollback_published_upload(publication)
        finally:
            publication.release()

        assert not publication.path.exists()
        assert not list(conversion_dir.glob(".upload-delete-*.part"))

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

    @pytest.mark.parametrize("filename", ["a." + "x" * 253, "é." + "x" * 251])
    def test_max_length_filename_with_long_suffix_still_gets_collision_candidate(self, tmp_path, filename):
        first = publish_upload_bytes(tmp_path, filename, b"first")
        second = publish_upload_bytes(tmp_path, filename, b"second")

        assert first.name == filename
        assert second.name.endswith("_1")
        assert len(second.name.encode("utf-8")) <= 255
        assert first.read_bytes() == b"first"
        assert second.read_bytes() == b"second"

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

    def test_restores_primary_left_in_deletion_transaction_after_crash(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"original")
        identity = UploadIdentity.from_path(primary)

        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
        )
        stage_lease.release()

        assert not primary.exists()
        assert staged_path.read_bytes() == b"original"
        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"original"
        assert not staged_path.exists()

    def test_finishes_recovery_that_crashed_after_publishing_visible_link(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"original")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
        )
        os.link(staged_path, primary)
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"original"
        assert not staged_path.exists()

    @pytest.mark.parametrize(
        "filename",
        [
            "report.pdf",
            "primary",
            ".remote-delete.json",
            ".remote-delete.finalizing",
            ".commit",
            ".restore",
            ".conversion",
        ],
    )
    def test_restores_legacy_intentless_deletion_transaction(self, tmp_path, filename):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / filename
        primary.write_bytes(b"original")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
        )
        stage_lease.release()
        transaction_dir = staged_path.parent.parent
        legacy_transaction_dir = transaction_dir.with_name(
            transaction_dir.name.replace(
                ".upload-delete-restore-",
                ".upload-delete-",
                1,
            )
        )
        current_primary_dir = staged_path.parent
        temporary_primary_dir = transaction_dir / ".current-primary"
        current_primary_dir.rename(temporary_primary_dir)
        legacy_staged_path = transaction_dir / staged_path.name
        (temporary_primary_dir / staged_path.name).rename(legacy_staged_path)
        temporary_primary_dir.rmdir()
        transaction_dir.rename(legacy_transaction_dir)
        legacy_staged_path = legacy_transaction_dir / staged_path.name

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"original"
        assert not legacy_staged_path.exists()

    def test_refuses_replaced_deletion_tombstone_after_crash(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"original")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
        )
        replacement = tmp_path / "replacement.bin"
        replacement.write_bytes(b"replacement")
        staged_path.unlink()
        replacement.rename(staged_path)
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        assert not primary.exists()
        assert staged_path.read_bytes() == b"replacement"

    def test_crashed_upload_rollback_finishes_deletion_instead_of_restoring(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "failed.pdf"
        primary.write_bytes(b"never committed")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=False,
        )
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert not primary.exists()
        assert not staged_path.exists()

    def test_crashed_discard_removes_a_republished_visible_link(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "failed.pdf"
        primary.write_bytes(b"never committed")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=False,
        )
        os.link(staged_path, primary)
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert not primary.exists()
        assert not staged_path.exists()

    def test_crashed_committed_delete_removes_primary_and_conversion(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"delete me")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir(parents=True, exist_ok=True)
        conversion.write_text("generated", encoding="utf-8")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=False,
        )
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert not primary.exists()
        assert not conversion.exists()
        assert not staged_path.exists()

    def test_crashed_committed_delete_does_not_rebind_old_conversion_to_replacement(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old generation")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("old conversion", encoding="utf-8")
        old_identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            old_identity,
            recover_on_crash=False,
            conversion_path=conversion,
        )
        primary.write_bytes(b"replacement generation")
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"replacement generation"
        assert not conversion.exists()
        assert not staged_path.exists()

    def test_crash_before_remote_delete_restores_primary_and_conversion(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("conversion", encoding="utf-8")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
            conversion_path=conversion,
        )
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"primary"
        assert conversion.read_text(encoding="utf-8") == "conversion"
        assert not staged_path.exists()

    @pytest.mark.parametrize(
        "filename",
        [
            ".commit",
            ".restore",
            ".conversion",
            ".remote-delete.json",
            ".remote-delete.finalizing",
            "primary",
        ],
    )
    def test_crash_recovery_restores_control_named_primary_and_conversion(self, tmp_path, filename):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / filename
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("conversion", encoding="utf-8")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
            conversion_path=conversion,
        )
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"primary"
        assert conversion.read_text(encoding="utf-8") == "conversion"
        assert not staged_path.exists()

    def test_crash_after_remote_delete_commits_primary_and_conversion(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("conversion", encoding="utf-8")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
            conversion_path=conversion,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert not primary.exists()
        assert not conversion.exists()
        assert not staged_path.exists()

    def test_committed_finalize_guard_confirms_journal_absence_before_cleanup(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        transaction_dir = staged_path.parent.parent
        finalize_guard = transaction_dir / upload_manager_module._UPLOAD_DELETION_FINALIZE_GUARD
        finalize_guard.write_text("{}", encoding="utf-8")
        stage_lease.release()

        confirmed_before_guard_unlink = False
        real_fsync = upload_manager_module.os.fsync
        transaction_identity = os.stat(transaction_dir)

        def observe_fsync(descriptor):
            nonlocal confirmed_before_guard_unlink
            descriptor_stat = os.fstat(descriptor)
            if (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
                transaction_identity.st_dev,
                transaction_identity.st_ino,
            ) and finalize_guard.exists():
                confirmed_before_guard_unlink = True
            return real_fsync(descriptor)

        with patch.object(upload_manager_module.os, "fsync", side_effect=observe_fsync):
            assert cleanup_stale_upload_staging_files(tmp_path) == 1

        assert confirmed_before_guard_unlink
        assert not transaction_dir.exists()
        assert not primary.exists()

    def test_committed_journal_and_finalize_guard_remain_pending(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        transaction_dir = staged_path.parent.parent
        journal = transaction_dir / upload_manager_module._UPLOAD_DELETION_REMOTE_JOURNAL
        finalize_guard = transaction_dir / upload_manager_module._UPLOAD_DELETION_FINALIZE_GUARD
        journal.write_text("{}", encoding="utf-8")
        finalize_guard.write_text("{}", encoding="utf-8")
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        assert journal.is_file()
        assert finalize_guard.is_file()
        assert staged_path.read_bytes() == b"primary"

    def test_uncommitted_journal_and_finalize_guard_restore_host(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        transaction_dir = staged_path.parent.parent
        journal = transaction_dir / upload_manager_module._UPLOAD_DELETION_REMOTE_JOURNAL
        finalize_guard = transaction_dir / upload_manager_module._UPLOAD_DELETION_FINALIZE_GUARD
        journal.write_text("{}", encoding="utf-8")
        finalize_guard.write_text("{}", encoding="utf-8")
        stage_lease.release()

        assert cleanup_stale_upload_staging_files(tmp_path) == 1
        assert primary.read_bytes() == b"primary"
        assert not transaction_dir.exists()


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

    @pytest.mark.skipif(os.name == "nt", reason="POSIX legacy filenames are not representable on Windows")
    @pytest.mark.parametrize("filename", ["CON", "report?.pdf", "trailing ", r"report\draft.pdf", "...", " "])
    def test_delete_accepts_listed_legacy_posix_filename(self, tmp_path, filename):
        legacy = tmp_path / filename
        legacy.write_bytes(b"legacy")

        assert filename in {entry["filename"] for entry in list_files_in_dir(tmp_path)["files"]}
        result = delete_file_safe(tmp_path, filename)

        assert result == {"success": True, "message": f"Deleted {filename}"}
        assert not legacy.exists()

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

    def test_delete_rejects_hardlink_race_without_unlinking_any_alias(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        primary = tmp_path / "zzz.txt"
        primary.write_bytes(b"payload")
        alias = tmp_path / "aaa.txt"
        real_find = upload_manager_module._find_upload_path_by_identity

        def add_alias_before_scan(base_dir, identity):
            os.link(primary, alias)
            return real_find(base_dir, identity)

        with patch.object(upload_manager_module, "_find_upload_path_by_identity", side_effect=add_alias_before_scan):
            with pytest.raises(UnsafeUploadPathError, match="exclusive"):
                delete_file_safe(tmp_path, primary.name)

        assert primary.read_bytes() == b"payload"
        assert alias.read_bytes() == b"payload"

    def test_delete_hardlink_after_identity_scan_preserves_conversion(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"payload")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("generated", encoding="utf-8")
        alias = uploads / "alias.pdf"
        real_find = upload_manager_module._find_upload_path_by_identity

        def add_alias_after_scan(base_dir, identity):
            found = real_find(base_dir, identity)
            os.link(found, alias)
            return found

        with patch.object(
            upload_manager_module,
            "_find_upload_path_by_identity",
            side_effect=add_alias_after_scan,
        ):
            with pytest.raises(UnsafeUploadPathError, match="exclusive"):
                delete_file_safe(uploads, primary.name)

        assert primary.read_bytes() == b"payload"
        assert alias.read_bytes() == b"payload"
        assert conversion.read_text(encoding="utf-8") == "generated"

    def test_delete_rejects_identity_renamed_outside_requested_name_lease(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("old conversion", encoding="utf-8")
        renamed = uploads / "other.pdf"
        renamed_conversion = conversion_path_for_upload(renamed)
        real_find = upload_manager_module._find_upload_path_by_identity
        remote_names: list[str] = []

        def rename_after_scan(base_dir, identity):
            found = real_find(base_dir, identity)
            found.rename(renamed)
            conversion.rename(renamed_conversion)
            return renamed

        def publish_replacement(actual_name, _primary_path, _conversion_path):
            remote_names.append(actual_name)
            publish_upload_bytes(uploads, actual_name, b"new")
            renamed_conversion.unlink()
            renamed_conversion.write_text("new conversion", encoding="utf-8")

        with patch.object(
            upload_manager_module,
            "_find_upload_path_by_identity",
            side_effect=rename_after_scan,
        ):
            with pytest.raises(UnsafeUploadPathError, match="name changed"):
                delete_file_safe(
                    uploads,
                    primary.name,
                    delete_remote_copy=publish_replacement,
                )

        assert remote_names == []
        assert renamed.read_bytes() == b"old"
        assert renamed_conversion.read_text(encoding="utf-8") == "old conversion"

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

    def test_delete_preserves_primary_when_conversion_removal_fails(self, tmp_path):
        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"PDF")
        owned_conversion = conversion_path_for_upload(primary)
        owned_conversion.parent.mkdir()
        owned_conversion.write_text("generated", encoding="utf-8")
        real_unlink = Path.unlink

        def fail_conversion_unlink(path, *args, **kwargs):
            if path.name == ".conversion" and path.parent.name.startswith(".upload-delete-"):
                raise OSError("cannot unlink conversion")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", autospec=True, side_effect=fail_conversion_unlink):
            with pytest.raises(OSError, match="cannot unlink conversion"):
                delete_file_safe(uploads, "report.pdf")

        assert primary.read_bytes() == b"PDF"
        assert owned_conversion.read_text(encoding="utf-8") == "generated"

    @pytest.mark.parametrize(
        "filename",
        [
            ".commit",
            ".restore",
            ".conversion",
            ".remote-delete.json",
            ".remote-delete.finalizing",
            "primary",
        ],
    )
    def test_failed_remote_delete_restores_control_named_primary_and_conversion(self, tmp_path, filename):
        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / filename
        primary.write_bytes(b"primary")
        owned_conversion = conversion_path_for_upload(primary)
        owned_conversion.parent.mkdir()
        owned_conversion.write_text("generated", encoding="utf-8")

        with pytest.raises(RemoteDeletionCompensatedError, match="remote unavailable"):
            delete_file_safe(
                uploads,
                filename,
                delete_remote_copy=lambda _name, _primary, _conversion: (_ for _ in ()).throw(RemoteDeletionCompensatedError("remote unavailable")),
            )

        assert primary.read_bytes() == b"primary"
        assert owned_conversion.read_text(encoding="utf-8") == "generated"
        assert not list(owned_conversion.parent.glob(".upload-delete-*.part"))

    def test_remote_delete_phase_is_persisted_before_the_hook_runs(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        observed_marker = False

        def observe_phase_then_fail(_name, staged_primary, _conversion):
            nonlocal observed_marker
            observed_marker = upload_manager_module._staged_deletion_commit_marker(staged_primary).is_file()
            raise RemoteDeletionCompensatedError("remote unavailable")

        with pytest.raises(RemoteDeletionCompensatedError, match="remote unavailable"):
            delete_file_safe(
                uploads,
                primary.name,
                delete_remote_copy=observe_phase_then_fail,
            )

        assert observed_marker
        assert primary.read_bytes() == b"primary"

    @pytest.mark.parametrize(
        ("marker_function_name", "recover_on_crash"),
        [
            ("_mark_staged_deletion_committed", True),
            ("_mark_staged_deletion_restore", False),
        ],
        ids=["commit", "restore"],
    )
    def test_existing_phase_marker_resyncs_parent_before_reuse(
        self,
        tmp_path,
        marker_function_name,
        recover_on_crash,
    ):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=recover_on_crash,
        )
        transaction_dir = staged_path.parent.parent
        marker_function = getattr(upload_manager_module, marker_function_name)
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        failed = False

        def fail_marker_parent_once(directory):
            nonlocal failed
            if Path(directory) == transaction_dir and not failed:
                failed = True
                raise OSError("cannot persist phase marker parent")
            return real_fsync_directory(directory)

        try:
            with patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=fail_marker_parent_once,
            ):
                with pytest.raises(OSError, match="cannot persist phase marker parent"):
                    marker_function(staged_path)

            fsynced_directories: list[Path] = []

            def observe_fsync_directory(directory):
                fsynced_directories.append(Path(directory))
                return real_fsync_directory(directory)

            with patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ):
                marker_function(staged_path)
        finally:
            stage_lease.release()

        assert transaction_dir in fsynced_directories

    @pytest.mark.parametrize(
        ("marker_function_name", "marker_path_function_name", "recover_on_crash"),
        [
            (
                "_mark_staged_deletion_committed",
                "_staged_deletion_commit_marker",
                True,
            ),
            (
                "_mark_staged_deletion_restore",
                "_staged_deletion_restore_marker",
                False,
            ),
        ],
        ids=["commit", "restore"],
    )
    def test_existing_phase_marker_resyncs_file_before_parent_after_file_fsync_failure(
        self,
        tmp_path,
        marker_function_name,
        marker_path_function_name,
        recover_on_crash,
    ):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=recover_on_crash,
        )
        transaction_dir = staged_path.parent.parent
        marker_function = getattr(upload_manager_module, marker_function_name)
        marker_path = getattr(upload_manager_module, marker_path_function_name)(staged_path)
        real_fsync = upload_manager_module.os.fsync
        failed = False

        def fail_marker_file_once(descriptor):
            nonlocal failed
            descriptor_stat = os.fstat(descriptor)
            if stat.S_ISREG(descriptor_stat.st_mode) and not failed:
                failed = True
                raise OSError("cannot persist phase marker file")
            return real_fsync(descriptor)

        try:
            with patch.object(
                upload_manager_module.os,
                "fsync",
                side_effect=fail_marker_file_once,
            ):
                with pytest.raises(OSError, match="cannot persist phase marker file"):
                    marker_function(staged_path)

            marker_stat = os.lstat(marker_path)
            transaction_stat = os.lstat(transaction_dir)
            marker_identity = (marker_stat.st_dev, marker_stat.st_ino)
            transaction_identity = (transaction_stat.st_dev, transaction_stat.st_ino)
            events: list[str] = []

            def observe_fsync(descriptor):
                descriptor_stat = os.fstat(descriptor)
                descriptor_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
                if stat.S_ISREG(descriptor_stat.st_mode) and descriptor_identity == marker_identity:
                    events.append("file")
                elif stat.S_ISDIR(descriptor_stat.st_mode) and descriptor_identity == transaction_identity:
                    events.append("directory")
                return real_fsync(descriptor)

            with patch.object(
                upload_manager_module.os,
                "fsync",
                side_effect=observe_fsync,
            ):
                marker_function(staged_path)
        finally:
            stage_lease.release()

        marker_file_sync = events.index("file")
        marker_directory_sync = events.index("directory", marker_file_sync)
        assert marker_file_sync < marker_directory_sync

    def test_existing_phase_marker_refuses_inode_swap_before_file_fsync(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        marker_path = upload_manager_module._staged_deletion_commit_marker(staged_path)
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        original_marker_stat = os.lstat(marker_path)
        real_open = upload_manager_module.os.open
        replaced = False

        def replace_marker_before_open(path, flags, *args):
            nonlocal replaced
            if Path(path) == marker_path and not (flags & os.O_CREAT) and not replaced:
                replaced = True
                marker_path.unlink()
                marker_path.write_bytes(b"replacement")
            return real_open(path, flags, *args)

        try:
            with patch.object(
                upload_manager_module.os,
                "open",
                side_effect=replace_marker_before_open,
            ):
                with pytest.raises(UnsafeUploadPathError, match="commit marker"):
                    upload_manager_module._mark_staged_deletion_committed(staged_path)
        finally:
            stage_lease.release()

        replacement_stat = os.lstat(marker_path)
        assert replaced
        assert (replacement_stat.st_dev, replacement_stat.st_ino) != (
            original_marker_stat.st_dev,
            original_marker_stat.st_ino,
        )

    def test_staged_renames_are_durable_before_remote_mutation(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("generated", encoding="utf-8")
        real_rename = upload_manager_module.os.rename
        real_fsync = upload_manager_module.os.fsync
        directory_labels = {
            (os.stat(uploads).st_dev, os.stat(uploads).st_ino): "uploads",
            (os.stat(conversion.parent).st_dev, os.stat(conversion.parent).st_ino): "conversions",
        }
        events: list[tuple[str, str]] = []
        events_before_remote: list[tuple[str, str]] = []

        def observe_rename(source, destination):
            real_rename(source, destination)
            destination = Path(destination)
            destination_parent_stat = os.stat(destination.parent)
            label = "primary" if destination.parent.name == "primary" else "transaction"
            directory_labels[(destination_parent_stat.st_dev, destination_parent_stat.st_ino)] = label
            events.append(("rename", label))

        def observe_fsync(descriptor):
            descriptor_stat = os.fstat(descriptor)
            if stat.S_ISDIR(descriptor_stat.st_mode):
                label = directory_labels.get((descriptor_stat.st_dev, descriptor_stat.st_ino))
                if label is not None:
                    events.append(("fsync", label))
            return real_fsync(descriptor)

        def observe_remote_mutation(_name, _primary, _conversion):
            events_before_remote.extend(events)

        with (
            patch.object(upload_manager_module.os, "rename", side_effect=observe_rename),
            patch.object(upload_manager_module.os, "fsync", side_effect=observe_fsync),
        ):
            delete_file_safe(
                uploads,
                primary.name,
                delete_remote_copy=observe_remote_mutation,
            )

        primary_rename = events_before_remote.index(("rename", "primary"))
        conversion_rename = events_before_remote.index(("rename", "transaction"))
        primary_destination_sync = events_before_remote.index(("fsync", "primary"), primary_rename)
        primary_source_sync = events_before_remote.index(("fsync", "uploads"), primary_destination_sync)
        conversion_destination_sync = events_before_remote.index(("fsync", "transaction"), conversion_rename)
        conversion_source_sync = events_before_remote.index(("fsync", "conversions"), conversion_destination_sync)
        assert primary_destination_sync < primary_source_sync < conversion_rename
        assert conversion_destination_sync < conversion_source_sync

    def test_staging_root_is_durable_before_primary_source_removal(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        user_data = tmp_path / "user-data"
        uploads = user_data / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        assert not conversion_dir_for_uploads(uploads).exists()
        events: list[tuple[str, str]] = []
        real_rename = upload_manager_module.os.rename
        real_fsync_directory = upload_manager_module._fsync_directory_durably

        def observe_rename(source, destination):
            if Path(source) == primary:
                events.append(("rename", "primary-source"))
            return real_rename(source, destination)

        def observe_fsync_directory(directory):
            if Path(directory) == user_data:
                events.append(("fsync", "user-data"))
            return real_fsync_directory(directory)

        with (
            patch.object(upload_manager_module.os, "rename", side_effect=observe_rename),
            patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ),
        ):
            delete_file_safe(
                uploads,
                primary.name,
                delete_remote_copy=lambda *_args: None,
            )

        staging_root_sync = events.index(("fsync", "user-data"))
        primary_rename = events.index(("rename", "primary-source"), staging_root_sync)
        assert staging_root_sync < primary_rename

    def test_staging_directory_fsync_failure_restores_host_before_remote_mutation(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("generated", encoding="utf-8")
        remote_calls: list[str] = []
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        failed = False

        def fail_primary_destination_once(directory):
            nonlocal failed
            if directory.name == "primary" and not failed:
                failed = True
                raise OSError("cannot persist primary tombstone")
            return real_fsync_directory(directory)

        with patch.object(
            upload_manager_module,
            "_fsync_directory_durably",
            side_effect=fail_primary_destination_once,
        ):
            with pytest.raises(OSError, match="cannot persist primary tombstone"):
                delete_file_safe(
                    uploads,
                    primary.name,
                    delete_remote_copy=lambda name, _primary, _conversion: remote_calls.append(name),
                )

        assert remote_calls == []
        assert primary.read_bytes() == b"primary"
        assert conversion.read_text(encoding="utf-8") == "generated"
        assert not list(conversion.parent.glob(".upload-delete-*.part"))

    def test_unexpected_inode_restore_recovers_after_visible_peer_fsync_failure(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        stale_identity = UploadIdentity.from_path(primary)
        primary.unlink()
        primary.write_bytes(b"replacement")
        assert not stale_identity.matches(primary)
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        failed = False

        def fail_visible_peer_once(directory):
            nonlocal failed
            if Path(directory) == uploads and not failed:
                failed = True
                raise OSError("cannot persist visible replacement")
            return real_fsync_directory(directory)

        with patch.object(
            upload_manager_module,
            "_fsync_directory_durably",
            side_effect=fail_visible_peer_once,
        ):
            with pytest.raises(OSError, match="cannot persist visible replacement"):
                upload_manager_module._stage_primary_deletion(
                    uploads,
                    primary,
                    stale_identity,
                    recover_on_crash=False,
                )

        assert primary.read_bytes() == b"replacement"
        assert os.lstat(primary).st_nlink == 1
        assert not list(conversion_dir_for_uploads(uploads).glob(".upload-delete-*.part"))

    def test_unexpected_inode_hardlink_replacement_restores_exact_name_after_fsync_failure(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        stale_identity = UploadIdentity.from_path(primary)
        primary.unlink()
        peer = uploads / "other.bin"
        peer.write_bytes(b"replacement")
        os.link(peer, primary)
        assert not stale_identity.matches(primary)
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        failed = False

        def fail_visible_peer_once(directory):
            nonlocal failed
            if Path(directory) == uploads and not failed:
                failed = True
                raise OSError("cannot persist visible hardlink replacement")
            return real_fsync_directory(directory)

        with patch.object(
            upload_manager_module,
            "_fsync_directory_durably",
            side_effect=fail_visible_peer_once,
        ):
            with pytest.raises(OSError, match="cannot persist visible hardlink replacement"):
                upload_manager_module._stage_primary_deletion(
                    uploads,
                    primary,
                    stale_identity,
                    recover_on_crash=False,
                )

        assert primary.read_bytes() == b"replacement"
        assert peer.read_bytes() == b"replacement"
        assert (os.lstat(primary).st_dev, os.lstat(primary).st_ino) == (
            os.lstat(peer).st_dev,
            os.lstat(peer).st_ino,
        )
        assert os.lstat(primary).st_nlink == 2
        assert not list(conversion_dir_for_uploads(uploads).glob(".upload-delete-*.part"))

    def test_startup_cleans_verified_visible_peer_for_unexpected_inode_transaction(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        stale_identity = UploadIdentity.from_path(primary)
        primary.unlink()
        peer = uploads / "other.bin"
        peer.write_bytes(b"replacement")
        os.link(peer, primary)
        assert not stale_identity.matches(primary)

        with patch.object(
            upload_manager_module,
            "_restore_unexpected_staged_entry",
            side_effect=OSError("simulate crash before live recovery"),
        ):
            with pytest.raises(OSError, match="simulate crash before live recovery"):
                upload_manager_module._stage_primary_deletion(
                    uploads,
                    primary,
                    stale_identity,
                    recover_on_crash=False,
                )

        transactions = list(conversion_dir_for_uploads(uploads).glob(".upload-delete-*.part"))
        assert len(transactions) == 1
        transaction_dir = transactions[0]
        staged_path = transaction_dir / upload_manager_module._UPLOAD_DELETION_PRIMARY_DIRNAME / primary.name
        assert staged_path.read_bytes() == b"replacement"
        os.link(staged_path, primary)

        assert upload_manager_module._recover_stale_deletion_transaction(transaction_dir)
        assert primary.read_bytes() == b"replacement"
        assert peer.read_bytes() == b"replacement"
        assert os.lstat(primary).st_nlink == 2
        assert not transaction_dir.exists()

    def test_startup_refuses_unrelated_peer_for_unexpected_inode_transaction(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old")
        stale_identity = UploadIdentity.from_path(primary)
        primary.unlink()
        peer = uploads / "other.bin"
        peer.write_bytes(b"replacement")
        os.link(peer, primary)
        assert not stale_identity.matches(primary)

        with patch.object(
            upload_manager_module,
            "_restore_unexpected_staged_entry",
            side_effect=OSError("simulate crash before live recovery"),
        ):
            with pytest.raises(OSError, match="simulate crash before live recovery"):
                upload_manager_module._stage_primary_deletion(
                    uploads,
                    primary,
                    stale_identity,
                    recover_on_crash=False,
                )

        transactions = list(conversion_dir_for_uploads(uploads).glob(".upload-delete-*.part"))
        assert len(transactions) == 1
        transaction_dir = transactions[0]
        staged_path = transaction_dir / upload_manager_module._UPLOAD_DELETION_PRIMARY_DIRNAME / primary.name
        assert not upload_manager_module._recover_stale_deletion_transaction(transaction_dir)
        assert not primary.exists()
        assert peer.read_bytes() == b"replacement"
        assert staged_path.read_bytes() == b"replacement"
        assert (os.lstat(peer).st_dev, os.lstat(peer).st_ino) == (
            os.lstat(staged_path).st_dev,
            os.lstat(staged_path).st_ino,
        )
        assert transaction_dir.exists()

    def test_primary_tombstone_unlink_is_durable_before_commit_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        primary_dir_stat = os.stat(staged_path.parent)
        primary_dir_identity = (primary_dir_stat.st_dev, primary_dir_stat.st_ino)
        fsynced_directories: set[tuple[int, int]] = set()
        commit_cleared_after_primary_sync = False
        real_fsync = upload_manager_module.os.fsync
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_fsync(descriptor):
            descriptor_stat = os.fstat(descriptor)
            if stat.S_ISDIR(descriptor_stat.st_mode):
                fsynced_directories.add((descriptor_stat.st_dev, descriptor_stat.st_ino))
            return real_fsync(descriptor)

        def observe_control_unlink(path):
            nonlocal commit_cleared_after_primary_sync
            if path.name == upload_manager_module._UPLOAD_DELETION_COMMIT_MARKER:
                commit_cleared_after_primary_sync = primary_dir_identity in fsynced_directories
            return real_unlink_control(path)

        try:
            with (
                patch.object(upload_manager_module.os, "fsync", side_effect=observe_fsync),
                patch.object(
                    upload_manager_module,
                    "_unlink_deletion_control_durably",
                    side_effect=observe_control_unlink,
                ),
            ):
                upload_manager_module._discard_staged_deletion(staged_path)
        finally:
            stage_lease.release()

        assert commit_cleared_after_primary_sync

    def test_restore_persists_visible_links_and_tombstone_removals_before_marker_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("generated", encoding="utf-8")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
            conversion_path=conversion,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        staged_conversion = upload_manager_module._staged_conversion_path(staged_path)
        transaction_dir = staged_path.parent.parent
        events: list[tuple[str, str]] = []
        real_link = upload_manager_module.os.link
        real_unlink = upload_manager_module.os.unlink
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_link(source, destination, *args, **kwargs):
            result = real_link(source, destination, *args, **kwargs)
            destination = Path(destination)
            if destination == primary:
                events.append(("link", "primary"))
            elif destination == conversion:
                events.append(("link", "conversion"))
            return result

        def observe_unlink(path, *args, **kwargs):
            path = Path(path)
            if path == staged_path:
                events.append(("unlink", "primary-tombstone"))
            elif path == staged_conversion:
                events.append(("unlink", "conversion-tombstone"))
            return real_unlink(path, *args, **kwargs)

        def observe_fsync_directory(directory):
            directory = Path(directory)
            if directory == uploads:
                events.append(("fsync", "uploads"))
            elif directory == conversion.parent:
                events.append(("fsync", "conversions"))
            elif directory == transaction_dir:
                events.append(("fsync", "transaction"))
            elif directory == staged_path.parent:
                events.append(("fsync", "primary-tombstone-dir"))
            return real_fsync_directory(directory)

        def observe_control_unlink(path):
            if path.name == upload_manager_module._UPLOAD_DELETION_RESTORE_MARKER:
                events.append(("clear", "restore"))
            return real_unlink_control(path)

        try:
            with (
                patch.object(upload_manager_module.os, "link", side_effect=observe_link),
                patch.object(upload_manager_module.os, "unlink", side_effect=observe_unlink),
                patch.object(
                    upload_manager_module,
                    "_fsync_directory_durably",
                    side_effect=observe_fsync_directory,
                ),
                patch.object(
                    upload_manager_module,
                    "_unlink_deletion_control_durably",
                    side_effect=observe_control_unlink,
                ),
            ):
                upload_manager_module._restore_staged_deletion(staged_path, primary, identity)
        finally:
            stage_lease.release()

        primary_link = events.index(("link", "primary"))
        uploads_sync = events.index(("fsync", "uploads"), primary_link)
        conversion_link = events.index(("link", "conversion"))
        conversions_sync = events.index(("fsync", "conversions"), conversion_link)
        conversion_unlink = events.index(("unlink", "conversion-tombstone"), conversions_sync)
        transaction_sync = events.index(("fsync", "transaction"), conversion_unlink)
        primary_unlink = events.index(("unlink", "primary-tombstone"), transaction_sync)
        primary_dir_sync = events.index(("fsync", "primary-tombstone-dir"), primary_unlink)
        restore_clear = events.index(("clear", "restore"), primary_dir_sync)
        assert primary_link < uploads_sync < primary_unlink
        assert conversion_link < conversions_sync < conversion_unlink < transaction_sync
        assert primary_unlink < primary_dir_sync < restore_clear

    def test_restore_recovery_persists_existing_visible_peer_before_marker_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_restore(staged_path)
        os.link(staged_path, primary)
        transaction_dir = staged_path.parent.parent
        stage_lease.release()
        events: list[tuple[str, str]] = []
        real_unlink = upload_manager_module.os.unlink
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_unlink(path, *args, **kwargs):
            if Path(path) == staged_path:
                events.append(("unlink", "primary-tombstone"))
            return real_unlink(path, *args, **kwargs)

        def observe_fsync_directory(directory):
            directory = Path(directory)
            if directory == uploads:
                events.append(("fsync", "uploads"))
            elif directory == staged_path.parent:
                events.append(("fsync", "primary-tombstone-dir"))
            return real_fsync_directory(directory)

        def observe_control_unlink(path):
            if path.name == upload_manager_module._UPLOAD_DELETION_RESTORE_MARKER:
                events.append(("clear", "restore"))
            return real_unlink_control(path)

        with (
            patch.object(upload_manager_module.os, "unlink", side_effect=observe_unlink),
            patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ),
            patch.object(
                upload_manager_module,
                "_unlink_deletion_control_durably",
                side_effect=observe_control_unlink,
            ),
        ):
            assert upload_manager_module._recover_stale_deletion_transaction(transaction_dir)

        uploads_sync = events.index(("fsync", "uploads"))
        primary_unlink = events.index(("unlink", "primary-tombstone"), uploads_sync)
        primary_dir_sync = events.index(("fsync", "primary-tombstone-dir"), primary_unlink)
        restore_clear = events.index(("clear", "restore"), primary_dir_sync)
        assert uploads_sync < primary_unlink < primary_dir_sync < restore_clear

    def test_discard_recovery_persists_visible_unlink_before_commit_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        os.link(staged_path, primary)
        transaction_dir = staged_path.parent.parent
        stage_lease.release()
        events: list[tuple[str, str]] = []
        real_unlink = upload_manager_module.os.unlink
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_unlink(path, *args, **kwargs):
            if Path(path) == primary:
                events.append(("unlink", "visible-primary"))
            return real_unlink(path, *args, **kwargs)

        def observe_fsync_directory(directory):
            if Path(directory) == uploads:
                events.append(("fsync", "uploads"))
            return real_fsync_directory(directory)

        def observe_control_unlink(path):
            if path.name == upload_manager_module._UPLOAD_DELETION_COMMIT_MARKER:
                events.append(("clear", "commit"))
            return real_unlink_control(path)

        with (
            patch.object(upload_manager_module.os, "unlink", side_effect=observe_unlink),
            patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ),
            patch.object(
                upload_manager_module,
                "_unlink_deletion_control_durably",
                side_effect=observe_control_unlink,
            ),
        ):
            assert upload_manager_module._recover_stale_deletion_transaction(transaction_dir)

        visible_unlink = events.index(("unlink", "visible-primary"))
        uploads_sync = events.index(("fsync", "uploads"), visible_unlink)
        commit_clear = events.index(("clear", "commit"), uploads_sync)
        assert visible_unlink < uploads_sync < commit_clear

    def test_missing_primary_recovery_resyncs_tombstone_dir_before_commit_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=True,
        )
        upload_manager_module._mark_staged_deletion_committed(staged_path)
        transaction_dir = staged_path.parent.parent
        primary_dir = staged_path.parent
        # Model a previous discard whose unlink is visible but whose directory
        # fsync failed. Recovery must persist this observed absence itself
        # before making commit absence durable.
        staged_path.unlink()
        stage_lease.release()
        events: list[tuple[str, str]] = []
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_fsync_directory(directory):
            if Path(directory) == primary_dir:
                events.append(("fsync", "primary-tombstone-dir"))
            return real_fsync_directory(directory)

        def observe_control_unlink(path):
            if path.name == upload_manager_module._UPLOAD_DELETION_COMMIT_MARKER:
                events.append(("clear", "commit"))
            return real_unlink_control(path)

        with (
            patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ),
            patch.object(
                upload_manager_module,
                "_unlink_deletion_control_durably",
                side_effect=observe_control_unlink,
            ),
        ):
            assert upload_manager_module._recover_stale_deletion_transaction(transaction_dir)

        primary_dir_sync = events.index(("fsync", "primary-tombstone-dir"))
        commit_clear = events.index(("clear", "commit"), primary_dir_sync)
        assert primary_dir_sync < commit_clear

    def test_missing_primary_recovery_resyncs_tombstone_dir_before_restore_clear(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"primary")
        identity = UploadIdentity.from_path(primary)
        staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
            uploads,
            primary,
            identity,
            recover_on_crash=False,
        )
        upload_manager_module._mark_staged_deletion_restore(staged_path)
        os.link(staged_path, primary)
        transaction_dir = staged_path.parent.parent
        primary_dir = staged_path.parent
        # Model a restore that published and persisted the visible peer, then
        # made the tombstone unlink visible but failed its directory fsync.
        staged_path.unlink()
        stage_lease.release()
        events: list[tuple[str, str]] = []
        real_fsync_directory = upload_manager_module._fsync_directory_durably
        real_unlink_control = upload_manager_module._unlink_deletion_control_durably

        def observe_fsync_directory(directory):
            if Path(directory) == primary_dir:
                events.append(("fsync", "primary-tombstone-dir"))
            return real_fsync_directory(directory)

        def observe_control_unlink(path):
            if path.name == upload_manager_module._UPLOAD_DELETION_RESTORE_MARKER:
                events.append(("clear", "restore"))
            return real_unlink_control(path)

        with (
            patch.object(
                upload_manager_module,
                "_fsync_directory_durably",
                side_effect=observe_fsync_directory,
            ),
            patch.object(
                upload_manager_module,
                "_unlink_deletion_control_durably",
                side_effect=observe_control_unlink,
            ),
        ):
            assert upload_manager_module._recover_stale_deletion_transaction(transaction_dir)

        primary_dir_sync = events.index(("fsync", "primary-tombstone-dir"))
        restore_clear = events.index(("clear", "restore"), primary_dir_sync)
        assert primary_dir_sync < restore_clear

    def test_commit_marker_failure_prevents_remote_side_effect_and_restores_host(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"PDF")
        owned_conversion = conversion_path_for_upload(primary)
        owned_conversion.parent.mkdir()
        owned_conversion.write_text("generated", encoding="utf-8")
        remote_names: list[str] = []

        with patch.object(
            upload_manager_module,
            "_mark_staged_deletion_committed",
            side_effect=OSError("cannot persist commit marker"),
        ):
            with pytest.raises(OSError, match="cannot persist commit marker"):
                delete_file_safe(
                    uploads,
                    "report.pdf",
                    delete_remote_copy=lambda name, _primary, _conversion: remote_names.append(name),
                )

        assert remote_names == []
        assert primary.read_bytes() == b"PDF"
        assert owned_conversion.read_text(encoding="utf-8") == "generated"
        assert not list(owned_conversion.parent.glob(".upload-delete-*.part"))

    def test_failed_delete_preserves_old_generation_when_name_is_recreated(self, tmp_path):
        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "report.pdf"
        primary.write_bytes(b"old generation")

        def recreate_then_fail(_filename, _primary_path, _conversion_path):
            primary.write_bytes(b"new generation")
            raise RemoteDeletionCompensatedError("remote delete failed")

        with pytest.raises((RemoteDeletionCompensatedError, UnsafeUploadPathError)):
            delete_file_safe(
                uploads,
                primary.name,
                delete_remote_copy=recreate_then_fail,
            )

        recovered = list(uploads.glob("report.pdf_recovered_*"))
        assert primary.read_bytes() == b"new generation"
        assert len(recovered) == 1
        assert recovered[0].read_bytes() == b"old generation"
        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        assert recovered[0].read_bytes() == b"old generation"

    def test_portable_alias_rename_deletes_original_companions(self, tmp_path):
        import deerflow.uploads.manager as upload_manager_module

        uploads = tmp_path / "user-data" / "uploads"
        uploads.mkdir(parents=True)
        primary = uploads / "straße.pdf"
        primary.write_bytes(b"payload")
        conversion = conversion_path_for_upload(primary)
        conversion.parent.mkdir()
        conversion.write_text("generated", encoding="utf-8")
        renamed = uploads / "strasse.pdf"
        remote_names: list[str] = []
        real_find = upload_manager_module._find_upload_path_by_identity

        def rename_after_scan(base_dir, identity):
            found = real_find(base_dir, identity)
            found.rename(renamed)
            return renamed

        with patch.object(
            upload_manager_module,
            "_find_upload_path_by_identity",
            side_effect=rename_after_scan,
        ):
            delete_file_safe(
                uploads,
                primary.name,
                delete_remote_copy=lambda name, _primary, _conversion: remote_names.append(name),
            )

        assert not renamed.exists()
        assert not conversion.exists()
        assert remote_names == ["straße.pdf"]
