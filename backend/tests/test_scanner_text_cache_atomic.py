# SPDX-License-Identifier: MIT
"""A cached preview must never be served half written."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deerflow.workspace_changes.scanner import _cache_text_file, _publish_text_atomically


def test_publishes_the_text_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "entry"

    _publish_text_atomically(target, "decoded body")

    assert target.read_text(encoding="utf-8") == "decoded body"
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_publish_keeps_the_previous_entry(tmp_path, monkeypatch):
    target = tmp_path / "entry"
    target.write_text("previous body", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        _publish_text_atomically(target, "new body")

    assert target.read_text(encoding="utf-8") == "previous body"
    assert list(tmp_path.glob("*.tmp")) == []


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


def test_cache_text_file_returns_a_complete_entry(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    virtual_path = "/workspace/report.csv"

    returned = _cache_text_file("a,b\n1,2\n", virtual_path, cache_dir)

    assert Path(returned).read_text(encoding="utf-8") == "a,b\n1,2\n"
    # The key is derived from the virtual path, so a partial entry would be served
    # as the file's content on every later read.
    assert Path(returned).name == __import__("hashlib").sha256(virtual_path.encode()).hexdigest()
