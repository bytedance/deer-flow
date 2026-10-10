# SPDX-License-Identifier: MIT
"""The Lark CLI runtime files must never be observable half written."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from deerflow.integrations.lark_broker import install_shim


def test_install_shim_publishes_executable_files(tmp_path):
    launcher = install_shim(str(tmp_path), version="1.2.3")

    assert os.access(launcher, os.X_OK)
    marker = tmp_path / ".deerflow-lark-cli-runtime.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["version"] == "1.2.3"
    assert [p.name for p in (tmp_path / "bin").glob("*.tmp")] == []


def test_a_failed_publish_leaves_the_previous_runtime_intact(tmp_path, monkeypatch):
    install_shim(str(tmp_path), version="1.0.0")
    shim = tmp_path / "bin" / "lark-cli-shim.py"
    before = shim.read_text(encoding="utf-8")
    assert before

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        install_shim(str(tmp_path), version="2.0.0")

    # A truncating open would have emptied the shim before failing, and the
    # sandbox then execs that fragment; publishing through a temporary file
    # cannot, so the previous runtime stays usable.
    assert shim.read_text(encoding="utf-8") == before


def test_atomic_helper_keeps_the_previous_file_when_publish_fails(tmp_path, monkeypatch):
    from deerflow.integrations.lark_broker import _write_text_atomically

    target = tmp_path / "runtime.json"
    target.write_text('{"version": "1.0.0"}', encoding="utf-8")
    target.chmod(0o640)
    previous_mode = stat.S_IMODE(target.stat().st_mode)

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        _write_text_atomically(str(target), '{"version": "2.0.0"}', mode=0o644)

    assert target.read_text(encoding="utf-8") == '{"version": "1.0.0"}'
    assert stat.S_IMODE(target.stat().st_mode) == previous_mode
    assert list(tmp_path.glob("*.tmp")) == []


def test_truncating_open_would_have_destroyed_it(tmp_path):
    """Control: the previous implementation loses the content in the same failure."""
    target = tmp_path / "runtime.json"
    target.write_text('{"version": "1.0.0"}', encoding="utf-8")

    try:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write('{"version": ')
            raise OSError("read-only filesystem")
    except OSError:
        pass

    assert target.read_text(encoding="utf-8") != '{"version": "1.0.0"}'


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits")
def test_runtime_permissions_are_final_when_each_file_is_published(tmp_path, monkeypatch):
    published = {}
    replace = os.replace

    def observe_publish(source, target):
        published[Path(target).name] = stat.S_IMODE(Path(source).stat().st_mode)
        replace(source, target)

    monkeypatch.setattr(os, "replace", observe_publish)

    install_shim(str(tmp_path), version="1.2.3")

    assert published == {"lark-cli-shim.py": 0o755, "lark-cli": 0o755, ".deerflow-lark-cli-runtime.json": 0o644}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits")
@pytest.mark.parametrize("filename,mode", [("lark-cli-shim.py", 0o755), ("lark-cli", 0o755), (".deerflow-lark-cli-runtime.json", 0o644)])
def test_interruption_after_publish_leaves_complete_usable_file(tmp_path, monkeypatch, filename, mode):
    install_shim(str(tmp_path), version="1.0.0")
    target = tmp_path / filename if filename.startswith(".") else tmp_path / "bin" / filename
    target.chmod(mode)
    previous_content = target.read_text(encoding="utf-8")
    replace = os.replace

    def interrupt_after_publish(source, destination):
        replace(source, destination)
        if Path(destination) == target:
            raise KeyboardInterrupt("interrupted immediately after publish")

    monkeypatch.setattr(os, "replace", interrupt_after_publish)

    with pytest.raises(KeyboardInterrupt, match="immediately after publish"):
        install_shim(str(tmp_path), version="2.0.0")

    assert stat.S_IMODE(target.stat().st_mode) == mode
    if filename.startswith("."):
        assert json.loads(target.read_text(encoding="utf-8")) == {"version": "2.0.0", "kind": "shim"}
    else:
        assert target.read_text(encoding="utf-8") == previous_content
        assert os.access(target, os.X_OK)
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permission bits")
def test_permission_failure_preserves_previous_runtime(tmp_path, monkeypatch):
    install_shim(str(tmp_path), version="1.0.0")
    files = [tmp_path / "bin" / "lark-cli-shim.py", tmp_path / "bin" / "lark-cli", tmp_path / ".deerflow-lark-cli-runtime.json"]
    previous = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in files}

    def fail_chmod(*args, **kwargs):
        raise OSError("permission change failed")

    monkeypatch.setattr(os, "chmod", fail_chmod)

    with pytest.raises(OSError, match="permission change failed"):
        install_shim(str(tmp_path), version="2.0.0")

    assert {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in files} == previous
    assert list(tmp_path.rglob("*.tmp")) == []
