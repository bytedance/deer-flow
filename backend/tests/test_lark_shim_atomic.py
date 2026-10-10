# SPDX-License-Identifier: MIT
"""The Lark CLI runtime files must never be observable half written."""

from __future__ import annotations

import json
import os

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
    marker = tmp_path / ".deerflow-lark-cli-runtime.json"
    before = marker.read_text(encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        install_shim(str(tmp_path), version="2.0.0")

    # A truncating open would have emptied the marker before failing, leaving the
    # gateway with unparseable JSON; publishing through a temporary file cannot.
    assert marker.read_text(encoding="utf-8") == before


def test_atomic_helper_keeps_the_previous_file_when_publish_fails(tmp_path, monkeypatch):
    from deerflow.integrations.lark_broker import _write_text_atomically

    target = tmp_path / "runtime.json"
    target.write_text('{"version": "1.0.0"}', encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        _write_text_atomically(str(target), '{"version": "2.0.0"}')

    assert target.read_text(encoding="utf-8") == '{"version": "1.0.0"}'
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
