"""Tests for the uploads companion-map sidecar."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from deerflow.uploads import companion_map as companion_map_mod
from deerflow.uploads.companion_map import (
    COMPANION_MAP_FILENAME,
    COMPANION_MAP_LOCK_FILENAME,
    CompanionEntry,
    CompanionMapLockError,
    companion_entry_matches,
    companion_map_lock_path,
    forget_companion_mapping,
    forget_companion_mappings,
    has_companion_entry,
    is_companion_map_file,
    load_companion_entries,
    load_companion_map,
    lookup_companion_mapping,
    mapped_companion_names,
    record_companion_mapping,
)
from deerflow.uploads.manager import (
    PathTraversalError,
    delete_file_safe,
    is_upload_hidden_file,
    list_files_in_dir,
    normalize_filename,
)
from deerflow.utils.file_outline import resolve_converted_markdown_path


def _thread_uploads(tmp_path: Path) -> Path:
    """Production layout: ``.../user-data/uploads`` (lock lives beside user-data)."""
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    return uploads


class TestCompanionMapFilePredicate:
    def test_json_and_lock_and_tmp_are_internal(self):
        assert is_companion_map_file(COMPANION_MAP_FILENAME)
        assert is_companion_map_file(".deer-flow-companions.lock")
        assert is_companion_map_file(".deer-flow-companions.abc.tmp")
        assert not is_companion_map_file("report.md")
        assert not is_companion_map_file(".env")

    def test_hidden_file_covers_staging_and_sidecar(self):
        assert is_upload_hidden_file(".upload-active.part")
        assert is_upload_hidden_file(COMPANION_MAP_FILENAME)
        assert not is_upload_hidden_file("report.pdf")

    def test_lock_path_uses_thread_dir_for_user_data_layout(self, tmp_path):
        uploads = tmp_path / "user-data" / "uploads"
        assert companion_map_lock_path(uploads) == tmp_path / COMPANION_MAP_LOCK_FILENAME

    def test_lock_path_stays_one_level_up_without_user_data(self, tmp_path):
        uploads = tmp_path / "uploads"
        assert companion_map_lock_path(uploads) == tmp_path / COMPANION_MAP_LOCK_FILENAME


class TestRecordAndLoad:
    def test_round_trip(self, tmp_path):
        (tmp_path / "a.md").write_text("# docx\n", encoding="utf-8")
        (tmp_path / "a_1.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        assert load_companion_map(tmp_path) == {"a.docx": "a.md", "a.pdf": "a_1.md"}
        assert lookup_companion_mapping(tmp_path, "a.pdf") == "a_1.md"
        assert lookup_companion_mapping(tmp_path, "missing.pdf") is None

    def test_record_captures_convert_time_fingerprint(self, tmp_path):
        companion = tmp_path / "a.md"
        companion.write_text("# docx\n", encoding="utf-8")
        expected = companion.stat()

        record_companion_mapping(tmp_path, "a.docx", "a.md")

        entries = load_companion_entries(tmp_path)
        assert entries["a.docx"] == CompanionEntry(
            name="a.md",
            size=expected.st_size,
            mtime_ns=expected.st_mtime_ns,
        )
        raw = json.loads((tmp_path / COMPANION_MAP_FILENAME).read_text(encoding="utf-8"))
        assert raw["version"] == 2
        assert raw["companions"]["a.docx"]["name"] == "a.md"
        assert raw["companions"]["a.docx"]["size"] == expected.st_size

    def test_record_requires_an_existing_regular_companion(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            record_companion_mapping(tmp_path, "a.pdf", "ghost.md")
        assert load_companion_map(tmp_path) == {}

    def test_replaces_previous_owner_of_the_same_companion(self, tmp_path):
        (tmp_path / "shared.md").write_text("# shared\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "old.pdf", "shared.md")
        record_companion_mapping(tmp_path, "new.pdf", "shared.md")

        mapping = load_companion_map(tmp_path)
        assert mapping == {"new.pdf": "shared.md"}

    def test_rejects_path_traversal_names(self, tmp_path):
        with pytest.raises(ValueError):
            record_companion_mapping(tmp_path, "../escape.pdf", "a.md")
        with pytest.raises(ValueError):
            record_companion_mapping(tmp_path, "a.pdf", "../escape.md")
        assert load_companion_map(tmp_path) == {}

    def test_corrupt_sidecar_reads_as_empty(self, tmp_path):
        (tmp_path / COMPANION_MAP_FILENAME).write_text("not-json", encoding="utf-8")
        assert load_companion_map(tmp_path) == {}

    def test_malformed_rows_are_sanitized(self, tmp_path):
        payload = {
            "version": 2,
            "companions": {
                "ok.pdf": {"name": "ok.md", "size": 3, "mtime_ns": 123},
                "legacy.pdf": "legacy.md",
                "bad-name.pdf": {"name": "../escape.md", "size": 1, "mtime_ns": 1},
                "bad-size.pdf": {"name": "b.md", "size": "huge", "mtime_ns": True},
                "not-dict.pdf": 42,
                "../evil.pdf": "x.md",
            },
        }
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

        assert load_companion_map(tmp_path) == {
            "ok.pdf": "ok.md",
            "legacy.pdf": "legacy.md",
            "bad-size.pdf": "b.md",
        }
        entries = load_companion_entries(tmp_path)
        assert entries["ok.pdf"] == CompanionEntry(name="ok.md", size=3, mtime_ns=123)
        # Malformed fingerprint fields degrade to "no fingerprint", not a dropped row.
        assert entries["bad-size.pdf"] == CompanionEntry(name="b.md")

    def test_ignores_symlink_sidecar(self, tmp_path):
        target = tmp_path / "outside.json"
        target.write_text('{"version": 1, "companions": {"a.pdf": "a.md"}}', encoding="utf-8")
        sidecar = tmp_path / COMPANION_MAP_FILENAME
        try:
            sidecar.symlink_to(target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("symlink creation requires Developer Mode or elevated privileges on Windows")
            raise
        assert load_companion_map(tmp_path) == {}


class TestLegacyV1Sidecar:
    def test_string_rows_verify_by_existence_only(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF")
        (tmp_path / "a_1.md").write_text("# PDF\n", encoding="utf-8")
        payload = {"version": 1, "companions": {"a.pdf": "a_1.md"}}
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

        assert load_companion_map(tmp_path) == {"a.pdf": "a_1.md"}
        assert load_companion_entries(tmp_path)["a.pdf"] == CompanionEntry(name="a_1.md")
        assert lookup_companion_mapping(tmp_path, "a.pdf") == "a_1.md"
        assert mapped_companion_names(tmp_path) == {"a_1.md"}
        assert resolve_converted_markdown_path(tmp_path / "a.pdf") == tmp_path / "a_1.md"


class TestForget:
    def test_forget_original_and_empty_file_is_removed(self, tmp_path):
        (tmp_path / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a.md")
        forget_companion_mapping(tmp_path, original="a.pdf")
        assert load_companion_map(tmp_path) == {}
        assert not (tmp_path / COMPANION_MAP_FILENAME).exists()

    def test_forget_by_companion_name(self, tmp_path):
        (tmp_path / "a.md").write_text("# docx\n", encoding="utf-8")
        (tmp_path / "a_1.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        forget_companion_mapping(tmp_path, companion="a_1.md")
        assert load_companion_map(tmp_path) == {"a.docx": "a.md"}


class TestMappedCompanionNames:
    def test_only_companions_that_exist(self, tmp_path):
        (tmp_path / "a.md").write_text("# docx\n", encoding="utf-8")
        renamed = tmp_path / "a_1.md"
        renamed.write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        renamed.unlink()

        assert mapped_companion_names(tmp_path) == {"a.md"}

    def test_preloaded_entries_do_not_reread_sidecar(self, tmp_path, monkeypatch):
        (tmp_path / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a.md")
        preloaded = load_companion_entries(tmp_path)

        loads = {"n": 0}
        real = companion_map_mod._load_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_unlocked", counting)

        assert mapped_companion_names(tmp_path, preloaded) == {"a.md"}
        assert loads["n"] == 0
        assert mapped_companion_names(tmp_path) == {"a.md"}
        assert loads["n"] == 1


class TestFingerprintStaleness:
    def test_modified_companion_content_is_stale(self, tmp_path):
        companion = tmp_path / "a_1.md"
        companion.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        companion.write_text("# PDF\n\nedited inside the sandbox\n", encoding="utf-8")

        entry = load_companion_entries(tmp_path)["a.pdf"]
        assert not companion_entry_matches(tmp_path, entry)
        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert mapped_companion_names(tmp_path) == set()
        assert has_companion_entry(tmp_path, "a.pdf") is True

    def test_same_named_replacement_is_not_the_recorded_companion(self, tmp_path):
        """The stale-sidecar gap: companion deleted outside the API, then an
        unrelated user file takes its name. The replacement must not be hidden
        from listings, not be attached to the original, and not be deleted
        with the original."""
        (tmp_path / "a.docx").write_bytes(b"docx")
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# FROM DOCX\n", encoding="utf-8")
        companion = tmp_path / "a_1.md"
        companion.write_text("# FROM PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        # Companion removed bypassing delete_file_safe (e.g. sandbox `rm`),
        # then the user uploads their own file under the same name.
        companion.unlink()
        replacement = tmp_path / "a_1.md"
        replacement.write_text("# My own notes, unrelated to any PDF\n", encoding="utf-8")

        # Not hidden: the replacement is a user file, not a conversion artifact.
        assert mapped_companion_names(tmp_path) == {"a.md"}
        # Not attached: a.pdf must not read the replacement as its converted text,
        # and must not fall back to the DOCX-derived a.md either.
        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert has_companion_entry(tmp_path, "a.pdf") is True
        assert resolve_converted_markdown_path(pdf) is None
        # The healthy a.docx → a.md mapping is unaffected.
        assert resolve_converted_markdown_path(tmp_path / "a.docx") == tmp_path / "a.md"

        # Not deleted: removing a.pdf must leave the replacement and a.md alone.
        delete_file_safe(tmp_path, "a.pdf", convertible_extensions={".pdf", ".docx"})
        assert not pdf.exists()
        assert replacement.read_text(encoding="utf-8") == "# My own notes, unrelated to any PDF\n"
        assert (tmp_path / "a.md").exists()
        # The stale entry is forgotten with the original; a.docx stays mapped.
        assert load_companion_map(tmp_path) == {"a.docx": "a.md"}

    def test_missing_companion_is_stale(self, tmp_path):
        companion = tmp_path / "a_1.md"
        companion.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        companion.unlink()

        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert mapped_companion_names(tmp_path) == set()
        assert has_companion_entry(tmp_path, "a.pdf") is True


class TestResolveUsesSidecar:
    def test_sidecar_wins_over_same_stem_sibling(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# DOCX\n", encoding="utf-8")
        renamed = tmp_path / "a_1.md"
        renamed.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        assert resolve_converted_markdown_path(pdf) == renamed

    def test_stale_sidecar_does_not_fall_back_to_sibling(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# DOCX\n", encoding="utf-8")
        companion = tmp_path / "a_1.md"
        companion.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        companion.unlink()

        assert resolve_converted_markdown_path(pdf) is None

    def test_legacy_stem_fallback_without_sidecar(self, tmp_path):
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF")
        sibling = tmp_path / "report.md"
        sibling.write_text("# Safe\n", encoding="utf-8")

        assert resolve_converted_markdown_path(pdf) == sibling

    def test_explicit_name_still_wins(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# DOCX\n", encoding="utf-8")
        renamed = tmp_path / "a_1.md"
        renamed.write_text("# PDF\n", encoding="utf-8")
        (tmp_path / "wrong.md").write_text("# WRONG\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "wrong.md")

        assert resolve_converted_markdown_path(pdf, companion_name="a_1.md") == renamed

    def test_preloaded_entries_skip_disk_read(self, tmp_path, monkeypatch):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# DOCX\n", encoding="utf-8")
        renamed = tmp_path / "a_1.md"
        renamed.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        preloaded = load_companion_entries(tmp_path)

        loads = {"n": 0}
        real = companion_map_mod._load_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_unlocked", counting)

        assert resolve_converted_markdown_path(pdf, entries=preloaded) == renamed
        assert loads["n"] == 0

    def test_empty_preloaded_entries_do_not_consult_disk_sidecar(self, tmp_path, monkeypatch):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF")
        (tmp_path / "a.md").write_text("# DOCX\n", encoding="utf-8")
        renamed = tmp_path / "a_1.md"
        renamed.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        loads = {"n": 0}
        real = companion_map_mod._load_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_unlocked", counting)

        # No sidecar row in the preloaded map → legacy stem fallback, no disk read.
        assert resolve_converted_markdown_path(pdf, entries={}) == tmp_path / "a.md"
        assert loads["n"] == 0


class TestListingHidesSidecar:
    def test_list_files_in_dir_skips_sidecar(self, tmp_path):
        (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")
        (tmp_path / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a.md")
        (tmp_path / ".deer-flow-companions.lock").write_text("", encoding="utf-8")

        result = list_files_in_dir(tmp_path)
        assert [f["filename"] for f in result["files"]] == ["a.md", "visible.txt"]


class TestNormalizeRejectsReservedSidecarName:
    def test_rejects_companion_map_filename(self):
        with pytest.raises(ValueError, match="reserved"):
            normalize_filename(COMPANION_MAP_FILENAME)
        with pytest.raises(ValueError, match="reserved"):
            normalize_filename(".deer-flow-companions.lock")


class TestDeleteUsesSidecar:
    def test_deletes_mapped_companion_not_the_sibling_stem(self, tmp_path):
        (tmp_path / "a.docx").write_bytes(b"docx")
        (tmp_path / "a.pdf").write_bytes(b"pdf")
        (tmp_path / "a.md").write_text("FROM DOCX", encoding="utf-8")
        (tmp_path / "a_1.md").write_text("FROM PDF", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        result = delete_file_safe(tmp_path, "a.pdf", convertible_extensions={".pdf", ".docx"})

        assert result["success"] is True
        assert not (tmp_path / "a.pdf").exists()
        assert not (tmp_path / "a_1.md").exists()
        assert (tmp_path / "a.docx").exists()
        assert (tmp_path / "a.md").exists()
        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert lookup_companion_mapping(tmp_path, "a.docx") == "a.md"

    def test_legacy_stem_companion_without_sidecar(self, tmp_path):
        (tmp_path / "report.pdf").write_bytes(b"pdf-bytes")
        (tmp_path / "report.md").write_text("converted", encoding="utf-8")

        delete_file_safe(tmp_path, "report.pdf", convertible_extensions={".pdf"})

        assert not (tmp_path / "report.pdf").exists()
        assert not (tmp_path / "report.md").exists()

    def test_refuses_to_delete_sidecar(self, tmp_path):
        (tmp_path / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a.md")
        with pytest.raises(FileNotFoundError):
            delete_file_safe(tmp_path, COMPANION_MAP_FILENAME)
        assert (tmp_path / COMPANION_MAP_FILENAME).is_file()

    def test_delete_companion_clears_mapping(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"pdf")
        (tmp_path / "a_1.md").write_text("FROM PDF", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")

        delete_file_safe(tmp_path, "a_1.md")

        assert not (tmp_path / "a_1.md").exists()
        assert (tmp_path / "a.pdf").exists()
        assert lookup_companion_mapping(tmp_path, "a.pdf") is None

    def test_delete_traversal_still_raises(self, tmp_path):
        with pytest.raises(PathTraversalError):
            delete_file_safe(tmp_path, "../outside.txt")


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("symlink creation requires Developer Mode or elevated privileges on Windows")
        raise


class TestLockLivesOutsideSandbox:
    def test_production_layout_puts_lock_beside_user_data(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(uploads, "a.pdf", "a.md")

        lock = companion_map_lock_path(uploads)
        assert lock == tmp_path / COMPANION_MAP_LOCK_FILENAME
        assert lock.is_file()
        assert not lock.is_symlink()
        assert stat.S_ISREG(lock.stat().st_mode)
        assert not (uploads / COMPANION_MAP_LOCK_FILENAME).exists()
        assert not (uploads.parent / COMPANION_MAP_LOCK_FILENAME).exists()
        assert lookup_companion_mapping(uploads, "a.pdf") == "a.md"

    def test_sandbox_lock_inside_uploads_is_ignored(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        planted = uploads / COMPANION_MAP_LOCK_FILENAME
        planted.write_bytes(b"sandbox-held")

        record_companion_mapping(uploads, "a.pdf", "a.md")

        assert planted.read_bytes() == b"sandbox-held"
        assert lookup_companion_mapping(uploads, "a.pdf") == "a.md"
        assert companion_map_lock_path(uploads).is_file()


class TestLockDoesNotFollowSymlink:
    def test_record_does_not_follow_lock_symlink_to_host_file(self, tmp_path):
        """A symlink at the real lock path must not be followed with Gateway privileges."""
        host_target = tmp_path / "host-secret"
        host_target.write_bytes(b"")
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        _symlink_or_skip(companion_map_lock_path(uploads), host_target)

        with pytest.raises(CompanionMapLockError):
            record_companion_mapping(uploads, "a.pdf", "a.md")

        assert host_target.read_bytes() == b""
        assert not (uploads / COMPANION_MAP_FILENAME).exists()

    def test_forget_does_not_follow_lock_symlink_to_host_file(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(uploads, "a.pdf", "a.md")

        host_target = tmp_path / "host-secret"
        host_target.write_bytes(b"untouched")
        lock_path = companion_map_lock_path(uploads)
        lock_path.unlink()
        _symlink_or_skip(lock_path, host_target)

        with pytest.raises(CompanionMapLockError):
            forget_companion_mapping(uploads, original="a.pdf")

        assert host_target.read_bytes() == b"untouched"
        assert load_companion_map(uploads) == {"a.pdf": "a.md"}

    def test_rejects_lock_directory(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        companion_map_lock_path(uploads).mkdir()

        with pytest.raises(CompanionMapLockError):
            record_companion_mapping(uploads, "a.pdf", "a.md")

        assert not (uploads / COMPANION_MAP_FILENAME).exists()

    def test_rejects_hardlinked_lock(self, tmp_path):
        host_target = tmp_path / "host-secret"
        host_target.write_bytes(b"keep")
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        try:
            os.link(host_target, companion_map_lock_path(uploads))
        except OSError as exc:
            pytest.skip(f"hardlink not supported: {exc}")

        with pytest.raises(CompanionMapLockError):
            record_companion_mapping(uploads, "a.pdf", "a.md")

        assert host_target.read_bytes() == b"keep"
        assert not (uploads / COMPANION_MAP_FILENAME).exists()

    def test_regular_lock_still_records(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(uploads, "a.pdf", "a.md")
        assert lookup_companion_mapping(uploads, "a.pdf") == "a.md"
        lock = companion_map_lock_path(uploads)
        assert lock.is_file()
        assert not lock.is_symlink()
        assert stat.S_ISREG(lock.stat().st_mode)

    def test_fallback_without_nofollow_still_rejects_symlink(self, tmp_path, monkeypatch):
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
        host_target = tmp_path / "host-secret"
        host_target.write_bytes(b"")
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        _symlink_or_skip(companion_map_lock_path(uploads), host_target)

        with pytest.raises(CompanionMapLockError):
            record_companion_mapping(uploads, "a.pdf", "a.md")

        assert host_target.read_bytes() == b""
        assert not (uploads / COMPANION_MAP_FILENAME).exists()


class TestLockWaitIsBounded:
    def test_record_skips_write_when_lock_is_held(self, tmp_path, monkeypatch):
        if companion_map_mod.fcntl is None:
            pytest.skip("fcntl flock is required to hold the lock from the test process")
        monkeypatch.setattr(companion_map_mod, "_LOCK_RETRY_ATTEMPTS", 2)
        monkeypatch.setattr(companion_map_mod, "_LOCK_RETRY_INTERVAL_S", 0)

        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        lock_path = companion_map_lock_path(uploads)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            companion_map_mod.fcntl.flock(fd, companion_map_mod.fcntl.LOCK_EX)
            record_companion_mapping(uploads, "a.pdf", "a.md")
        finally:
            companion_map_mod.fcntl.flock(fd, companion_map_mod.fcntl.LOCK_UN)
            os.close(fd)

        assert load_companion_map(uploads) == {}
        assert not (uploads / COMPANION_MAP_FILENAME).exists()

    def test_forget_skips_when_lock_is_held(self, tmp_path, monkeypatch):
        if companion_map_mod.fcntl is None:
            pytest.skip("fcntl flock is required to hold the lock from the test process")
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(uploads, "a.pdf", "a.md")

        monkeypatch.setattr(companion_map_mod, "_LOCK_RETRY_ATTEMPTS", 2)
        monkeypatch.setattr(companion_map_mod, "_LOCK_RETRY_INTERVAL_S", 0)
        lock_path = companion_map_lock_path(uploads)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            companion_map_mod.fcntl.flock(fd, companion_map_mod.fcntl.LOCK_EX)
            forget_companion_mapping(uploads, original="a.pdf")
            forget_companion_mappings(uploads, [("a.pdf", "a.md")])
        finally:
            companion_map_mod.fcntl.flock(fd, companion_map_mod.fcntl.LOCK_UN)
            os.close(fd)

        assert load_companion_map(uploads) == {"a.pdf": "a.md"}
