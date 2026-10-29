"""Staged-temp cleanup in the artifact and Lark writers must keep the real outcome.

Both writers publish through a same-directory temporary and discard it on exit.
A failing discard used to replace the error the caller needed — the artifact
editor returned a cleanup ``OSError`` instead of the failed write, and the Lark
flow-state writer did the same.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def real_unlink():
    return Path.unlink


def _fail_unlink_on(monkeypatch, predicate, real_unlink):
    """Make ``Path.unlink`` raise for the paths a test owns."""

    def unlink(self, *args, **kwargs):
        if predicate(self):
            raise PermissionError("temporary unlink failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_artifact_edit_keeps_the_publish_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    from app.gateway.routers import artifacts

    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")
    file_stat = os.stat(target)

    def _failing_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(artifacts.os, "replace", _failing_replace)
    _fail_unlink_on(monkeypatch, lambda path: path.name.startswith(".") and path.suffix == "", real_unlink)

    with pytest.raises(OSError, match="replace failed"):
        artifacts._replace_artifact_atomically(target, b"replacement", file_stat)

    assert target.read_text(encoding="utf-8") == "original"


def test_artifact_edit_success_is_quiet(tmp_path, caplog):
    """The published path must not warn: its temp name is already gone."""
    from app.gateway.routers import artifacts

    target = tmp_path / "note.txt"
    target.write_text("original", encoding="utf-8")
    file_stat = os.stat(target)
    caplog.clear()

    with caplog.at_level("WARNING", logger="deerflow.utils.atomic_write"):
        artifacts._replace_artifact_atomically(target, b"replacement", file_stat)

    assert target.read_bytes() == b"replacement"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(artifacts._ARTIFACT_EDIT_TEMP_PREFIX)] == []
    assert caplog.text == ""


def test_lark_flow_state_write_keeps_the_write_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    from deerflow.integrations import lark_cli

    target = tmp_path / "flow-state.json"

    def _failing_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(lark_cli.os, "replace", _failing_replace)
    _fail_unlink_on(monkeypatch, lambda path: path.name.startswith(".flow-state.json"), real_unlink)

    with pytest.raises(OSError, match="replace failed"):
        lark_cli._write_json_file_atomic(target, {"state": "pending"})

    assert not target.exists()


def test_lark_flow_state_write_still_succeeds(monkeypatch, tmp_path):
    """The success path keeps its behaviour: payload written, no temp left."""
    from deerflow.integrations import lark_cli

    target = tmp_path / "flow-state.json"
    lark_cli._write_json_file_atomic(target, {"state": "pending"})

    assert target.read_text(encoding="utf-8") == '{"state": "pending"}\n'
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".flow-state")] == []
