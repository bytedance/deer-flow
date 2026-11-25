"""Startup diagnostics for the volume used by managed subagent definitions."""

from __future__ import annotations

import errno
import logging
from pathlib import Path

import pytest

from app.gateway import deps
from deerflow.config.paths import Paths


@pytest.fixture
def paths(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    return paths


def test_probe_uses_the_managed_volume_and_leaves_existing_definitions_untouched(paths, monkeypatch, caplog):
    root = paths.managed_subagents_dir
    root.mkdir()
    existing = root / "researcher.json"
    existing.write_bytes(b'{"name":"researcher"}\n')
    original_link = deps.os.link
    claims = []

    def observed_link(source, destination):
        source, destination = Path(source), Path(destination)
        assert source.parent.parent == root
        assert destination.parent == source.parent
        original_link(source, destination)
        assert source.stat().st_ino == destination.stat().st_ino
        claims.append((source, destination))

    monkeypatch.setattr(deps.os, "link", observed_link)
    with caplog.at_level(logging.WARNING):
        deps._probe_managed_subagent_file_storage()

    assert len(claims) == 1
    assert list(root.iterdir()) == [existing]
    assert existing.read_bytes() == b'{"name":"researcher"}\n'
    assert not caplog.records


@pytest.mark.parametrize("error", [OSError(errno.EOPNOTSUPP, "hard links unavailable"), PermissionError(errno.EPERM, "hard links denied")])
def test_probe_warns_on_link_failure_and_cleans_up(paths, monkeypatch, caplog, error):
    attempted = []

    def failed_link(source, destination):
        attempted.append((source, destination))
        raise error

    monkeypatch.setattr(deps.os, "link", failed_link)
    with caplog.at_level(logging.WARNING):
        deps._probe_managed_subagent_file_storage()

    assert len(attempted) == 1
    assert list(paths.managed_subagents_dir.iterdir()) == []
    assert "hard-link probe failed" in caplog.text
    assert str(paths.managed_subagents_dir) in caplog.text
    assert "creation may fail" in caplog.text
    assert "agent_storage.backend='db'" in caplog.text


def test_probe_warns_if_the_directory_cannot_be_created(paths, monkeypatch, caplog):
    root = paths.managed_subagents_dir
    original_mkdir = Path.mkdir
    attempted = []

    def denied_mkdir(path, *args, **kwargs):
        if path == root:
            attempted.append(path)
            raise PermissionError(errno.EACCES, "volume is read-only")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied_mkdir)
    with caplog.at_level(logging.WARNING):
        deps._probe_managed_subagent_file_storage()

    assert attempted == [root]
    assert "hard-link probe failed" in caplog.text
    assert "volume is read-only" in caplog.text
    assert not root.exists()
