"""Tests for setup_agent tool — validates agent name security and data loss prevention."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deerflow.tools.builtins.setup_agent_tool import setup_agent

# --- Helpers ---


class _DummyRuntime(SimpleNamespace):
    context: dict
    tool_call_id: str


def _make_runtime(agent_name: str | None = "test-agent") -> MagicMock:
    runtime = MagicMock()
    runtime.context = {"agent_name": agent_name}
    runtime.tool_call_id = "call_1"
    return runtime


def _make_paths_mock(tmp_path: Path):
    paths = MagicMock()
    paths.base_dir = tmp_path
    paths.agent_dir = lambda name: tmp_path / "agents" / name
    paths.user_agent_dir = lambda user_id, name: tmp_path / "users" / user_id / "agents" / name
    return paths


def _call_setup_agent(tmp_path: Path, soul: str, description: str, agent_name: str = "test-agent"):
    """Call the underlying setup_agent function directly, bypassing langchain tool wrapper."""
    with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)):
        return setup_agent.func(
            soul=soul,
            description=description,
            runtime=_make_runtime(agent_name),
        )


# --- Agent name validation tests ---


def test_setup_agent_rejects_invalid_agent_name_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    outside_dir = tmp_path.parent / "outside-target"
    traversal_agent = f"../../../{outside_dir.name}/evil"
    runtime = _DummyRuntime(context={"agent_name": traversal_agent}, tool_call_id="tool-1")

    result = setup_agent.func(soul="test soul", description="desc", runtime=runtime)

    messages = result.update["messages"]
    assert len(messages) == 1
    assert "Invalid agent name" in messages[0].content
    assert not (tmp_path / "users" / "test-user-autouse" / "agents").exists()
    assert not (outside_dir / "evil" / "SOUL.md").exists()


def test_setup_agent_rejects_absolute_agent_name_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    absolute_agent = str(tmp_path / "outside-agent")
    runtime = _DummyRuntime(context={"agent_name": absolute_agent}, tool_call_id="tool-2")

    result = setup_agent.func(soul="test soul", description="desc", runtime=runtime)

    messages = result.update["messages"]
    assert len(messages) == 1
    assert "Invalid agent name" in messages[0].content
    assert not (tmp_path / "users" / "test-user-autouse" / "agents").exists()
    assert not (Path(absolute_agent) / "SOUL.md").exists()


# --- Data loss prevention tests ---


class TestSetupAgentNoDataLoss:
    """Ensure shutil.rmtree only removes directories created during the current call."""

    def test_existing_agent_dir_preserved_on_failure(self, tmp_path: Path):
        """If the agent directory already exists and setup fails,
        the directory and its contents must NOT be deleted."""
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        old_soul = agent_dir / "SOUL.md"
        old_soul.write_text("original soul content", encoding="utf-8")

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)):
            # Force soul_file.write_text to raise after directory already exists
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                setup_agent.func(
                    soul="new soul",
                    description="desc",
                    runtime=_make_runtime(),
                )

        # Directory must still exist
        assert agent_dir.exists(), "Pre-existing agent directory was deleted on failure"
        # Original SOUL.md should still be on disk (not deleted by rmtree)
        assert old_soul.exists(), "Pre-existing SOUL.md was deleted on failure"

    def test_new_agent_dir_cleaned_up_on_failure(self, tmp_path: Path):
        """If the agent directory is newly created and setup fails,
        the directory should be cleaned up."""
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        assert not agent_dir.exists()

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)):
            with patch("yaml.dump", side_effect=OSError("write error")):
                setup_agent.func(
                    soul="new soul",
                    description="desc",
                    runtime=_make_runtime(),
                )

        # Newly created directory should be cleaned up
        assert not agent_dir.exists(), "Newly created agent directory was not cleaned up on failure"

    def test_successful_setup_creates_files(self, tmp_path: Path):
        """Happy path: setup_agent creates config.yaml and SOUL.md."""
        _call_setup_agent(tmp_path, soul="# My Agent", description="A test agent")

        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        assert agent_dir.exists()
        assert (agent_dir / "SOUL.md").read_text() == "# My Agent"
        assert (agent_dir / "config.yaml").exists()
