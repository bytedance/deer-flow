# SPDX-License-Identifier: MIT
"""A failed extension install must not corrupt the files it rolls back."""

from __future__ import annotations

import os

import pytest

from deerflow.extensions.manager import _FileSnapshot


def test_restore_keeps_the_previous_content_when_the_publish_fails(tmp_path, monkeypatch):
    target = tmp_path / "pyproject.toml"
    target.write_text("original\n", encoding="utf-8")
    snapshot = _FileSnapshot.capture(target)

    # The install failed, so the file was rewritten; now the rollback runs.
    target.write_text("half written by the failed install", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("device full")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        snapshot.restore()

    # write_bytes would have truncated the file before failing, taking the
    # checkout with it; publishing through a temporary file cannot.
    assert target.read_text(encoding="utf-8") == "half written by the failed install"


def test_restore_still_replaces_the_file(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("original\n", encoding="utf-8")
    snapshot = _FileSnapshot.capture(target)

    target.write_text("changed\n", encoding="utf-8")
    snapshot.restore()

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".*tmp")) == []


def test_restore_removes_a_file_that_did_not_exist(tmp_path):
    target = tmp_path / "uv.lock"
    snapshot = _FileSnapshot.capture(target)
    target.write_text("created by the failed install\n", encoding="utf-8")

    snapshot.restore()

    assert not target.exists()
