# SPDX-License-Identifier: MIT
"""Atomic publication replaces a read-only destination on every platform.

POSIX rename ignores the target's permission bits, so a read-only file is
replaced like any other. Windows refuses to replace a read-only file *and* to
unlink a sibling that inherited that mode, which turned a failed capture into a
permanent hidden temporary. The publisher therefore defers the preserved mode
until after the rename there, and clears the destination attribute first.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from deerflow.utils.atomic_write import publish_bytes_atomically


def _write_read_only(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    os.chmod(path, 0o444)


def test_publish_replaces_a_read_only_destination_and_keeps_its_mode(tmp_path):
    target = tmp_path / "capture.png"
    _write_read_only(target, b"previous")
    try:
        publish_bytes_atomically(target, b"replacement")

        assert target.read_bytes() == b"replacement"
        assert not stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE
        assert [entry.name for entry in tmp_path.iterdir()] == [target.name]
    finally:
        os.chmod(target, 0o600)


def test_failed_publish_over_a_read_only_destination_leaves_no_sibling(tmp_path, monkeypatch):
    target = tmp_path / "capture.png"
    _write_read_only(target, b"previous")

    def replace(source, destination):
        raise OSError("publication failed")

    monkeypatch.setattr(os, "replace", replace)
    try:
        with pytest.raises(OSError):
            publish_bytes_atomically(target, b"replacement")

        assert [entry.name for entry in tmp_path.iterdir()] == [target.name]
        assert target.read_bytes() == b"previous"
        assert not stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE
    finally:
        os.chmod(target, 0o600)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_read_only_symlink_target_keeps_its_mode(tmp_path, monkeypatch):
    """The attribute is cleared on the destination, never through a symlink."""
    from deerflow.utils import atomic_write

    link = tmp_path / "capture.png"
    real = tmp_path / "store.bin"
    _write_read_only(real, b"previous")
    link.symlink_to(real)
    monkeypatch.setattr(atomic_write.os, "name", "nt")
    try:
        publish_bytes_atomically(link, b"replacement")

        assert real.read_bytes() == b"previous"
        assert not stat.S_IMODE(real.stat().st_mode) & stat.S_IWRITE
    finally:
        os.chmod(real, 0o600)
