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
