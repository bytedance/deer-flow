"""Tests for setup_agent tool — validates agent name security and data loss prevention."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
    with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
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

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
            # Force soul_file.write_text to raise after directory already exists
            with patch("yaml.dump", side_effect=OSError("disk full")):
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

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
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

    @pytest.mark.no_auto_user
    def test_runtime_user_id_used_when_contextvar_missing(self, tmp_path: Path):
        """setup_agent should not fall back to default when runtime carries user_id."""
        runtime = _DummyRuntime(
            context={"agent_name": "test-agent", "user_id": "auth-user-42"},
            tool_call_id="tool-3",
        )

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
            setup_agent.func(
                soul="# My Agent",
                description="A test agent",
                runtime=runtime,
            )

        expected_dir = tmp_path / "users" / "auth-user-42" / "agents" / "test-agent"
        default_dir = tmp_path / "users" / "default" / "agents" / "test-agent"
        assert (expected_dir / "SOUL.md").read_text() == "# My Agent"
        assert not default_dir.exists()


# --- Empty soul guard tests  ---


class TestSetupAgentEmptySoulGuard:
    """The tool must refuse to persist an empty / whitespace-only SOUL.md and
    must not touch the filesystem at all, so an existing SOUL.md (per-agent or
    global default) cannot be silently overwritten with empty content.
    """

    def test_empty_soul_returns_error_and_does_not_write(self, tmp_path: Path):
        result = _call_setup_agent(tmp_path, soul="", description="desc")

        messages = result.update["messages"]
        assert len(messages) == 1
        assert "soul content is empty" in messages[0].content
        assert "created_agent_name" not in result.update
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        assert not agent_dir.exists()

    def test_whitespace_only_soul_returns_error_and_does_not_write(self, tmp_path: Path):
        result = _call_setup_agent(tmp_path, soul="   \n\t  ", description="desc")

        messages = result.update["messages"]
        assert len(messages) == 1
        assert "soul content is empty" in messages[0].content
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        assert not agent_dir.exists()

    def test_empty_soul_does_not_overwrite_existing_global_soul(self, tmp_path: Path):
        """If agent_name resolution would have fallen back to base_dir, an
        empty soul must not clobber a pre-existing global SOUL.md.
        """
        global_soul = tmp_path / "SOUL.md"
        global_soul.write_text("original global soul", encoding="utf-8")

        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
            setup_agent.func(
                soul="",
                description="desc",
                runtime=_DummyRuntime(context={"agent_name": None}, tool_call_id="tool-empty"),
            )

        assert global_soul.read_text(encoding="utf-8") == "original global soul"

    def test_empty_soul_does_not_overwrite_existing_per_agent_soul(self, tmp_path: Path):
        agent_dir = tmp_path / "users" / "test-user-autouse" / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        existing_soul = agent_dir / "SOUL.md"
        existing_soul.write_text("original per-agent soul", encoding="utf-8")

        _call_setup_agent(tmp_path, soul="   ", description="desc")

        assert existing_soul.read_text(encoding="utf-8") == "original per-agent soul"


class TestSetupAgentGlobalSoulAtomicPublish:
    """The default agent's SOUL.md must never be observable half written."""

    def _write_global_soul(self, tmp_path: Path, soul: str):
        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
            return setup_agent.func(
                soul=soul,
                description="desc",
                runtime=_DummyRuntime(context={"agent_name": None}, tool_call_id="tool-global"),
            )

    def test_publishes_full_soul_without_leaving_temps(self, tmp_path: Path):
        result = self._write_global_soul(tmp_path, "# Persona\n\nBe kind.")

        soul_path = tmp_path / "SOUL.md"
        assert soul_path.read_text(encoding="utf-8") == "# Persona\n\nBe kind."
        assert list(tmp_path.glob("*.tmp")) == []
        assert "created successfully" in result.update["messages"][0].content

    def test_failed_publish_keeps_the_previous_soul(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("original global soul", encoding="utf-8")

        def _boom(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(os, "replace", _boom)
        result = self._write_global_soul(tmp_path, "replacement soul")

        # A truncating write would have emptied SOUL.md before failing, leaving
        # every later run with a persona file missing its instructions;
        # publishing through a temporary file cannot.
        assert soul_path.read_text(encoding="utf-8") == "original global soul"
        assert list(tmp_path.glob("*.tmp")) == []
        assert "Error" in result.update["messages"][0].content

    def test_truncating_write_would_have_destroyed_it(self, tmp_path: Path):
        """Control: the previous implementation loses the content in the same failure."""
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("original global soul", encoding="utf-8")

        try:
            with open(soul_path, "w", encoding="utf-8") as handle:
                handle.write("replacement soul")
                raise OSError("read-only filesystem")
        except OSError:
            pass

        assert soul_path.read_text(encoding="utf-8") != "original global soul"

    def test_publish_sets_the_temp_mode_before_the_replace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("original global soul", encoding="utf-8")
        chmod_calls: list[tuple[Path, int]] = []
        real_chmod = os.chmod

        def spy_chmod(path, mode):
            chmod_calls.append((Path(path), mode))
            real_chmod(path, mode)

        monkeypatch.setattr(os, "chmod", spy_chmod)
        self._write_global_soul(tmp_path, "replacement soul")

        # The staged temporary — not the published file — carries the target's
        # mode into the replace, so the published file never takes mkstemp's
        # 0600 and a re-publish keeps a mode an operator set.
        assert chmod_calls, "the temporary must be chmod'ed before the replace"
        temporary, mode = chmod_calls[0]
        assert temporary.name.endswith(".tmp")
        assert mode == stat.S_IMODE(os.stat(soul_path).st_mode)

    def test_staging_failure_leaves_no_temporary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("original global soul", encoding="utf-8")
        real_named_temporary_file = tempfile.NamedTemporaryFile

        class _FailingStagingHandle:
            """Stands in for the staging handle: the write fails mid-flight (ENOSPC)."""

            def __init__(self, *args, **kwargs):
                self._handle = real_named_temporary_file(*args, **kwargs)
                self.name = self._handle.name

            def write(self, data):
                raise OSError("No space left on device")

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                self._handle.close()
                return False

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", _FailingStagingHandle)
        result = self._write_global_soul(tmp_path, "replacement soul")

        # The staging failure happens before the replace, so the previous file
        # survives and the delete=False temporary is cleaned up rather than
        # orphaned in base_dir.
        assert soul_path.read_text(encoding="utf-8") == "original global soul"
        assert list(tmp_path.glob("*.tmp")) == []
        assert "Error" in result.update["messages"][0].content


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits; Windows chmod only carries the read-only flag")
class TestSetupAgentGlobalSoulPublishMode:
    """The published SOUL.md keeps a real mode, never mkstemp's 0600."""

    def _write_global_soul(self, tmp_path: Path, soul: str):
        with patch("deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=_make_paths_mock(tmp_path)), patch("deerflow.config.agents_config.get_paths", return_value=_make_paths_mock(tmp_path)):
            return setup_agent.func(
                soul=soul,
                description="desc",
                runtime=_DummyRuntime(context={"agent_name": None}, tool_call_id="tool-global"),
            )

    def test_first_publish_is_world_readable(self, tmp_path: Path):
        self._write_global_soul(tmp_path, "# Persona")

        assert stat.S_IMODE(os.stat(tmp_path / "SOUL.md").st_mode) == 0o644

    def test_republish_preserves_the_operators_mode(self, tmp_path: Path):
        soul_path = tmp_path / "SOUL.md"
        soul_path.write_text("original global soul", encoding="utf-8")
        os.chmod(soul_path, 0o640)

        self._write_global_soul(tmp_path, "replacement soul")

        assert soul_path.read_text(encoding="utf-8") == "replacement soul"
        assert stat.S_IMODE(os.stat(soul_path).st_mode) == 0o640
