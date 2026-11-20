# SPDX-License-Identifier: MIT
"""The Lark CLI runtime binary must never be observable half written."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from deerflow.integrations.lark_cli import _publish_bytes_atomically


def test_publishes_the_content_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "lark-cli"

    _publish_bytes_atomically(target, b"#!/bin/sh\necho hi\n")

    assert target.read_bytes() == b"#!/bin/sh\necho hi\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_publish_keeps_the_previous_binary(tmp_path, monkeypatch):
    target = tmp_path / "lark-cli"
    target.write_bytes(b"old runtime")

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        _publish_bytes_atomically(target, b"new runtime")

    assert target.read_bytes() == b"old runtime"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("primary_type", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_publish_preserves_original_error_when_cleanup_fails(tmp_path, monkeypatch, caplog, primary_type, failure):
    target = tmp_path / "lark-cli"
    target.write_bytes(b"old runtime")
    primary = primary_type("publish failed")
    staged: list[Path] = []
    real_replace = os.replace
    real_unlink = Path.unlink

    def replace(source, destination):
        staged.append(Path(source))
        if Path(destination) == target:
            raise primary
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace)
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if staged and path == staged[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(primary_type) as raised:
                _publish_bytes_atomically(target, b"new runtime")

        assert raised.value is primary
        assert "temporary unlink failed" not in str(raised.value)
        assert target.read_bytes() == b"old runtime"
        assert len(staged) == 1
        if failure == "none":
            assert not staged[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert staged[0].read_bytes() == b"new runtime"
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(staged[0]) in caplog.text
                assert "temporary unlink failed" in caplog.text
    finally:
        if staged:
            real_unlink(staged[0], missing_ok=True)


def test_success_replaces_bytes_and_keeps_the_temporary_mode(tmp_path):
    target = tmp_path / "linux-amd64" / "lark-cli"
    target.parent.mkdir()
    target.write_bytes(b"old runtime")
    if os.name != "nt":
        target.chmod(0o755)

    _publish_bytes_atomically(target, b"new runtime")

    assert target.read_bytes() == b"new runtime"
    if os.name != "nt":
        # mkstemp publishes mode 0o600; callers chmod the final path afterward.
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [path for path in target.parent.iterdir() if path.suffix == ".tmp"] == []


def test_truncating_write_would_have_destroyed_it(tmp_path):
    """Control: the previous implementation loses the binary in the same failure."""
    target = tmp_path / "lark-cli"
    target.write_bytes(b"old runtime")

    try:
        with open(target, "wb") as handle:
            handle.write(b"new ")
            raise OSError("read-only filesystem")
    except OSError:
        pass

    assert target.read_bytes() != b"old runtime"


def test_the_install_path_preserves_previous_binary_on_publish_failure(tmp_path, monkeypatch):
    import io
    import tarfile

    from deerflow.integrations.lark_cli import _extract_lark_cli_runtime_binary

    buf = io.BytesIO()
    payload = b"#!/bin/sh\necho new-runtime\n"
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="bin/lark-cli")
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))
    archive_bytes = buf.getvalue()

    destination = tmp_path / "runtime" / "lark-cli"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old runtime")

    def fail_replace(*args):
        raise OSError("replace failed mid-install")

    with monkeypatch.context() as patches:
        patches.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="replace failed mid-install"):
            _extract_lark_cli_runtime_binary(archive_bytes, destination)

    assert destination.read_bytes() == b"old runtime"
    assert list(destination.parent.glob("*.tmp")) == []

    _extract_lark_cli_runtime_binary(archive_bytes, destination)
    assert destination.read_bytes() == payload
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o755
