# SPDX-License-Identifier: MIT
"""A failed extension install must not corrupt the files it rolls back."""

from __future__ import annotations

import os
import stat

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


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o600])
def test_restore_preserves_the_captured_permissions(tmp_path, mode):
    target = tmp_path / "config.yaml"
    target.write_text("original\n", encoding="utf-8")
    target.chmod(mode)
    snapshot = _FileSnapshot.capture(target)

    target.write_text("changed\n", encoding="utf-8")
    target.chmod(0o660)
    snapshot.restore()

    assert target.read_text(encoding="utf-8") == "original\n"
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert list(tmp_path.glob(".*tmp")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_restore_recreates_a_deleted_file_with_its_captured_permissions(tmp_path):
    target = tmp_path / "uv.lock"
    target.write_text("original\n", encoding="utf-8")
    target.chmod(0o644)
    snapshot = _FileSnapshot.capture(target)
    target.unlink()

    snapshot.restore()

    assert target.read_text(encoding="utf-8") == "original\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_restore_keeps_the_current_file_when_setting_permissions_fails(tmp_path, monkeypatch):
    target = tmp_path / "config.yaml"
    target.write_text("original\n", encoding="utf-8")
    target.chmod(0o640)
    snapshot = _FileSnapshot.capture(target)
    target.write_text("changed\n", encoding="utf-8")
    target.chmod(0o660)

    def _boom(*args, **kwargs):
        raise OSError("cannot set permissions")

    monkeypatch.setattr(os, "chmod", _boom)

    with pytest.raises(OSError, match="cannot set permissions"):
        snapshot.restore()

    assert target.read_text(encoding="utf-8") == "changed\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o660
    assert list(tmp_path.glob(".*tmp")) == []
