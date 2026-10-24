"""Both atomic write paths honor one retry budget and preserve error identity."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.integrations import lark_cli
from deerflow.persistence.agents import file as agent_file
from deerflow.utils import atomic_write


@pytest.mark.parametrize("caller", ["agent", "lark"])
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_atomic_write_callers_share_retry_policy(monkeypatch, tmp_path, caller, error_type):
    # A policy adjustment must change both the loop bound and the last-attempt
    # check in both callers, rather than falling through without an exception.
    monkeypatch.setattr(atomic_write, "_ATOMIC_RETRY_ATTEMPTS", 3, raising=False)
    monkeypatch.setattr(atomic_write, "_ATOMIC_RETRY_BACKOFF_SECONDS", 0.01, raising=False)
    error = error_type("Windows atomic operation denied")
    error.winerror = 32
    calls = []
    delays = []
    source, target = tmp_path / "staging", tmp_path / "target"

    def denied(path, destination):
        calls.append((path, destination))
        raise error

    if caller == "agent":
        monkeypatch.setattr(agent_file, "sys", SimpleNamespace(platform="win32"))
        monkeypatch.setattr(agent_file, "time", SimpleNamespace(sleep=delays.append))
        monkeypatch.setattr(Path, "replace", denied)
        operation = agent_file._replace_staged_file
    else:
        monkeypatch.setattr(lark_cli, "os", SimpleNamespace(name="nt"))
        monkeypatch.setattr(lark_cli, "time", SimpleNamespace(sleep=delays.append))
        monkeypatch.setattr(Path, "rename", denied)
        operation = lark_cli._rename_sandbox_runtime

    with pytest.raises(error_type) as caught:
        operation(source, target)

    assert caught.value is error
    assert calls == [(source, target)] * 3
    assert delays == [0.01, 0.02]
