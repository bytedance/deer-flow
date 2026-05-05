"""Tests for update_agent tool — partial updates, atomic writes, and validation.

Resolves issue #2616: a custom agent must be able to persist updates to its
own SOUL.md / config.yaml from inside a normal chat (not only from bootstrap).

The tool writes per-user (``{base_dir}/users/{user_id}/agents/{name}/``) so
that one user's update cannot mutate another user's agent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from deerflow.config.agents_config import AgentConfig
from deerflow.tools.builtins.update_agent_tool import update_agent

DEFAULT_USER = "test-user-autouse"  # matches the autouse fixture in tests/conftest.py


class _DummyRuntime(SimpleNamespace):
    context: dict
    tool_call_id: str


def _runtime(agent_name: str | None = "test-agent", tool_call_id: str = "call_1") -> _DummyRuntime:
    return _DummyRuntime(context={"agent_name": agent_name} if agent_name is not None else {}, tool_call_id=tool_call_id)


def _make_paths_mock(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.base_dir = tmp_path
    paths.agent_dir = lambda name: tmp_path / "agents" / name
    paths.agents_dir = tmp_path / "agents"
    paths.user_agent_dir = lambda user_id, name: tmp_path / "users" / user_id / "agents" / name
    paths.user_agents_dir = lambda user_id: tmp_path / "users" / user_id / "agents"
    return paths


def _user_agent_dir(tmp_path: Path, name: str = "test-agent", user_id: str = DEFAULT_USER) -> Path:
    return tmp_path / "users" / user_id / "agents" / name


def _seed_agent(
    tmp_path: Path,
    name: str = "test-agent",
    *,
    description: str = "old desc",
    soul: str = "old soul",
    skills: list[str] | None = None,
    user_id: str = DEFAULT_USER,
) -> Path:
    """Create a baseline agent dir with config.yaml and SOUL.md for tests to mutate."""
    agent_dir = _user_agent_dir(tmp_path, name, user_id=user_id)
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


@pytest.fixture()
def stub_app_config():
    """Stub get_app_config so model validation accepts only known names."""
    fake = MagicMock()
    fake.get_model_config.side_effect = lambda name: object() if name in {"gpt-known", "m1"} else None
    with patch("deerflow.tools.builtins.update_agent_tool.get_app_config", return_value=fake):
        yield fake


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
    assert not _user_agent_dir(tmp_path, "ghost").exists()


def test_update_agent_requires_at_least_one_field(tmp_path, patched_paths):
    _seed_agent(tmp_path)

    result = update_agent.func(runtime=_runtime())

    msg = result.update["messages"][0]
    assert "No fields provided" in msg.content


def test_update_agent_rejects_unknown_model(tmp_path, patched_paths, stub_app_config):
    """Copilot review: model must be validated against configured models before
    being persisted; otherwise _resolve_model_name silently falls back to the
    default and the user gets repeated warnings on every later turn."""
    _seed_agent(tmp_path)

    result = update_agent.func(runtime=_runtime(), model="not-in-config")

    msg = result.update["messages"][0]
    assert "Unknown model" in msg.content
    cfg = yaml.safe_load((_user_agent_dir(tmp_path) / "config.yaml").read_text())
    assert "model" not in cfg, "Invalid model must not have been written to config.yaml"


def test_update_agent_accepts_known_model(tmp_path, patched_paths, stub_app_config):
    _seed_agent(tmp_path)

    result = update_agent.func(runtime=_runtime(), model="gpt-known")

    cfg = yaml.safe_load((_user_agent_dir(tmp_path) / "config.yaml").read_text())
    assert cfg["model"] == "gpt-known"
    assert "model" in result.update["messages"][0].content


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


def test_update_agent_forces_name_to_directory(tmp_path, patched_paths):
    """Copilot review: if the existing config.yaml has a drifted ``name`` field,
    update_agent must rewrite it to match the directory name so on-disk state
    stays consistent with the runtime context."""
    agent_dir = _user_agent_dir(tmp_path)
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump({"name": "drifted-name", "description": "old"}, sort_keys=False), encoding="utf-8")
    (agent_dir / "SOUL.md").write_text("soul", encoding="utf-8")

    update_agent.func(runtime=_runtime(), description="bumped")

    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["name"] == "test-agent", "config.yaml name must follow the directory name, not legacy yaml content"


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


def test_update_agent_soul_failure_does_not_replace_config(tmp_path, patched_paths):
    """Copilot review: if both config.yaml and SOUL.md are scheduled to be
    written and SOUL.md staging fails *before* any rename, config.yaml must
    NOT be replaced. The fix stages every temp file first and only renames
    after all temps exist on disk."""
    agent_dir = _seed_agent(tmp_path, description="original-desc", soul="original soul")

    real_named_temp_file = __import__("tempfile").NamedTemporaryFile
    call_count = {"n": 0}

    def _explode_on_soul(*args, **kwargs):
        # Inspect target dir + suffix; the SOUL temp file is the second one we stage.
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise OSError("disk full while staging SOUL.md")
        return real_named_temp_file(*args, **kwargs)

    with patch("deerflow.tools.builtins.update_agent_tool.tempfile.NamedTemporaryFile", side_effect=_explode_on_soul):
        result = update_agent.func(runtime=_runtime(), description="new-desc", soul="new soul")

    cfg = yaml.safe_load((agent_dir / "config.yaml").read_text())
    assert cfg["description"] == "original-desc", "config.yaml must not be replaced when SOUL.md staging fails"
    assert (agent_dir / "SOUL.md").read_text() == "original soul"
    assert "Error" in result.update["messages"][0].content
    assert list(agent_dir.glob("*.tmp")) == [], "staged config.yaml temp must be cleaned up on SOUL.md failure"


# --- Per-user isolation ---


def test_update_agent_only_writes_under_current_user(tmp_path, patched_paths):
    """An update from user 'alice' must never touch user 'bob's agent files."""
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    # Seed an agent for both users with the same name.
    alice_dir = _seed_agent(tmp_path, name="shared", description="alice-desc", soul="alice soul", user_id="alice")
    bob_dir = _seed_agent(tmp_path, name="shared", description="bob-desc", soul="bob soul", user_id="bob")

    # Override the autouse contextvar so update_agent runs as Alice.
    token = set_current_user(SimpleNamespace(id="alice"))
    try:
        update_agent.func(runtime=_runtime(agent_name="shared"), description="alice-bumped")
    finally:
        reset_current_user(token)

    alice_cfg = yaml.safe_load((alice_dir / "config.yaml").read_text())
    bob_cfg = yaml.safe_load((bob_dir / "config.yaml").read_text())
    assert alice_cfg["description"] == "alice-bumped"
    assert bob_cfg["description"] == "bob-desc", "bob's config.yaml must not have been touched"
    assert (bob_dir / "SOUL.md").read_text() == "bob soul"


# --- Loader passthrough sanity check ---


def test_update_agent_round_trips_known_fields(tmp_path, patched_paths):
    """update_agent reads through load_agent_config so all fields the loader
    knows about (name, description, model, tool_groups, skills) round-trip
    on a partial update.

    Note: ``load_agent_config`` strips unknown fields before constructing
    AgentConfig, so legacy/extra YAML keys are NOT preserved across
    updates — by design.
    """
    _seed_agent(tmp_path, description="legacy")

    fake_cfg = AgentConfig(name="test-agent", description="legacy", skills=["s1"], tool_groups=["g1"], model="m1")
    fake_app_config = MagicMock()
    fake_app_config.get_model_config.return_value = object()
    with patch("deerflow.tools.builtins.update_agent_tool.load_agent_config", return_value=fake_cfg):
        with patch("deerflow.tools.builtins.update_agent_tool.get_app_config", return_value=fake_app_config):
            update_agent.func(runtime=_runtime(), description="bumped")

    cfg = yaml.safe_load((_user_agent_dir(tmp_path) / "config.yaml").read_text())
    assert cfg["description"] == "bumped"
    assert cfg["skills"] == ["s1"]
    assert cfg["tool_groups"] == ["g1"]
    assert cfg["model"] == "m1"
