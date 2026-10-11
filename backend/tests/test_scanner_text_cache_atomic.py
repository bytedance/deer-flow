# SPDX-License-Identifier: MIT
"""A cached preview must never be served half written."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def scanner():
    # Import after the autouse fixtures initialize the runtime package.
    from deerflow.workspace_changes import scanner

    return scanner


def test_publishes_the_text_and_leaves_no_temp_file(tmp_path, scanner):
    target = tmp_path / "entry"

    scanner._publish_text_atomically(target, "decoded body")

    assert target.read_text(encoding="utf-8") == "decoded body"
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_publish_keeps_the_previous_entry(tmp_path, monkeypatch, scanner):
    target = tmp_path / "entry"
    target.write_text("previous body", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        scanner._publish_text_atomically(target, "new body")

    assert target.read_text(encoding="utf-8") == "previous body"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("publish_error", [OSError("publish failed"), KeyboardInterrupt("publish interrupted")], ids=["io-error", "interrupt"])
def test_cleanup_failure_preserves_the_publish_error(tmp_path, monkeypatch, scanner, publish_error):
    target = tmp_path / "entry"
    target.write_text("previous body", encoding="utf-8")

    def _fail_publish(*args, **kwargs):
        raise publish_error

    def _fail_cleanup(*args, **kwargs):
        raise PermissionError("cleanup failed")

    with monkeypatch.context() as patches:
        patches.setattr(os, "replace", _fail_publish)
        patches.setattr(Path, "unlink", _fail_cleanup)

        with pytest.raises(type(publish_error)) as caught:
            scanner._publish_text_atomically(target, "new body")

    assert caught.value is publish_error
    assert target.read_text(encoding="utf-8") == "previous body"


def test_truncating_write_would_have_destroyed_it(tmp_path):
    """Control: the previous implementation loses the entry in the same failure."""
    target = tmp_path / "entry"
    target.write_text("previous body", encoding="utf-8")

    try:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("new ")
            raise OSError("disk full")
    except OSError:
        pass

    assert target.read_text(encoding="utf-8") != "previous body"


def test_cache_text_file_returns_a_complete_entry(tmp_path, scanner):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    virtual_path = "/workspace/report.csv"

    returned = scanner._cache_text_file("a,b\n1,2\n", virtual_path, cache_dir)

    assert Path(returned).read_text(encoding="utf-8") == "a,b\n1,2\n"
    # The key is derived from the virtual path, so a partial entry would be served
    # as the file's content on every later read.
    assert Path(returned).name == hashlib.sha256(virtual_path.encode()).hexdigest()


def test_cache_entry_survives_a_failed_publish(tmp_path, monkeypatch, scanner):
    """The real entry point: a failed publish must not damage the cached entry."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    virtual_path = "/workspace/report.csv"
    name = hashlib.sha256(virtual_path.encode()).hexdigest()
    entry = cache_dir / name
    entry.write_text("previous body", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        scanner._cache_text_file("new body", virtual_path, cache_dir)

    # A truncating write would have emptied the entry before failing, and the
    # caller serves this path as the file's content on every later read.
    assert entry.read_text(encoding="utf-8") == "previous body"
