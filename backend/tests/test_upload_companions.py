"""Source-version validation for converted upload ownership records."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.uploads.companions import (
    companion_names,
    invalidate_overwritten_upload,
    register_companion,
    resolve_companion,
    unregister_companion,
)
from deerflow.utils.file_outline import extract_outline_for_file


@pytest.fixture
def converted_upload(tmp_path):
    uploads = tmp_path / "thread" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    original = uploads / "report.pdf"
    markdown = uploads / "report.md"
    original.write_bytes(b"%PDF ORIGINAL A")
    markdown.write_text("# Original A\n", encoding="utf-8")
    register_companion(original, markdown)
    return original, markdown


def test_unchanged_source_keeps_companion_after_read(converted_upload):
    original, markdown = converted_upload
    assert original.read_bytes() == b"%PDF ORIGINAL A"
    assert resolve_companion(original) == markdown
    assert companion_names(original.parent) == {markdown.name}
    assert extract_outline_for_file(original)[0] == [{"title": "Original A", "line": 1}]


def test_companion_record_accepts_uppercase_markdown_suffix(tmp_path):
    uploads = tmp_path / "thread" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    original = uploads / "report.pdf"
    markdown = uploads / "report.MD"
    original.write_bytes(b"%PDF ORIGINAL A")
    markdown.write_text("# Uppercase suffix\n", encoding="utf-8")

    register_companion(original, markdown)

    assert resolve_companion(original) == markdown
    assert companion_names(original.parent) == {markdown.name}
    assert extract_outline_for_file(original)[0] == [{"title": "Uppercase suffix", "line": 1}]


@pytest.mark.parametrize("writer", ["in_place", "sandbox"])
def test_same_size_rewrite_rejects_stale_outline(converted_upload, writer):
    original, markdown = converted_upload
    before = original.stat()
    if writer == "in_place":
        original.write_text("%PDF REPLACED B", encoding="utf-8")
    else:
        sandbox = LocalSandbox("repro", [PathMapping("/mnt/user-data", str(original.parent.parent))])
        sandbox.write_file("/mnt/user-data/uploads/report.pdf", "%PDF REPLACED B")
    # Force a distinct modification time even on coarse-resolution filesystems.
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    after = original.stat()
    assert (before.st_dev, before.st_size) == (after.st_dev, after.st_size)
    if writer == "sandbox" and sys.platform in {"darwin", "linux"}:
        assert before.st_ino != after.st_ino
    else:
        assert before.st_ino == after.st_ino

    assert resolve_companion(original) is None
    assert companion_names(original.parent) == set()
    assert extract_outline_for_file(original) == ([], [])
    assert markdown.read_text(encoding="utf-8") == "# Original A\n"


@pytest.mark.parametrize("timestamp", ["st_mtime_ns", "st_ctime_ns"])
def test_each_source_timestamp_invalidates_companion(converted_upload, monkeypatch, timestamp, caplog):
    original, _ = converted_upload
    real_stat = Path.stat
    before = original.stat()

    def changed_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == original:
            fields = {name: getattr(before, name) for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            fields[timestamp] += 2_000_000_000
            return SimpleNamespace(**fields)
        return result

    # Model mtime-only updates (e.g. Windows creation-time ctime) and ctime-only
    # updates (e.g. POSIX writes followed by restoring the old mtime).
    monkeypatch.setattr(Path, "stat", changed_stat)
    with caplog.at_level("DEBUG", logger="deerflow.uploads.companions"):
        assert resolve_companion(original) is None
    assert "source identity or version timestamps do not match" in caplog.text


def test_same_size_markdown_edit_invalidates_companion_on_windows(converted_upload, monkeypatch, caplog):
    original, markdown = converted_upload
    before = markdown.stat()
    real_stat = Path.stat

    def changed_markdown_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == markdown:
            fields = {name: getattr(before, name) for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            fields["st_mtime_ns"] += 2_000_000_000
            return SimpleNamespace(**fields)
        return result

    monkeypatch.setattr(Path, "stat", changed_markdown_stat)
    with caplog.at_level("DEBUG", logger="deerflow.uploads.companions"):
        assert resolve_companion(original) is None
    assert "Markdown identity or version timestamp does not match" in caplog.text
    assert "legacy Markdown identity" not in caplog.text


def test_legacy_source_record_requires_reregistration(converted_upload, caplog):
    original, markdown = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    data["source_identity"] = data["source_identity"][:3]
    record.write_text(json.dumps(data), encoding="utf-8")
    legacy = record.read_bytes()

    with caplog.at_level("DEBUG", logger="deerflow.uploads.companions"):
        assert resolve_companion(original) is None
    assert "legacy source identity lacks version timestamps" in caplog.text
    assert extract_outline_for_file(original) == ([], [])
    assert record.read_bytes() == legacy  # Do not bless stale content on read.

    register_companion(original, markdown)
    assert resolve_companion(original) == markdown


def test_legacy_markdown_record_requires_reregistration(converted_upload, caplog):
    original, markdown = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    # The old four-field format retained ctime but did not record mtime.
    data["markdown_identity"] = data["markdown_identity"][:3] + data["markdown_identity"][4:]
    record.write_text(json.dumps(data), encoding="utf-8")
    legacy = record.read_bytes()

    with caplog.at_level("DEBUG", logger="deerflow.uploads.companions"):
        assert resolve_companion(original) is None
    assert "legacy Markdown identity lacks modification timestamp; re-register companion" in caplog.text
    assert "Markdown identity or version timestamp does not match" not in caplog.text
    assert companion_names(original.parent) == set()
    assert extract_outline_for_file(original) == ([], [])
    assert record.read_bytes() == legacy  # Do not bless stale content on read.

    register_companion(original, markdown)
    assert resolve_companion(original) == markdown
    assert extract_outline_for_file(original)[0] == [{"title": "Original A", "line": 1}]


def test_new_conversion_restores_outline_after_source_edit(converted_upload):
    original, markdown = converted_upload
    before = original.stat()
    original.write_bytes(b"%PDF REPLACED B")
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    markdown.write_text("# Replaced B\n", encoding="utf-8")
    register_companion(original, markdown)

    assert resolve_companion(original) == markdown
    assert extract_outline_for_file(original)[0] == [{"title": "Replaced B", "line": 1}]


def _fail_record_unlink(monkeypatch):
    """Make deleting an ownership record fail the way a held handle does."""
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if self.suffix == ".json" and self.parent.name == "upload-companions":
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_unregister_tolerates_a_record_that_cannot_be_removed(converted_upload, monkeypatch, caplog):
    """Removal runs after the caller's outcome is decided, so it cannot raise."""
    original, _ = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    _fail_record_unlink(monkeypatch)

    with caplog.at_level("WARNING", logger="deerflow.uploads.companions"):
        unregister_companion(original)

    assert "Failed to remove upload companion record" in caplog.text
    assert record.exists()


def test_overwrite_invalidation_tolerates_a_record_that_cannot_be_removed(converted_upload, monkeypatch, caplog):
    """The embedded upload path publishes first, so this must not raise either."""
    original, _ = converted_upload
    _fail_record_unlink(monkeypatch)

    with caplog.at_level("WARNING", logger="deerflow.uploads.companions"):
        invalidate_overwritten_upload(original)

    assert "Failed to remove upload companion record" in caplog.text


def test_record_removal_survives_a_broken_log_handler(converted_upload, monkeypatch):
    """Diagnostics are best-effort too: a raising handler cannot fail the caller."""
    from deerflow.uploads import companions as companions_module

    original, _ = converted_upload
    _fail_record_unlink(monkeypatch)

    def broken_warning(*_args, **_kwargs):
        raise RuntimeError("synthetic logging handler failure")

    monkeypatch.setattr(companions_module.logger, "warning", broken_warning)

    unregister_companion(original)
