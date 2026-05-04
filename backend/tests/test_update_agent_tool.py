"""Tests for update_agent tool — partial updates, atomic writes, and validation.

Resolves issue #2616: a custom agent must be able to persist updates to its
own SOUL.md / config.yaml from inside a normal chat (not only from bootstrap).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from deerflow.config.agents_config import AgentConfig
from deerflow.tools.builtins.update_agent_tool import update_agent


class _DummyRuntime(SimpleNamespace):
    context: dict
    tool_call_id: str


def _runtime(agent_name: str | None = "test-agent", tool_call_id: str = "call_1") -> _DummyRuntime:
    return _DummyRuntime(context={"agent_name": agent_name} if agent_name is not None else {}, tool_call_id=tool_call_id)


def _make_paths_mock(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.base_dir = tmp_path
    paths.agent_dir = lambda name: tmp_path / "agents" / name
    return paths


def _seed_agent(tmp_path: Path, name: str = "test-agent", *, description: str = "old desc", soul: str = "old soul", skills: list[str] | None = None) -> Path:
    """Create a baseline agent dir with config.yaml and SOUL.md for tests to mutate."""
    agent_dir = tmp_path / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    cfg: dict = {"name": name, "description": description}
    if skills is not None:
        cfg["skills"] = skills
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return agent_dir


@pytest.fixture()
def patched_paths(tmp_path: Path):
    paths_mock = _make_paths_mock(tmp_path)
    with patch("deerflow.tools.builtins.update_agent_tool.get_paths", return_value=paths_mock):
        # load_agent_config also calls get_paths(); patch the same target it uses.
        with patch("deerflow.config.agents_config.get_paths", return_value=paths_mock):
            yield paths_mock


# --- Validation tests ---


def test_update_agent_rejects_missing_agent_name(patched_paths):
    result = update_agent.func(runtime=_runtime(agent_name=None), soul="new soul")

    msg = result.update["messages"][0]
    assert "only available inside a custom agent's chat" in msg.content


def test_update_agent_rejects_invalid_agent_name(patched_paths):
    result = update_agent.func(runtime=_runtime(agent_name="../../etc/passwd"), soul="x")

    msg = result.update["messages"][0]
    assert "Invalid agent name" in msg.content


def test_update_agent_rejects_unknown_agent(tmp_path, patched_paths):
    result = update_agent.func(runtime=_runtime(agent_name="ghost"), soul="x")

    msg = result.update["messages"][0]
    assert "does not exist" in msg.content
    assert not (tmp_path / "agents" / "ghost").exists()


def test_update_agent_requires_at_least_one_field(tmp_path, patched_paths):
    _seed_agent(tmp_path)

    result = update_agent.func(runtime=_runtime())

    msg = result.update["messages"][0]
    assert "No fields provided" in msg.content


# --- Partial update tests ---


def test_update_agent_updates_soul_only(tmp_path, patched_paths):
    agent_dir = _seed_agent(tmp_path, description="keep me", soul="old soul")

    result = update_agent.func(runtime=_runtime(), soul="brand new soul")

    assert (agent_dir / "SOUL.md").read_text() == "brand new soul"
    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["description"] == "keep me", "description must be preserved"
    assert "soul" in result.update["messages"][0].content


def test_update_agent_updates_description_only(tmp_path, patched_paths):
    agent_dir = _seed_agent(tmp_path, description="old desc", soul="keep this soul")

    result = update_agent.func(runtime=_runtime(), description="new desc")

    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["description"] == "new desc"
    assert (agent_dir / "SOUL.md").read_text() == "keep this soul", "SOUL.md must be preserved"
    assert "description" in result.update["messages"][0].content


def test_update_agent_skills_empty_list_disables_all(tmp_path, patched_paths):
    agent_dir = _seed_agent(tmp_path, skills=["a", "b"])

    result = update_agent.func(runtime=_runtime(), skills=[])

    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["skills"] == [], "empty list must persist as empty list (not be omitted)"
    assert "skills" in result.update["messages"][0].content


def test_update_agent_skills_omitted_keeps_existing(tmp_path, patched_paths):
    agent_dir = _seed_agent(tmp_path, skills=["alpha", "beta"])

    update_agent.func(runtime=_runtime(), description="bumped")

    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["skills"] == ["alpha", "beta"], "omitting skills must preserve the existing whitelist"


def test_update_agent_no_op_when_values_match_existing(tmp_path, patched_paths):
    _seed_agent(tmp_path, description="same")

    result = update_agent.func(runtime=_runtime(), description="same")

    assert "No changes applied" in result.update["messages"][0].content


# --- Atomicity tests ---


def test_update_agent_failure_preserves_existing_files(tmp_path, patched_paths):
    agent_dir = _seed_agent(tmp_path, soul="original soul")

    real_replace = Path.replace

    def _explode(self, target):
        if str(target).endswith("SOUL.md"):
            raise OSError("disk full")
        return real_replace(self, target)

    with patch.object(Path, "replace", _explode):
        result = update_agent.func(runtime=_runtime(), soul="poisoned content")

    assert (agent_dir / "SOUL.md").read_text() == "original soul", "atomic write must not corrupt existing SOUL.md"
    assert "Error" in result.update["messages"][0].content
    leftover_tmps = list(agent_dir.glob("*.tmp"))
    assert leftover_tmps == [], "temp files must be cleaned up on failure"


# --- Loader passthrough sanity check ---


def test_update_agent_uses_load_agent_config(tmp_path, patched_paths):
    """Ensure update_agent reads the existing config through load_agent_config so
    extra YAML keys (e.g. legacy fields) round-trip correctly via AgentConfig."""
    _seed_agent(tmp_path, description="legacy")

    fake_cfg = AgentConfig(name="test-agent", description="legacy", skills=["s1"], tool_groups=["g1"], model="m1")
    with patch("deerflow.tools.builtins.update_agent_tool.load_agent_config", return_value=fake_cfg):
        update_agent.func(runtime=_runtime(), description="bumped")

    cfg = yaml.safe_load((tmp_path / "agents" / "test-agent" / "config.yaml").read_text())
    assert cfg["description"] == "bumped"
    assert cfg["skills"] == ["s1"]
    assert cfg["tool_groups"] == ["g1"]
    assert cfg["model"] == "m1"
