# SPDX-License-Identifier: MIT
"""Extension writers keep the original publish error when temporary cleanup fails."""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path

import pytest

from deerflow.extensions.manager import _FileSnapshot, _write_plugins_block


@pytest.mark.parametrize("primary_type", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_snapshot_restore_preserves_publish_error_when_cleanup_fails(tmp_path, monkeypatch, caplog, primary_type, failure):
    target = tmp_path / "pyproject.toml"
    target.write_bytes(b"mutated-before-rollback")
    if os.name != "nt":
        target.chmod(0o640)
    mode = stat.S_IMODE(target.stat().st_mode)
    snapshot = _FileSnapshot(target, b"original-bytes", 0o644 if os.name != "nt" else None)

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
        # The staged path is known only once replace runs; patch unlink lazily.
        def unlink(path, *args, **kwargs):
            if staged and path == staged[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
        with pytest.raises(primary_type) as raised:
            snapshot.restore()

    assert raised.value is primary
    assert target.read_bytes() == b"mutated-before-rollback"
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert len(staged) == 1
    if failure == "none":
        assert not staged[0].exists()
        assert "Failed to remove temporary output file" not in caplog.text
    else:
        assert staged[0].read_bytes() == b"original-bytes"
        if failure == "unlink":
            assert "Failed to remove temporary output file" in caplog.text
            assert str(staged[0]) in caplog.text
            assert "temporary unlink failed" in caplog.text
    real_unlink(staged[0], missing_ok=True)


@pytest.mark.parametrize("primary_type", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_plugins_rewrite_preserves_publish_error_when_cleanup_fails(tmp_path, monkeypatch, caplog, primary_type, failure):
    target = tmp_path / "config.yaml"
    original = "kept: true\n"
    target.write_text(original, encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o640)
    mode = stat.S_IMODE(target.stat().st_mode)

    primary = primary_type("publish failed")
    real_replace = os.replace
    real_unlink = Path.unlink
    staged: list[Path] = []

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

    with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
        with pytest.raises(primary_type) as raised:
            _write_plugins_block(target, original, [{"name": "demo", "enabled": True}])

    assert raised.value is primary
    assert target.read_text(encoding="utf-8") == original
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert len(staged) == 1
    if failure == "none":
        assert not staged[0].exists()
        assert "Failed to remove temporary output file" not in caplog.text
    else:
        assert "name: demo" in staged[0].read_text(encoding="utf-8")
        if failure == "unlink":
            assert "Failed to remove temporary output file" in caplog.text
            assert str(staged[0]) in caplog.text
    real_unlink(staged[0], missing_ok=True)


def test_plugins_rewrite_success_keeps_neighbor_bytes_and_mode(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_bytes(b"other: 1\n")
    if os.name != "nt":
        target.chmod(0o640)
    mode = stat.S_IMODE(target.stat().st_mode)

    _write_plugins_block(target, "other: 1\n", [{"name": "demo", "enabled": True}])

    text = target.read_text(encoding="utf-8")
    assert text.startswith("other: 1\n")
    assert "name: demo" in text
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert list(tmp_path.glob(".config.yaml.*")) == []


@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("unlink_fails", [False, True])
def test_snapshot_fdopen_failure_closes_descriptor_without_masking(tmp_path, monkeypatch, caplog, close_fails, unlink_fails):
    from deerflow.extensions import manager as extension_manager

    target = tmp_path / "pyproject.toml"
    target.write_bytes(b"kept")
    snapshot = _FileSnapshot(target, b"original-bytes", None)
    primary = OSError("fdopen failed")
    allocated: list[tuple[int, Path]] = []
    closes: list[int] = []
    real_mkstemp = tempfile.mkstemp
    real_fdopen = os.fdopen
    real_close = os.close
    real_unlink = Path.unlink

    def mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        allocated.append((fd, Path(name)))
        return fd, name

    def fdopen(fd, *args, **kwargs):
        if allocated and fd == allocated[-1][0]:
            raise primary
        return real_fdopen(fd, *args, **kwargs)

    def close(fd):
        closes.append(fd)
        real_close(fd)
        if close_fails and allocated and fd == allocated[-1][0]:
            raise OSError("descriptor cleanup failed")

    def unlink(path, *args, **kwargs):
        if unlink_fails and allocated and path == allocated[-1][1]:
            raise OSError("temporary unlink failed")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(extension_manager.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(Path, "unlink", unlink)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(OSError) as raised:
                snapshot.restore()
        assert raised.value is primary
        fd, temporary = allocated[0]
        assert fd in closes
        assert target.read_bytes() == b"kept"
        if unlink_fails:
            assert temporary.exists()
            assert "Failed to remove temporary output file" in caplog.text
        else:
            assert not temporary.exists()
        if close_fails:
            assert "Failed to close temporary output descriptor" in caplog.text
            assert str(temporary) in caplog.text
        else:
            assert "Failed to close temporary output descriptor" not in caplog.text
    finally:
        for fd, temporary in allocated:
            real_unlink(temporary, missing_ok=True)


@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_plugins_short_write_still_removes_the_temporary(tmp_path, monkeypatch, caplog, failure):
    from deerflow.extensions import manager as extension_manager

    target = tmp_path / "config.yaml"
    original = "kept: true\n"
    target.write_text(original, encoding="utf-8")
    primary = OSError("disk full")
    created: list[Path] = []
    real_named = tempfile.NamedTemporaryFile
    real_unlink = Path.unlink

    def tracking(*args, **kwargs):
        handle = real_named(*args, **kwargs)
        created.append(Path(handle.name))

        def fail_write(_data):
            raise primary

        handle.write = fail_write
        return handle

    monkeypatch.setattr(extension_manager.tempfile, "NamedTemporaryFile", tracking)
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if created and path == created[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(OSError) as raised:
                _write_plugins_block(target, original, [{"name": "demo", "enabled": True}])
        assert raised.value is primary
        assert target.read_text(encoding="utf-8") == original
        assert len(created) == 1
        if failure == "none":
            assert not created[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert created[0].exists()
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(created[0]) in caplog.text
    finally:
        for path in created:
            real_unlink(path, missing_ok=True)


@pytest.mark.parametrize("failure", ["unlink", "logging"])
def test_snapshot_delete_branch_cleanup_failure_does_not_skip_later_restores(tmp_path, monkeypatch, caplog, failure):
    created = tmp_path / "uv.lock"
    kept = tmp_path / "pyproject.toml"
    kept.write_bytes(b"mutated")
    created.write_bytes(b"created-by-install")
    missing = _FileSnapshot(created, None, None)
    later = _FileSnapshot(kept, b"original", 0o644 if os.name != "nt" else None)
    operation_error = RuntimeError("install failed")

    real_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == created:
            raise OSError("temporary unlink failed")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    def _rollback():
        try:
            raise operation_error
        except RuntimeError:
            for snapshot in (missing, later):
                snapshot.restore()
            raise

    with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
        with pytest.raises(RuntimeError) as raised:
            _rollback()

    assert raised.value is operation_error
    assert created.read_bytes() == b"created-by-install"
    assert kept.read_bytes() == b"original"
    if failure == "unlink":
        assert "Failed to remove temporary output file" in caplog.text
        assert str(created) in caplog.text
        assert "temporary unlink failed" in caplog.text
    if failure == "logging":
        assert str(raised.value) == "install failed"
        assert "log handler failed" not in str(raised.value)
