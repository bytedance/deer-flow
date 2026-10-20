# SPDX-License-Identifier: MIT
"""Extension writers keep the original publish error when temporary cleanup fails."""

from __future__ import annotations

import logging
import os
import stat
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
