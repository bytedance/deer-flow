"""Source-version validation for converted upload ownership records."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.uploads.companions import companion_names, register_companion, resolve_companion
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


def test_same_size_sandbox_rewrite_rejects_stale_outline(converted_upload):
    original, markdown = converted_upload
    before = original.stat()
    sandbox = LocalSandbox("repro", [PathMapping("/mnt/user-data", str(original.parent.parent))])
    sandbox.write_file("/mnt/user-data/uploads/report.pdf", "%PDF REPLACED B")
    # Force a distinct modification time even on coarse-resolution filesystems.
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    after = original.stat()
    assert (before.st_dev, before.st_ino, before.st_size) == (after.st_dev, after.st_ino, after.st_size)

    assert resolve_companion(original) is None
    assert companion_names(original.parent) == set()
    assert extract_outline_for_file(original) == ([], [])
    assert markdown.read_text(encoding="utf-8") == "# Original A\n"


@pytest.mark.parametrize("timestamp", ["st_mtime_ns", "st_ctime_ns"])
def test_each_source_timestamp_invalidates_companion(converted_upload, monkeypatch, timestamp):
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
    assert resolve_companion(original) is None


def test_legacy_source_record_requires_reregistration(converted_upload):
    original, markdown = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    data["source_identity"] = data["source_identity"][:3]
    record.write_text(json.dumps(data), encoding="utf-8")
    legacy = record.read_bytes()

    assert resolve_companion(original) is None
    assert extract_outline_for_file(original) == ([], [])
    assert record.read_bytes() == legacy  # Do not bless stale content on read.

    register_companion(original, markdown)
    assert resolve_companion(original) == markdown


def test_new_conversion_restores_outline_after_source_edit(converted_upload):
    original, markdown = converted_upload
    before = original.stat()
    original.write_bytes(b"%PDF REPLACED B")
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    markdown.write_text("# Replaced B\n", encoding="utf-8")
    register_companion(original, markdown)

    assert resolve_companion(original) == markdown
    assert extract_outline_for_file(original)[0] == [{"title": "Replaced B", "line": 1}]
