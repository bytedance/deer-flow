"""Tests for the uploads companion-map sidecar."""

from __future__ import annotations

import errno
import json
import math
import os
import shutil
import stat
import threading
from pathlib import Path

import pytest

from deerflow.uploads import companion_map as companion_map_mod
from deerflow.uploads.companion_map import (
    COMPANION_ID_DIRNAME,
    COMPANION_MAP_FILENAME,
    COMPANION_MAP_LOCK_FILENAME,
    CompanionEntry,
    CompanionMapLockError,
    CopiedFileIdentity,
    companion_entry_matches,
    companion_identity_dir,
    companion_identity_path,
    companion_map_lock_path,
    copied_upload_identities,
    copy_user_data_tree,
    forget_companion_mapping,
    forget_companion_mappings,
    has_companion_entry,
    is_companion_map_file,
    load_companion_entries,
    load_companion_map,
    load_companion_state,
    lookup_companion_mapping,
    mapped_companion_names,
    rebind_cloned_companion_identities,
    record_companion_mapping,
    release_copied_identities,
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
        assert is_companion_map_file(".deer-flow-companions.id." + "a" * 32)
        assert is_companion_map_file(".deer-flow-companions.quarantine." + "ab" * 16)
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
        recorded = entries["a.docx"]
        assert recorded.name == "a.md"
        assert recorded.size == expected.st_size
        assert recorded.mtime_ns == expected.st_mtime_ns
        assert recorded.dev == expected.st_dev
        assert recorded.ino == expected.st_ino
        assert recorded.id is not None
        pin = companion_identity_path(tmp_path, recorded.id)
        assert pin.is_file()
        assert not pin.is_symlink()
        assert pin.stat().st_ino == expected.st_ino
        raw = json.loads((tmp_path / COMPANION_MAP_FILENAME).read_text(encoding="utf-8"))
        assert raw["version"] == 2
        assert raw["companions"]["a.docx"]["name"] == "a.md"
        assert raw["companions"]["a.docx"]["size"] == expected.st_size
        assert raw["companions"]["a.docx"]["dev"] == expected.st_dev
        assert raw["companions"]["a.docx"]["ino"] == expected.st_ino
        assert raw["companions"]["a.docx"]["id"] == recorded.id

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
                "ok.pdf": {"name": "ok.md", "size": 3, "mtime_ns": 123, "dev": 1, "ino": 99},
                "legacy.pdf": "legacy.md",
                "bad-name.pdf": {"name": "../escape.md", "size": 1, "mtime_ns": 1},
                "bad-size.pdf": {"name": "b.md", "size": "huge", "mtime_ns": True, "dev": "x", "ino": True},
                "bad-id.pdf": {"name": "c.md", "id": "../escape"},
                "not-dict.pdf": 42,
                "../evil.pdf": "x.md",
            },
        }
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

        assert load_companion_map(tmp_path) == {
            "ok.pdf": "ok.md",
            "legacy.pdf": "legacy.md",
            "bad-size.pdf": "b.md",
            "bad-id.pdf": "c.md",
        }
        entries = load_companion_entries(tmp_path)
        assert entries["ok.pdf"] == CompanionEntry(name="ok.md", size=3, mtime_ns=123, dev=1, ino=99)
        # Malformed fingerprint fields degrade to "no fingerprint", not a dropped row.
        assert entries["bad-size.pdf"] == CompanionEntry(name="b.md")
        assert entries["bad-id.pdf"] == CompanionEntry(name="c.md")

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
        recorded = load_companion_entries(tmp_path)["a.pdf"]
        forget_companion_mapping(tmp_path, original="a.pdf")
        assert load_companion_map(tmp_path) == {}
        assert not (tmp_path / COMPANION_MAP_FILENAME).exists()
        if recorded.id is not None:
            assert not companion_identity_path(tmp_path, recorded.id).exists()

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
        real = companion_map_mod._load_state_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_state_unlocked", counting)

        assert mapped_companion_names(tmp_path, preloaded) == {"a.md"}
        assert loads["n"] == 0
        assert mapped_companion_names(tmp_path) == {"a.md"}
        assert loads["n"] == 1


class TestFingerprintStaleness:
    def test_in_place_edit_keeps_companion_attached(self, tmp_path):
        companion = tmp_path / "a_1.md"
        companion.write_text("# PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        recorded = companion.stat()
        companion.write_text("# PDF\n\nedited inside the sandbox\n", encoding="utf-8")
        after = companion.stat()
        assert (after.st_dev, after.st_ino) == (recorded.st_dev, recorded.st_ino)

        entry = load_companion_entries(tmp_path)["a.pdf"]
        assert companion_entry_matches(tmp_path, entry)
        assert lookup_companion_mapping(tmp_path, "a.pdf") == "a_1.md"
        assert mapped_companion_names(tmp_path) == {"a_1.md"}
        assert has_companion_entry(tmp_path, "a.pdf") is True

    def test_recreated_same_bytes_is_stale(self, tmp_path):
        companion = tmp_path / "a_1.md"
        text = "# PDF\n"
        companion.write_text(text, encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        recorded = load_companion_entries(tmp_path)["a.pdf"]
        companion.unlink()
        replacement = tmp_path / "a_1.md"
        replacement.write_text(text, encoding="utf-8")
        if recorded.id is None and recorded.ino is not None and replacement.stat().st_ino == recorded.ino:
            pytest.skip("filesystem reused the inode and identity pin was unavailable")

        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert mapped_companion_names(tmp_path) == set()
        assert has_companion_entry(tmp_path, "a.pdf") is True

    def test_legacy_size_mtime_row_treats_edit_as_stale(self, tmp_path):
        companion = tmp_path / "a_1.md"
        companion.write_text("# PDF\n", encoding="utf-8")
        st = companion.stat()
        payload = {
            "version": 2,
            "companions": {
                "a.pdf": {
                    "name": "a_1.md",
                    "size": st.st_size,
                    "mtime_ns": st.st_mtime_ns,
                }
            },
        }
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        companion.write_text("# PDF\n\nedited\n", encoding="utf-8")

        entry = load_companion_entries(tmp_path)["a.pdf"]
        assert entry.dev is None and entry.ino is None
        assert not companion_entry_matches(tmp_path, entry)
        assert lookup_companion_mapping(tmp_path, "a.pdf") is None

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
        real = companion_map_mod._load_state_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_state_unlocked", counting)

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
        real = companion_map_mod._load_state_unlocked

        def counting(uploads_dir):
            loads["n"] += 1
            return real(uploads_dir)

        monkeypatch.setattr(companion_map_mod, "_load_state_unlocked", counting)

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

    def test_delete_preserves_companion_replaced_after_original_unlink(self, tmp_path, monkeypatch):
        """Sandbox can replace the companion basename after the original is gone.

        lookup/fingerprint ran against the conversion artifact, but the later
        unlink must not delete whatever now occupies that name.
        """
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF")
        companion = tmp_path / "report.md"
        companion.write_text("# converted\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report.md")

        real_unlink = Path.unlink

        def unlink_then_plant(path_self, missing_ok=False):
            name = path_self.name
            result = real_unlink(path_self, missing_ok=missing_ok)
            if name == "report.pdf":
                planted = path_self.with_name("report.md")
                if planted.exists() or planted.is_symlink():
                    real_unlink(planted, missing_ok=True)
                planted.write_text("# sandbox replacement\n", encoding="utf-8")
            return result

        monkeypatch.setattr(Path, "unlink", unlink_then_plant)
        delete_file_safe(tmp_path, "report.pdf", convertible_extensions={".pdf"})

        planted = tmp_path / "report.md"
        assert planted.read_text(encoding="utf-8") == "# sandbox replacement\n"
        assert lookup_companion_mapping(tmp_path, "report.pdf") is None

    def test_delete_preserves_replacement_outside_sandbox_mount_layout(self, tmp_path, monkeypatch):
        uploads = _thread_uploads(tmp_path)
        pdf = uploads / "report.pdf"
        pdf.write_bytes(b"%PDF")
        (uploads / "report.md").write_text("# converted\n", encoding="utf-8")
        record_companion_mapping(uploads, "report.pdf", "report.md")

        real_unlink = Path.unlink

        def unlink_then_plant(path_self, missing_ok=False):
            name = path_self.name
            result = real_unlink(path_self, missing_ok=missing_ok)
            if name == "report.pdf":
                planted = path_self.with_name("report.md")
                if planted.exists() or planted.is_symlink():
                    real_unlink(planted, missing_ok=True)
                planted.write_text("# sandbox replacement\n", encoding="utf-8")
            return result

        monkeypatch.setattr(Path, "unlink", unlink_then_plant)
        delete_file_safe(uploads, "report.pdf", convertible_extensions={".pdf"})

        planted = uploads / "report.md"
        assert planted.read_text(encoding="utf-8") == "# sandbox replacement\n"
        assert not list(uploads.glob(".deer-flow-companions.quarantine.*"))

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


class TestIdentityPinSurvivesInodeReuse:
    def test_production_layout_pins_identity_beside_user_data(self, tmp_path):
        uploads = _thread_uploads(tmp_path)
        (uploads / "a.md").write_text("# pdf\n", encoding="utf-8")
        record_companion_mapping(uploads, "a.pdf", "a.md")

        entry = load_companion_entries(uploads)["a.pdf"]
        assert entry.id is not None
        pin = companion_identity_path(uploads, entry.id)
        assert pin.parent == tmp_path / COMPANION_ID_DIRNAME
        assert pin.is_file()
        assert not pin.is_symlink()
        assert pin.stat().st_ino == (uploads / "a.md").stat().st_ino
        assert not list(uploads.glob(".deer-flow-companions.id.*"))

    def test_inode_number_reuse_does_not_attach_replacement(self, tmp_path):
        companion = tmp_path / "a_1.md"
        companion.write_text("# FROM PDF\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        recorded = load_companion_entries(tmp_path)["a.pdf"]
        companion.unlink()
        replacement = tmp_path / "a_1.md"
        replacement.write_text("# My own notes, unrelated to any PDF\n", encoding="utf-8")

        assert lookup_companion_mapping(tmp_path, "a.pdf") is None
        assert mapped_companion_names(tmp_path) == set()
        if recorded.id is not None:
            pin = companion_identity_path(tmp_path, recorded.id)
            assert pin.exists()
            assert pin.stat().st_ino != replacement.stat().st_ino


class TestSidecarReadBounds:
    def test_oversized_sidecar_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_BYTES", 64)
        payload = {"version": 2, "companions": {"a.pdf": {"name": "a.md", "size": 1, "mtime_ns": 1}}}
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload) + ("x" * 200), encoding="utf-8")

        assert load_companion_map(tmp_path) == {}

    def test_entry_cap_drops_the_tail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_ENTRIES", 2)
        payload = {
            "version": 2,
            "companions": {
                "a.pdf": "a.md",
                "b.pdf": "b.md",
                "c.pdf": "c.md",
            },
        }
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        (tmp_path / "a.md").write_text("a", encoding="utf-8")
        (tmp_path / "b.md").write_text("b", encoding="utf-8")
        (tmp_path / "c.md").write_text("c", encoding="utf-8")

        assert load_companion_map(tmp_path) == {"a.pdf": "a.md", "b.pdf": "b.md"}

    def test_sidecar_open_uses_nonblocking_flag_when_available(self, tmp_path, monkeypatch):
        if not hasattr(os, "O_NONBLOCK"):
            pytest.skip("O_NONBLOCK not available on this platform")
        captured: list[int] = []
        real_open = os.open

        def _open(path, flags, *args):
            captured.append(flags)
            return real_open(path, flags, *args)

        monkeypatch.setattr(companion_map_mod.os, "open", _open)
        (tmp_path / COMPANION_MAP_FILENAME).write_text("{}", encoding="utf-8")

        assert load_companion_map(tmp_path) == {}
        assert captured
        assert captured[0] & os.O_NONBLOCK

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo is POSIX-only")
    def test_fifo_sidecar_without_writer_returns_empty(self, tmp_path):
        os.mkfifo(tmp_path / COMPANION_MAP_FILENAME)
        result: dict[str, object] = {}
        errors: list[BaseException] = []

        def _load() -> None:
            try:
                result["map"] = load_companion_map(tmp_path)
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=_load, daemon=True)
        worker.start()
        worker.join(timeout=2)
        if worker.is_alive():
            pytest.fail("load_companion_map blocked on a FIFO sidecar with no writer")
        assert errors == []
        assert result["map"] == {}


class TestSidecarWriteBounds:
    def test_persist_prunes_to_entry_cap_and_unpins_oldest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_ENTRIES", 2)
        for stem in ("a", "b"):
            (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
            record_companion_mapping(tmp_path, f"{stem}.pdf", f"{stem}.md")
        oldest = load_companion_entries(tmp_path)["a.pdf"]

        (tmp_path / "c.md").write_text("c", encoding="utf-8")
        record_companion_mapping(tmp_path, "c.pdf", "c.md")

        loaded = load_companion_entries(tmp_path)
        assert {original: entry.name for original, entry in loaded.items()} == {"b.pdf": "b.md", "c.pdf": "c.md"}
        assert load_companion_state(tmp_path).evicted == ("a.pdf",)
        if oldest.id is not None:
            assert not companion_identity_path(tmp_path, oldest.id).exists()
        newest = loaded["c.pdf"]
        if newest.id is not None:
            assert companion_identity_path(tmp_path, newest.id).exists()

    def test_persist_prunes_to_byte_cap_instead_of_dropping_the_map(self, tmp_path, monkeypatch):
        for stem in ("a", "b"):
            (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
            record_companion_mapping(tmp_path, f"{stem}.pdf", f"{stem}.md")
        size_two = (tmp_path / COMPANION_MAP_FILENAME).stat().st_size
        oldest = load_companion_entries(tmp_path)["a.pdf"]
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_BYTES", size_two)

        (tmp_path / "c.md").write_text("c", encoding="utf-8")
        record_companion_mapping(tmp_path, "c.pdf", "c.md")

        loaded = load_companion_map(tmp_path)
        assert loaded, "a persist that exceeds the reader byte cap must prune, not write an unreadable map"
        assert loaded.get("c.pdf") == "c.md"
        assert "a.pdf" not in loaded
        state = load_companion_state(tmp_path)
        assert "a.pdf" in state.evicted or state.no_legacy_fallback
        if oldest.id is not None:
            assert not companion_identity_path(tmp_path, oldest.id).exists()
        sidecar_size = (tmp_path / COMPANION_MAP_FILENAME).stat().st_size
        assert sidecar_size <= size_two

    def test_persist_failure_does_not_unpin_evicted_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_ENTRIES", 2)
        for stem in ("a", "b"):
            (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
            record_companion_mapping(tmp_path, f"{stem}.pdf", f"{stem}.md")
        oldest = load_companion_entries(tmp_path)["a.pdf"]
        assert oldest.id is not None
        assert companion_identity_path(tmp_path, oldest.id).exists()

        (tmp_path / "c.md").write_text("c", encoding="utf-8")

        def failing_replace(_src, _dst):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="No space left on device"):
            record_companion_mapping(tmp_path, "c.pdf", "c.md")

        assert load_companion_map(tmp_path) == {"a.pdf": "a.md", "b.pdf": "b.md"}
        assert companion_identity_path(tmp_path, oldest.id).exists()

    def test_trim_raises_when_one_entry_exceeds_byte_cap(self, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_BYTES", 10)
        mapping = {"huge.pdf": CompanionEntry(name="huge.md", size=1, mtime_ns=1, dev=1, ino=1, id="y" * 32)}
        with pytest.raises(ValueError, match="even after pruning"):
            companion_map_mod._trim_mapping_to_limits(mapping)

    @pytest.mark.parametrize("keep", [1, 8, 63])
    def test_trim_byte_cap_matches_oldest_first_policy_without_per_eviction_dumps(self, monkeypatch, keep):
        n = 64
        mapping = {f"{i:04d}.pdf": CompanionEntry(name=f"{i:04d}.md", size=i, mtime_ns=i, dev=1, ino=i, id="x" * 32) for i in range(n)}
        kept_map = dict(list(mapping.items())[-keep:])
        dropped_keys = [key for key, _ in list(mapping.items())[: n - keep]]
        # Cap at last-`keep` lives plus the sticky flag. Tombstones for the
        # dropped names may or may not fit; either way `keep+1` lives cannot.
        cap = companion_map_mod._serialized_map_bytes(kept_map, (), True)
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_BYTES", cap)
        monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_ENTRIES", n)

        calls = {"n": 0}
        real = companion_map_mod._serialized_map_bytes

        def counting(candidate, *args, **kwargs):
            calls["n"] += 1
            return real(candidate, *args, **kwargs)

        monkeypatch.setattr(companion_map_mod, "_serialized_map_bytes", counting)

        kept, dropped, tombstones, flag = companion_map_mod._trim_mapping_to_limits(mapping)
        expected_keys = [f"{i:04d}.pdf" for i in range(n - keep, n)]
        assert list(kept) == expected_keys
        assert [entry.name for entry in dropped] == [f"{i:04d}.md" for i in range(n - keep)]
        if flag:
            assert tombstones == []
        else:
            assert tombstones == dropped_keys
        assert real(kept, tombstones, flag) <= cap
        # Each candidate may dump once (tombstones fit) or twice (retry with sticky flag).
        # Full map + last-row fail-closed check + binary search over n-1 cut points,
        # plus a small slack for the sticky-flag retry on the accepted cut.
        assert calls["n"] <= 2 * (2 + math.ceil(math.log2(n - 1))) + 2


class TestEvictedOriginalsAreNotLegacy:
    """Pruning must not turn collision-renamed companions into stem guesses."""

    def _evict_pdf_mapping(self, tmp_path: Path, monkeypatch, mode: str) -> None:
        (tmp_path / "a.docx").write_bytes(b"docx")
        (tmp_path / "a.pdf").write_bytes(b"pdf")
        (tmp_path / "a.md").write_text("FROM DOCX", encoding="utf-8")
        (tmp_path / "a_1.md").write_text("FROM PDF", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.docx", "a.md")
        record_companion_mapping(tmp_path, "a.pdf", "a_1.md")
        if mode == "entries":
            monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_ENTRIES", 2)
        else:
            size_two = (tmp_path / COMPANION_MAP_FILENAME).stat().st_size
            monkeypatch.setattr(companion_map_mod, "MAX_COMPANION_MAP_BYTES", size_two)
        for stem in ("c", "d"):
            (tmp_path / f"{stem}.md").write_text(stem, encoding="utf-8")
            record_companion_mapping(tmp_path, f"{stem}.pdf", f"{stem}.md")
        state = load_companion_state(tmp_path)
        assert "a.pdf" not in state.companions
        assert state.blocks_legacy_fallback("a.pdf")

    @pytest.mark.parametrize("mode", ["entries", "bytes"])
    def test_lookup_does_not_choose_other_document_companion(self, tmp_path, monkeypatch, mode):
        self._evict_pdf_mapping(tmp_path, monkeypatch, mode)
        assert resolve_converted_markdown_path(tmp_path / "a.pdf") is None
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == "FROM DOCX"

    @pytest.mark.parametrize("mode", ["entries", "bytes"])
    def test_delete_preserves_other_document_companion(self, tmp_path, monkeypatch, mode):
        self._evict_pdf_mapping(tmp_path, monkeypatch, mode)
        delete_file_safe(tmp_path, "a.pdf", convertible_extensions={".pdf", ".docx"})
        assert not (tmp_path / "a.pdf").exists()
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == "FROM DOCX"

    def test_genuine_legacy_upload_still_uses_stem_fallback(self, tmp_path, monkeypatch):
        self._evict_pdf_mapping(tmp_path, monkeypatch, "entries")
        (tmp_path / "report.pdf").write_bytes(b"pdf")
        sibling = tmp_path / "report.md"
        sibling.write_text("# legacy\n", encoding="utf-8")
        assert resolve_converted_markdown_path(tmp_path / "report.pdf") == sibling

    def test_rerecord_clears_tombstone(self, tmp_path, monkeypatch):
        self._evict_pdf_mapping(tmp_path, monkeypatch, "entries")
        (tmp_path / "a_2.md").write_text("FROM PDF v2", encoding="utf-8")
        record_companion_mapping(tmp_path, "a.pdf", "a_2.md")
        state = load_companion_state(tmp_path)
        assert "a.pdf" not in state.evicted
        assert resolve_converted_markdown_path(tmp_path / "a.pdf") == tmp_path / "a_2.md"

    def test_sticky_flag_is_durable_and_blocks_stem_fallback(self, tmp_path):
        payload = {"version": 2, "companions": {}, "no_legacy_fallback": True}
        (tmp_path / COMPANION_MAP_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        (tmp_path / "a.pdf").write_bytes(b"pdf")
        (tmp_path / "a.md").write_text("FROM DOCX", encoding="utf-8")
        assert load_companion_state(tmp_path).no_legacy_fallback is True
        assert resolve_converted_markdown_path(tmp_path / "a.pdf") is None
        delete_file_safe(tmp_path, "a.pdf", convertible_extensions={".pdf"})
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == "FROM DOCX"


class TestReplacementCleansPreviousCompanion:
    def test_rerecord_unlinks_unmodified_previous_companion(self, tmp_path):
        (tmp_path / "report.md").write_text("# v1\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report.md")
        previous = load_companion_entries(tmp_path)["report.pdf"]
        (tmp_path / "report_1.md").write_text("# v2\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report_1.md")

        assert not (tmp_path / "report.md").exists()
        assert lookup_companion_mapping(tmp_path, "report.pdf") == "report_1.md"
        if previous.id is not None:
            assert not companion_identity_path(tmp_path, previous.id).exists()

    def test_rerecord_keeps_edited_previous_companion(self, tmp_path):
        companion = tmp_path / "report.md"
        companion.write_text("# v1\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report.md")
        companion.write_text("# v1\nedited in the sandbox\n", encoding="utf-8")
        (tmp_path / "report_1.md").write_text("# v2\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report_1.md")

        assert companion.read_text(encoding="utf-8") == "# v1\nedited in the sandbox\n"
        assert lookup_companion_mapping(tmp_path, "report.pdf") == "report_1.md"
        assert "report.md" not in mapped_companion_names(tmp_path)

    def test_rerecord_unlinks_unmodified_previous_companion_without_hardlink_pins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(companion_map_mod, "_pin_companion", lambda *args: None)
        (tmp_path / "report.md").write_text("# v1\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report.md")
        assert load_companion_entries(tmp_path)["report.pdf"].id is None

        (tmp_path / "report_1.md").write_text("# v2\n", encoding="utf-8")
        record_companion_mapping(tmp_path, "report.pdf", "report_1.md")

        assert not (tmp_path / "report.md").exists()
        assert lookup_companion_mapping(tmp_path, "report.pdf") == "report_1.md"


def _production_thread_uploads(root: Path, thread_name: str) -> Path:
    """Production layout: ``{thread}/user-data/uploads`` with pins beside user-data."""
    uploads = root / thread_name / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    return uploads


def _copy_user_data(source_uploads: Path, dest_root: Path, dest_name: str) -> tuple[Path, dict[str, CopiedFileIdentity]]:
    dest_user_data = dest_root / dest_name / "user-data"
    copied = copy_user_data_tree(source_uploads.parent, dest_user_data)
    return dest_user_data / "uploads", copied_upload_identities(copied)


class TestRebindClonedCompanionIdentities:
    def test_copying_user_data_alone_drops_converted_path(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# Report\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")

        dest, _copied_from = _copy_user_data(source, tmp_path, "dest")
        copied = load_companion_entries(dest)["report.pdf"]
        assert copied.id
        assert not companion_entry_matches(dest, copied)
        assert resolve_converted_markdown_path(dest / "report.pdf") is None

        # Copying the pin files independently still fails: they are new inodes.
        shutil.copytree(companion_identity_dir(source), companion_identity_dir(dest))
        still_copied = load_companion_entries(dest)["report.pdf"]
        assert not companion_entry_matches(dest, still_copied)
        assert resolve_converted_markdown_path(dest / "report.pdf") is None

    def test_rebind_pins_destination_copy_and_keeps_source(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# Report\n", encoding="utf-8")
        (source / "a.docx").write_bytes(b"docx")
        (source / "a.pdf").write_bytes(b"%PDF")
        (source / "a.md").write_text("# From DOCX\n", encoding="utf-8")
        (source / "a_1.md").write_text("# From PDF\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        record_companion_mapping(source, "a.docx", "a.md")
        record_companion_mapping(source, "a.pdf", "a_1.md")
        source_report = load_companion_entries(source)["report.pdf"]

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        dest_report = load_companion_entries(dest)["report.pdf"]
        dest_pdf = load_companion_entries(dest)["a.pdf"]
        assert dest_report.id
        assert dest_report.id != source_report.id
        assert companion_entry_matches(source, source_report)
        assert companion_entry_matches(dest, dest_report)
        dest_pin = companion_identity_path(dest, dest_report.id)
        dest_md = dest / "report.md"
        assert dest_pin.stat().st_ino == dest_md.stat().st_ino
        assert dest_md.stat().st_ino != (source / "report.md").stat().st_ino
        assert companion_identity_path(source, source_report.id).stat().st_ino == (source / "report.md").stat().st_ino
        assert resolve_converted_markdown_path(dest / "report.pdf") == dest / "report.md"
        assert resolve_converted_markdown_path(dest / "a.pdf") == dest / "a_1.md"
        assert mapped_companion_names(dest) == {"report.md", "a.md", "a_1.md"}
        assert dest_pdf.id != load_companion_entries(source)["a.pdf"].id

    def test_rebind_keeps_in_place_edit_and_rejects_replacement(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        edited = source / "edited.md"
        edited.write_text("# Keep\n", encoding="utf-8")
        (source / "edited.pdf").write_bytes(b"%PDF")
        record_companion_mapping(source, "edited.pdf", "edited.md")
        edited.write_text("# Keep\n\nedited in place\n", encoding="utf-8")
        assert companion_entry_matches(source, load_companion_entries(source)["edited.pdf"])

        stale = source / "stale.md"
        stale.write_text("# Original convert\n", encoding="utf-8")
        (source / "stale.pdf").write_bytes(b"%PDF")
        record_companion_mapping(source, "stale.pdf", "stale.md")
        stale.unlink()
        (source / "stale.md").write_text("# User notes\n", encoding="utf-8")
        assert not companion_entry_matches(source, load_companion_entries(source)["stale.pdf"])

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        dest_edited = load_companion_entries(dest)["edited.pdf"]
        source_edited = load_companion_entries(source)["edited.pdf"]
        assert dest_edited.size == source_edited.size
        assert dest_edited.mtime_ns == source_edited.mtime_ns
        assert dest_edited.size != (dest / "edited.md").stat().st_size
        assert lookup_companion_mapping(dest, "edited.pdf") == "edited.md"
        assert resolve_converted_markdown_path(dest / "edited.pdf") == dest / "edited.md"
        assert lookup_companion_mapping(dest, "stale.pdf") is None
        assert resolve_converted_markdown_path(dest / "stale.pdf") is None
        assert mapped_companion_names(dest) == {"edited.md"}
        assert "stale.pdf" not in load_companion_entries(dest)
        assert "stale.pdf" in load_companion_state(dest).evicted
        assert has_companion_entry(dest, "stale.pdf") is True

    def test_rebind_preserves_convert_fingerprint_so_rerecord_keeps_edits(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# v1\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        (source / "report.md").write_text("# v1\nedited in place\n", encoding="utf-8")

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        (dest / "report_1.md").write_text("# v2 convert\n", encoding="utf-8")
        record_companion_mapping(dest, "report.pdf", "report_1.md")
        assert (dest / "report.md").read_text(encoding="utf-8") == "# v1\nedited in place\n"
        assert lookup_companion_mapping(dest, "report.pdf") == "report_1.md"

        (source / "report_1.md").write_text("# v2 convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report_1.md")
        assert (source / "report.md").read_text(encoding="utf-8") == "# v1\nedited in place\n"

    def test_rebind_tombstones_metadata_preserving_replacement(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        companion = source / "report.md"
        companion.write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        preserved = tmp_path / "preserved.md"
        shutil.copy2(companion, preserved)
        companion.unlink()
        shutil.copy2(preserved, companion)
        source_entry = load_companion_entries(source)["report.pdf"]
        if source_entry.id is None and companion.stat().st_ino == source_entry.ino:
            pytest.skip("filesystem reused the inode and identity pin was unavailable")
        assert not companion_entry_matches(source, source_entry)

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        assert lookup_companion_mapping(dest, "report.pdf") is None
        assert "report.pdf" in load_companion_state(dest).evicted
        assert has_companion_entry(dest, "report.pdf") is True
        delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
        assert (dest / "report.md").read_text(encoding="utf-8") == "# convert\n"
        delete_file_safe(source, "report.pdf", convertible_extensions={".pdf"})
        assert companion.read_text(encoding="utf-8") == "# convert\n"

    def test_rebind_tombstones_when_source_rerecords_same_name_after_copy(self, tmp_path):
        """Copied notes must not inherit a newer same-name convert on the source."""
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        copied_id = load_companion_entries(source)["report.pdf"].id
        (source / "report.md").unlink()
        (source / "report.md").write_text("# independent notes\n", encoding="utf-8")
        dest, copied_from = _copy_user_data(source, tmp_path, "dest")

        (source / "report.md").unlink()
        (source / "report.md").write_text("# new convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        new_id = load_companion_entries(source)["report.pdf"].id
        if copied_id is None and new_id is None:
            pytest.skip("identity pins unavailable; generation tokens cannot differ")
        assert new_id != copied_id
        assert companion_entry_matches(source, load_companion_entries(source)["report.pdf"])

        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        assert lookup_companion_mapping(dest, "report.pdf") is None
        assert "report.pdf" in load_companion_state(dest).evicted
        assert (dest / "report.md").read_text(encoding="utf-8") == "# independent notes\n"
        delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
        assert (dest / "report.md").read_text(encoding="utf-8") == "# independent notes\n"

    def test_rebind_tombstones_when_dest_markdown_predates_copied_sidecar(self, tmp_path):
        """Same bytes after copy are not identity; dest notes keep their inode.

        copytree copies files one by one. Dest can receive the new sidecar after a
        source re-record while still holding an independent restore of the same text.
        """
        same_text = "# same bytes\n"
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        (source / "report.md").unlink()
        (source / "report.md").write_text(same_text, encoding="utf-8")
        dest, copied_from = _copy_user_data(source, tmp_path, "dest")

        (source / "report.md").unlink()
        (source / "report.md").write_text(same_text, encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        shutil.copy2(source / COMPANION_MAP_FILENAME, dest / COMPANION_MAP_FILENAME)
        dest_id = load_companion_entries(dest)["report.pdf"].id
        source_id = load_companion_entries(source)["report.pdf"].id
        assert dest_id == source_id
        assert (dest / "report.md").read_text(encoding="utf-8") == same_text
        notes_ino = (dest / "report.md").stat().st_ino
        source_ino = (source / "report.md").stat().st_ino
        assert notes_ino != source_ino

        rebind_cloned_companion_identities(source, dest, copied_from=copied_from)

        assert lookup_companion_mapping(dest, "report.pdf") is None
        assert "report.pdf" in load_companion_state(dest).evicted
        assert (dest / "report.md").read_text(encoding="utf-8") == same_text
        delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
        assert (dest / "report.md").read_text(encoding="utf-8") == same_text

    def test_rebind_tombstones_symlink_destination(self, tmp_path):
        if os.name == "nt":
            pytest.skip("symlink pin guard is POSIX")
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# Report\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        outside = tmp_path / "outside.md"
        outside.write_text("# not a companion\n", encoding="utf-8")
        (dest / "report.md").unlink()
        (dest / "report.md").symlink_to(outside)

        assert rebind_cloned_companion_identities(source, dest, copied_from=copied_from) is True
        assert "report.pdf" not in load_companion_entries(dest)
        assert "report.pdf" in load_companion_state(dest).evicted
        assert has_companion_entry(dest, "report.pdf") is True
        assert lookup_companion_mapping(dest, "report.pdf") is None
        assert resolve_converted_markdown_path(dest / "report.pdf") is None

    def test_rebind_without_copy_record_tombstones(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# Report\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        dest, _copied_from = _copy_user_data(source, tmp_path, "dest")

        rebind_cloned_companion_identities(source, dest, copied_from={})

        assert lookup_companion_mapping(dest, "report.pdf") is None
        assert "report.pdf" in load_companion_state(dest).evicted
        assert (dest / "report.md").read_text(encoding="utf-8") == "# Report\n"
        delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
        assert (dest / "report.md").read_text(encoding="utf-8") == "# Report\n"

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo is POSIX-only")
    def test_rebind_does_not_block_when_source_becomes_fifo(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# Report\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        dest, copied_from = _copy_user_data(source, tmp_path, "dest")

        (source / "report.md").unlink()
        os.mkfifo(source / "report.md")

        done = threading.Event()
        result: dict[str, bool] = {}

        def _run() -> None:
            result["ok"] = rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            done.set()

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        assert done.wait(timeout=2), "rebind blocked on source FIFO"
        assert result["ok"] is True
        assert (dest / "report.md").read_text(encoding="utf-8") == "# Report\n"

    def test_rebind_unpinned_unmodified_mapping_gets_dest_pin(self, tmp_path, monkeypatch):
        original_pin = companion_map_mod._pin_companion
        monkeypatch.setattr(companion_map_mod, "_pin_companion", lambda *_args, **_kwargs: None)
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        assert load_companion_entries(source)["report.pdf"].id is None
        monkeypatch.setattr(companion_map_mod, "_pin_companion", original_pin)

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            dest_entry = load_companion_entries(dest)["report.pdf"]
            assert dest_entry.id
            assert companion_entry_matches(dest, dest_entry)
            assert lookup_companion_mapping(dest, "report.pdf") == "report.md"
        finally:
            release_copied_identities(copied_from)

    def test_rebind_tombstones_when_copy_cannot_hold_source_identity(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            companion_map_mod.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EPERM, "Operation not permitted")),
        )
        monkeypatch.setattr(companion_map_mod, "_copy_fd_hold_limit", lambda: 0)
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            assert (dest / "report.md").read_text(encoding="utf-8") == "# convert\n"
            assert "report.md" not in copied_from
            rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            assert lookup_companion_mapping(dest, "report.pdf") is None
            assert "report.pdf" in load_companion_state(dest).evicted
            delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
            assert (dest / "report.md").read_text(encoding="utf-8") == "# convert\n"
        finally:
            release_copied_identities(copied_from)

    def test_rebind_rejects_identity_without_live_hold(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        (source / "report.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            stripped = {
                name: CopiedFileIdentity(
                    source_dev=identity.source_dev,
                    source_ino=identity.source_ino,
                    dest_dev=identity.dest_dev,
                    dest_ino=identity.dest_ino,
                )
                for name, identity in copied_from.items()
            }
            rebind_cloned_companion_identities(source, dest, copied_from=stripped)
            assert lookup_companion_mapping(dest, "report.pdf") is None
            assert "report.pdf" in load_companion_state(dest).evicted
            delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
            assert (dest / "report.md").read_text(encoding="utf-8") == "# convert\n"
        finally:
            release_copied_identities(copied_from)

    def test_rebind_does_not_revive_unpinned_stale_mapping(self, tmp_path, monkeypatch):
        original_pin = companion_map_mod._pin_companion
        monkeypatch.setattr(companion_map_mod, "_pin_companion", lambda *_args, **_kwargs: None)
        source = _production_thread_uploads(tmp_path, "source")
        (source / "report.pdf").write_bytes(b"%PDF")
        companion = source / "report.md"
        companion.write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "report.pdf", "report.md")
        source_entry = load_companion_entries(source)["report.pdf"]
        assert source_entry.id is None
        companion.write_text("# convert\nedited in place\n", encoding="utf-8")
        assert not companion_entry_matches(source, source_entry)
        monkeypatch.setattr(companion_map_mod, "_pin_companion", original_pin)

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            assert lookup_companion_mapping(dest, "report.pdf") is None
            assert "report.pdf" in load_companion_state(dest).evicted
            delete_file_safe(dest, "report.pdf", convertible_extensions={".pdf"})
            assert (dest / "report.md").read_text(encoding="utf-8") == "# convert\nedited in place\n"
        finally:
            release_copied_identities(copied_from)

    def test_rebind_keeps_mapping_when_user_data_root_has_same_basename(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "notes.pdf").write_bytes(b"%PDF")
        (source / "notes.md").write_text("# convert\n", encoding="utf-8")
        record_companion_mapping(source, "notes.pdf", "notes.md")
        (source.parent / "notes.md").write_text("# unrelated workspace notes\n", encoding="utf-8")

        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            assert copied_from["notes.md"].source_ino == (source / "notes.md").stat().st_ino
            rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            assert lookup_companion_mapping(dest, "notes.pdf") == "notes.md"
            assert companion_entry_matches(dest, load_companion_entries(dest)["notes.pdf"])
            assert resolve_converted_markdown_path(dest / "notes.pdf") == dest / "notes.md"
            assert (dest.parent / "notes.md").read_text(encoding="utf-8") == "# unrelated workspace notes\n"
        finally:
            release_copied_identities(copied_from)


class TestCopiedUploadIdentities:
    def test_uploads_path_wins_over_user_data_root_file(self):
        uploads = CopiedFileIdentity(source_dev=1, source_ino=2, dest_dev=3, dest_ino=4)
        root = CopiedFileIdentity(source_dev=5, source_ino=6, dest_dev=7, dest_ino=8)
        overwritten_if_root_wins = copied_upload_identities({"uploads/notes.md": uploads, "notes.md": root})
        assert overwritten_if_root_wins["notes.md"] is uploads
        uploads_last = copied_upload_identities({"notes.md": root, "uploads/notes.md": uploads})
        assert uploads_last["notes.md"] is uploads

    def test_bare_uploads_root_copy_still_maps_basename(self):
        identity = CopiedFileIdentity(source_dev=1, source_ino=2, dest_dev=3, dest_ino=4)
        assert copied_upload_identities({"notes.md": identity})["notes.md"] is identity


class TestCopyUserDataTree:
    def test_copy_opens_source_nonblocking_when_available(self, tmp_path, monkeypatch):
        if not hasattr(os, "O_NONBLOCK"):
            pytest.skip("O_NONBLOCK not available on this platform")
        source = _production_thread_uploads(tmp_path, "source")
        (source / "notes.md").write_text("hello\n", encoding="utf-8")
        captured: list[int] = []
        real_open = os.open

        def _open(path, flags, *args):
            captured.append(flags)
            return real_open(path, flags, *args)

        monkeypatch.setattr(companion_map_mod.os, "open", _open)
        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            assert copied
            assert any(flags & os.O_NONBLOCK for flags in captured)
        finally:
            release_copied_identities(copied)

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo is POSIX-only")
    def test_copy_skips_fifo_without_blocking(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        (source / "keep.md").write_text("keep\n", encoding="utf-8")
        os.mkfifo(source / "stuck.md")
        dest_root = tmp_path / "dest" / "user-data"
        done = threading.Event()
        copied: dict[str, object] = {}

        def _run() -> None:
            copied["ids"] = copy_user_data_tree(source.parent, dest_root)
            done.set()

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        assert done.wait(timeout=2), "copy blocked on source FIFO"
        dest_uploads = dest_root / "uploads"
        assert (dest_uploads / "keep.md").read_text(encoding="utf-8") == "keep\n"
        assert not (dest_uploads / "stuck.md").exists()
        identities = copied_upload_identities(copied["ids"])
        assert "keep.md" in identities
        assert "stuck.md" not in identities
        release_copied_identities(copied["ids"])

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_copy_preserves_executable_and_sandbox_writable_modes(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        workspace = source.parent / "workspace"
        workspace.mkdir()
        script = workspace / "run.sh"
        script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        script.chmod(0o755)
        upload = source / "notes.txt"
        upload.write_text("editable\n", encoding="utf-8")
        upload.chmod(0o666)

        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            dest_script = dest_root / "workspace" / "run.sh"
            dest_upload = dest_root / "uploads" / "notes.txt"
            assert dest_script.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"
            assert dest_upload.read_text(encoding="utf-8") == "editable\n"
            assert stat.S_IMODE(dest_script.stat().st_mode) == 0o755
            assert stat.S_IMODE(dest_upload.stat().st_mode) == 0o666
        finally:
            release_copied_identities(copied)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_copy_preserves_directory_modes(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        workspace = source.parent / "workspace"
        nested = workspace / "scripts"
        nested.mkdir(parents=True)
        (nested / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        source.parent.chmod(0o777)
        workspace.chmod(0o777)
        nested.chmod(0o777)

        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            assert stat.S_IMODE(dest_root.stat().st_mode) == 0o777
            assert stat.S_IMODE((dest_root / "workspace").stat().st_mode) == 0o777
            assert stat.S_IMODE((dest_root / "workspace" / "scripts").stat().st_mode) == 0o777
        finally:
            release_copied_identities(copied)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_copy_keeps_contents_of_readonly_directories(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        workspace = source.parent / "workspace"
        readonly = workspace / "readonly"
        readonly.mkdir(parents=True)
        (readonly / "data.txt").write_text("keep me\n", encoding="utf-8")
        readonly.chmod(0o555)
        source.parent.chmod(0o555)

        dest_root = tmp_path / "dest" / "user-data"
        copied = None
        try:
            copied = copy_user_data_tree(source.parent, dest_root)
            dest_readonly = dest_root / "workspace" / "readonly"
            assert (dest_readonly / "data.txt").read_text(encoding="utf-8") == "keep me\n"
            assert stat.S_IMODE(dest_readonly.stat().st_mode) == 0o555
            assert stat.S_IMODE(dest_root.stat().st_mode) == 0o555
        finally:
            for path in (readonly, source.parent, dest_root / "workspace" / "readonly", dest_root):
                try:
                    os.chmod(path, stat.S_IMODE(path.stat().st_mode) | 0o200)
                except OSError:
                    pass
            if copied is not None:
                release_copied_identities(copied)

    def test_copy_caps_held_source_fds_when_hardlink_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            companion_map_mod.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EPERM, "Operation not permitted")),
        )
        monkeypatch.setattr(companion_map_mod, "_copy_fd_hold_limit", lambda: 2)
        source = _production_thread_uploads(tmp_path, "source")
        for index in range(20):
            (source / f"file-{index:02d}.txt").write_text(f"{index}\n", encoding="utf-8")
        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            dest_uploads = dest_root / "uploads"
            assert len(list(dest_uploads.glob("file-*.txt"))) == 20
            held_fds = sum(1 for identity in copied.values() if identity._hold is not None and identity._hold.fd >= 0)
            assert held_fds <= 2
            file_identities = [key for key in copied if key.rsplit("/", 1)[-1].startswith("file-")]
            assert len(file_identities) == held_fds
            assert all((dest_uploads / f"file-{index:02d}.txt").read_text(encoding="utf-8") == f"{index}\n" for index in range(20))
        finally:
            release_copied_identities(copied)

    @pytest.mark.skipif(os.name != "posix", reason="RLIMIT_NOFILE is POSIX")
    def test_copy_does_not_exhaust_fd_table_when_hardlink_unavailable(self, tmp_path, monkeypatch):
        resource = pytest.importorskip("resource")
        if not hasattr(resource, "RLIMIT_NOFILE"):
            pytest.skip("RLIMIT_NOFILE unavailable")
        monkeypatch.setattr(
            companion_map_mod.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EPERM, "Operation not permitted")),
        )
        open_count = companion_map_mod._open_fd_count()
        if open_count is not None and open_count > 48:
            pytest.skip("too many fds already open to simulate a 64-fd ceiling")
        source = _production_thread_uploads(tmp_path, "source")
        for index in range(100):
            (source / f"file-{index:03d}.txt").write_text(f"{index}\n", encoding="utf-8")
        dest_root = tmp_path / "dest" / "user-data"
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        copied = None
        try:
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard if hard >= 64 or hard < 0 else 64))
            except (ValueError, OverflowError, OSError):
                pytest.skip("cannot lower RLIMIT_NOFILE on this platform")
            copied = copy_user_data_tree(source.parent, dest_root)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        try:
            dest_uploads = dest_root / "uploads"
            assert len(list(dest_uploads.glob("file-*.txt"))) == 100
            held_fds = sum(1 for identity in copied.values() if identity._hold is not None and identity._hold.fd >= 0)
            assert held_fds <= companion_map_mod._MAX_HELD_COPY_FDS
        finally:
            if copied is not None:
                release_copied_identities(copied)

    def test_copy_retries_short_writes_until_complete(self, tmp_path, monkeypatch):
        source = _production_thread_uploads(tmp_path, "source")
        payload = b"abcdefghijklmnop"
        (source / "blob.bin").write_bytes(payload)
        real_write = os.write

        def short_write(fd, data):
            if len(data) > 1:
                return real_write(fd, data[:1])
            return real_write(fd, data)

        monkeypatch.setattr(companion_map_mod.os, "write", short_write)
        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            assert (dest_root / "uploads" / "blob.bin").read_bytes() == payload
            assert "uploads/blob.bin" in copied
        finally:
            release_copied_identities(copied)

    def test_copy_unlinks_partial_file_when_write_fails(self, tmp_path, monkeypatch):
        source = _production_thread_uploads(tmp_path, "source")
        payload = b"x" * 4096
        (source / "blob.bin").write_bytes(payload)
        real_write = os.write
        budget = 1024

        def limited_write(fd, data):
            nonlocal budget
            if budget <= 0:
                raise OSError(errno.EFBIG, "File too large")
            n = min(len(data), budget, 100)
            budget -= n
            return real_write(fd, data[:n])

        monkeypatch.setattr(companion_map_mod.os, "write", limited_write)
        dest_root = tmp_path / "dest" / "user-data"
        with pytest.raises(OSError):
            copy_user_data_tree(source.parent, dest_root)
        assert not (dest_root / "uploads" / "blob.bin").exists()

    @pytest.mark.skipif(os.name != "posix", reason="RLIMIT_FSIZE is POSIX")
    def test_copy_does_not_succeed_when_rlimit_fsize_truncates(self, tmp_path):
        resource = pytest.importorskip("resource")
        if not hasattr(resource, "RLIMIT_FSIZE"):
            pytest.skip("RLIMIT_FSIZE unavailable")
        import signal

        previous_xfsz = None
        if hasattr(signal, "SIGXFSZ"):
            previous_xfsz = signal.getsignal(signal.SIGXFSZ)
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)

        source = _production_thread_uploads(tmp_path, "source")
        payload = b"x" * 4096
        (source / "blob.bin").write_bytes(payload)
        dest_root = tmp_path / "dest" / "user-data"
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        try:
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, (1024, hard))
            except (ValueError, OverflowError, OSError):
                pytest.skip("cannot lower RLIMIT_FSIZE on this platform")
            try:
                copied = copy_user_data_tree(source.parent, dest_root)
            except OSError:
                assert not (dest_root / "uploads" / "blob.bin").exists()
                return
            release_copied_identities(copied)
            dest = dest_root / "uploads" / "blob.bin"
            if dest.exists() and dest.stat().st_size == 4096:
                pytest.skip("RLIMIT_FSIZE did not constrain writes on this platform")
            pytest.fail("copy succeeded with a truncated destination file")
        finally:
            resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
            if previous_xfsz is not None:
                signal.signal(signal.SIGXFSZ, previous_xfsz)

    def test_same_length_edit_during_copy_does_not_register_identity(self, tmp_path, monkeypatch):
        source = _production_thread_uploads(tmp_path, "source")
        original = b"convert-v1-text\n"
        edited = b"convert-v2-text\n"
        assert len(original) == len(edited)
        (source / "report.pdf").write_bytes(b"%PDF")
        companion = source / "report.md"
        companion.write_bytes(original)
        record_companion_mapping(source, "report.pdf", "report.md")
        companion_ino = companion.stat().st_ino
        real_read = os.read
        edited_once = False

        def read_and_edit(fd, n):
            nonlocal edited_once
            if not edited_once:
                try:
                    opened = os.fstat(fd)
                except OSError:
                    opened = None
                if opened is not None and opened.st_ino == companion_ino:
                    edited_once = True
                    with open(companion, "r+b") as handle:
                        handle.write(edited)
            return real_read(fd, n)

        monkeypatch.setattr(companion_map_mod.os, "read", read_and_edit)
        dest, copied_from = _copy_user_data(source, tmp_path, "dest")
        try:
            assert edited_once
            assert "report.md" not in copied_from
            dest_md = dest / "report.md"
            assert dest_md.read_bytes() == edited
            rebind_cloned_companion_identities(source, dest, copied_from=copied_from)
            assert lookup_companion_mapping(dest, "report.pdf") is None
            (dest / "report_1.md").write_text("# v2 convert\n", encoding="utf-8")
            record_companion_mapping(dest, "report.pdf", "report_1.md")
            assert dest_md.read_bytes() == edited
        finally:
            release_copied_identities(copied_from)

    def test_copy_holds_source_inode_after_unlink(self, tmp_path):
        source = _production_thread_uploads(tmp_path, "source")
        target = source / "notes.md"
        target.write_text("hello\n", encoding="utf-8")
        dest_root = tmp_path / "dest" / "user-data"
        copied = copy_user_data_tree(source.parent, dest_root)
        try:
            identity = copied["uploads/notes.md"]
            hold = identity._hold
            assert hold is not None
            target.unlink()
            if hold.path is not None:
                held = os.lstat(hold.path)
            else:
                assert hold.fd >= 0
                held = os.fstat(hold.fd)
            assert held.st_dev == identity.source_dev
            assert held.st_ino == identity.source_ino
            assert stat.S_ISREG(held.st_mode)
        finally:
            release_copied_identities(copied)


class TestDeleteSidecarCleanupIsAdvisory:
    def test_delete_succeeds_when_forget_raises(self, tmp_path, monkeypatch):
        target = tmp_path / "notes.txt"
        target.write_text("keep-me-deleted", encoding="utf-8")

        def boom(*_args, **_kwargs):
            raise OSError("sidecar exploded")

        monkeypatch.setattr("deerflow.uploads.manager.forget_companion_mapping", boom)
        result = delete_file_safe(tmp_path, "notes.txt")
        assert result["success"] is True
        assert not target.exists()
