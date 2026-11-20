"""Staged-write cleanup at the two persistence writers must not replace the outcome.

Each writer stages a temporary file and discards it in a ``finally`` that also
runs when the publish itself failed. Before this change a failing discard
replaced that error with its own.
"""

from __future__ import annotations

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


def _is_staged(path: Path) -> bool:
    return path.suffix == ".tmp"


def test_managed_subagent_write_keeps_the_replace_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    from deerflow.persistence.managed_subagents import file as store_module
    from deerflow.persistence.managed_subagents.base import ManagedSubagentDefinition

    definition = ManagedSubagentDefinition(
        name="planner",
        description="plans",
        system_prompt="plan things",
    )
    target = tmp_path / "planner.json"

    def _failing_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(store_module.os, "replace", _failing_replace)
    _fail_unlink_on(monkeypatch, _is_staged, real_unlink)

    with pytest.raises(OSError, match="replace failed"):
        store_module.FileManagedSubagentStore._atomic_write(target, definition)

    assert not target.exists()


def test_agent_store_write_keeps_the_publish_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    from deerflow.persistence.agents.file import FileAgentStore

    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()

    def _failing_replace(self, target, *args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", _failing_replace)
    _fail_unlink_on(monkeypatch, _is_staged, real_unlink)

    with pytest.raises(OSError, match="replace failed"):
        FileAgentStore._write(agent_dir, {"name": "planner"}, "# SOUL")


def test_managed_subagent_write_removes_the_temp_when_the_write_fails(tmp_path, monkeypatch):
    """A failure before the publish still has to discard the staged file."""
    from deerflow.persistence.managed_subagents import file as store_module
    from deerflow.persistence.managed_subagents.base import ManagedSubagentDefinition

    definition = ManagedSubagentDefinition(
        name="planner",
        description="plans",
        system_prompt="plan things",
    )

    def _failing_fsync(*_args, **_kwargs):
        raise OSError("fsync failed")

    monkeypatch.setattr(store_module.os, "fsync", _failing_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        store_module.FileManagedSubagentStore._atomic_write(tmp_path / "planner.json", definition)

    assert [p.name for p in tmp_path.iterdir()] == []


def test_agent_store_write_removes_the_temp_when_the_write_fails(tmp_path, monkeypatch):
    """The staging helper must register its path before writing the payload."""
    from deerflow.persistence.agents import file as store_module

    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()

    real_named_tempfile = store_module.tempfile.NamedTemporaryFile

    class _FailingWrite:
        """A real staged file whose payload write fails."""

        def __init__(self, *args, **kwargs):
            self._inner = real_named_tempfile(*args, **kwargs)
            self.name = self._inner.name

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc_info):
            return self._inner.__exit__(*exc_info)

        def write(self, *_args, **_kwargs):
            raise OSError("write failed")

    monkeypatch.setattr(store_module.tempfile, "NamedTemporaryFile", _FailingWrite)

    with pytest.raises(OSError, match="write failed"):
        store_module.FileAgentStore._write(agent_dir, {"name": "planner"}, "# SOUL")

    assert [p.name for p in agent_dir.iterdir()] == []
