"""Markdown-version regression tests for converted upload companions (#7339).

On NTFS ``st_ctime_ns`` is the *creation* time, so an equal-size in-place edit
of the converted Markdown changes ``st_mtime_ns`` only. The ownership record
therefore carries the Markdown's ``st_mtime_ns`` and rejects both edited files
and legacy records that lack the field.
"""

from __future__ import annotations

import json
import os

import pytest

from deerflow.uploads.companions import (
    companion_names,
    register_companion,
    resolve_companion,
)


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


def _bump_mtime_ns(path, delta=2_000_000_000):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + delta))


def test_equal_size_markdown_edit_invalidates_companion(converted_upload):
    """The #7339 Windows scenario: same byte length, mtime moves, ctime does not."""
    original, markdown = converted_upload
    before = markdown.stat()
    assert len("# Original A\n".encode("utf-8")) == len("# Original B\n".encode("utf-8"))

    markdown.write_text("# Original B\n", encoding="utf-8")
    _bump_mtime_ns(markdown)
    after = markdown.stat()

    # The edit matches the reported NTFS behavior: same size, same ctime.
    assert before.st_size == after.st_size
    assert before.st_ctime_ns == after.st_ctime_ns
    assert before.st_mtime_ns != after.st_mtime_ns

    assert resolve_companion(original) is None
    assert companion_names(original.parent) == set()


def test_unequal_size_markdown_edit_still_invalidates(converted_upload):
    original, markdown = converted_upload
    markdown.write_text("# A much longer replacement body\n", encoding="utf-8")
    _bump_mtime_ns(markdown)

    assert resolve_companion(original) is None
    assert companion_names(original.parent) == set()


def test_untouched_markdown_keeps_companion(converted_upload):
    original, markdown = converted_upload
    assert resolve_companion(original) == markdown
    assert companion_names(original.parent) == {markdown.name}


def test_legacy_four_field_markdown_record_is_rejected(converted_upload, caplog):
    """Records written before the mtime field cannot prove an edit did not happen."""
    original, markdown = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    assert len(data["markdown_identity"]) == 5
    data["markdown_identity"] = data["markdown_identity"][:4]
    record.write_text(json.dumps(data), encoding="utf-8")

    with caplog.at_level("DEBUG", logger="deerflow.uploads.companions"):
        assert resolve_companion(original) is None
    assert "legacy Markdown identity lacks the modification timestamp" in caplog.text
    # Do not bless stale content on read.
    assert json.loads(record.read_text(encoding="utf-8"))["markdown_identity"] == data["markdown_identity"]

    # A fresh conversion re-establishes a valid 5-field association.
    register_companion(original, markdown)
    assert resolve_companion(original) == markdown


def test_markdown_identity_uses_current_field_order(converted_upload):
    """The new record stores [dev, ino, size, mtime_ns, ctime_ns] for the Markdown."""
    original, _ = converted_upload
    record = next((original.parent.parent.parent / "upload-companions").glob("*.json"))
    data = json.loads(record.read_text(encoding="utf-8"))
    markdown_stat = (original.parent / data["markdown"]).stat(follow_symlinks=False)
    assert data["markdown_identity"] == [
        markdown_stat.st_dev,
        markdown_stat.st_ino,
        markdown_stat.st_size,
        markdown_stat.st_mtime_ns,
        markdown_stat.st_ctime_ns,
    ]
