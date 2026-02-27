"""Tests for DeerFlowClient."""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: F401

from src.client import DeerFlowClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_app_config():
    """Provide a minimal AppConfig mock."""
    model = MagicMock()
    model.name = "test-model"
    model.model_dump.return_value = {"name": "test-model", "use": "langchain_openai:ChatOpenAI"}

    config = MagicMock()
    config.models = [model]
    return config


@pytest.fixture
def client(mock_app_config):
    """Create a DeerFlowClient with mocked config loading."""
    with patch("src.client.get_app_config", return_value=mock_app_config):
        return DeerFlowClient()


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_default_params(self, client):
        assert client._model_name is None
        assert client._thinking_enabled is True
        assert client._subagent_enabled is False
        assert client._plan_mode is False
        assert client._checkpointer is None
        assert client._agent is None

    def test_custom_params(self, mock_app_config):
        with patch("src.client.get_app_config", return_value=mock_app_config):
            c = DeerFlowClient(
                model_name="gpt-4",
                thinking_enabled=False,
                subagent_enabled=True,
                plan_mode=True,
            )
        assert c._model_name == "gpt-4"
        assert c._thinking_enabled is False
        assert c._subagent_enabled is True
        assert c._plan_mode is True

    def test_custom_config_path(self, mock_app_config):
        with (
            patch("src.client.reload_app_config") as mock_reload,
            patch("src.client.get_app_config", return_value=mock_app_config),
        ):
            DeerFlowClient(config_path="/tmp/custom.yaml")
            mock_reload.assert_called_once_with("/tmp/custom.yaml")

    def test_checkpointer_stored(self, mock_app_config):
        cp = MagicMock()
        with patch("src.client.get_app_config", return_value=mock_app_config):
            c = DeerFlowClient(checkpointer=cp)
        assert c._checkpointer is cp


# ---------------------------------------------------------------------------
# list_models / list_skills / get_memory
# ---------------------------------------------------------------------------

class TestConfigQueries:
    def test_list_models(self, client):
        models = client.list_models()
        assert len(models) == 1
        assert models[0]["name"] == "test-model"

    def test_list_skills(self, client):
        skill = MagicMock()
        skill.name = "web-search"
        skill.description = "Search the web"
        skill.category = "public"
        skill.enabled = True

        with patch("src.skills.loader.load_skills", return_value=[skill]) as mock_load:
            result = client.list_skills()
            mock_load.assert_called_once_with(enabled_only=False)

        assert len(result) == 1
        assert result[0] == {
            "name": "web-search",
            "description": "Search the web",
            "category": "public",
            "enabled": True,
        }

    def test_list_skills_enabled_only(self, client):
        with patch("src.skills.loader.load_skills", return_value=[]) as mock_load:
            client.list_skills(enabled_only=True)
            mock_load.assert_called_once_with(enabled_only=True)

    def test_get_memory(self, client):
        memory = {"version": "1.0", "facts": []}
        with patch("src.agents.memory.updater.get_memory_data", return_value=memory) as mock_mem:
            result = client.get_memory()
            mock_mem.assert_called_once()
        assert result == memory


# ---------------------------------------------------------------------------
# stream / chat
# ---------------------------------------------------------------------------

def _make_agent_mock(chunks: list[dict]):
    """Create a mock agent whose .stream() yields the given chunks."""
    agent = MagicMock()
    agent.stream.return_value = iter(chunks)
    return agent


class TestStream:
    def test_basic_message(self, client):
        """stream() emits message + done for a simple AI reply."""
        ai = AIMessage(content="Hello!", id="ai-1")
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1")]},
            {"messages": [HumanMessage(content="hi", id="h-1"), ai]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t1"))

        types = [e.type for e in events]
        assert "message" in types
        assert types[-1] == "done"
        msg_events = [e for e in events if e.type == "message"]
        assert msg_events[0].data["content"] == "Hello!"

    def test_tool_call_and_result(self, client):
        """stream() emits tool_call and tool_result events."""
        ai = AIMessage(content="", id="ai-1", tool_calls=[{"name": "bash", "args": {"cmd": "ls"}, "id": "tc-1"}])
        tool = ToolMessage(content="file.txt", id="tm-1", tool_call_id="tc-1", name="bash")
        ai2 = AIMessage(content="Here are the files.", id="ai-2")

        chunks = [
            {"messages": [HumanMessage(content="list files", id="h-1"), ai]},
            {"messages": [HumanMessage(content="list files", id="h-1"), ai, tool]},
            {"messages": [HumanMessage(content="list files", id="h-1"), ai, tool, ai2]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("list files", thread_id="t2"))

        types = [e.type for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "message" in types
        assert types[-1] == "done"

    def test_title_event(self, client):
        """stream() emits title event when title appears in state."""
        ai = AIMessage(content="ok", id="ai-1")
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1"), ai], "title": "Greeting"},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t3"))

        title_events = [e for e in events if e.type == "title"]
        assert len(title_events) == 1
        assert title_events[0].data["title"] == "Greeting"

    def test_deduplication(self, client):
        """Messages with the same id are not emitted twice."""
        ai = AIMessage(content="Hello!", id="ai-1")
        chunks = [
            {"messages": [HumanMessage(content="hi", id="h-1"), ai]},
            {"messages": [HumanMessage(content="hi", id="h-1"), ai]},  # duplicate
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t4"))

        msg_events = [e for e in events if e.type == "message"]
        assert len(msg_events) == 1

    def test_auto_thread_id(self, client):
        """stream() auto-generates a thread_id if not provided."""
        agent = _make_agent_mock([{"messages": [AIMessage(content="ok", id="ai-1")]}])

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi"))

        # Should not raise; done event proves it completed
        assert events[-1].type == "done"

    def test_list_content_blocks(self, client):
        """stream() handles AIMessage with list-of-blocks content."""
        ai = AIMessage(
            content=[
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "result"},
            ],
            id="ai-1",
        )
        chunks = [{"messages": [ai]}]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t5"))

        msg_events = [e for e in events if e.type == "message"]
        assert len(msg_events) == 1
        assert msg_events[0].data["content"] == "result"


class TestChat:
    def test_returns_last_message(self, client):
        """chat() returns the last AI message text."""
        ai1 = AIMessage(content="thinking...", id="ai-1")
        ai2 = AIMessage(content="final answer", id="ai-2")
        chunks = [
            {"messages": [HumanMessage(content="q", id="h-1"), ai1]},
            {"messages": [HumanMessage(content="q", id="h-1"), ai1, ai2]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            result = client.chat("q", thread_id="t6")

        assert result == "final answer"

    def test_empty_response(self, client):
        """chat() returns empty string if no AI message produced."""
        chunks = [{"messages": []}]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            result = client.chat("q", thread_id="t7")

        assert result == ""


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_string(self):
        assert DeerFlowClient._extract_text("hello") == "hello"

    def test_list_text_blocks(self):
        content = [
            {"type": "text", "text": "first"},
            {"type": "thinking", "thinking": "skip"},
            {"type": "text", "text": "second"},
        ]
        assert DeerFlowClient._extract_text(content) == "first\nsecond"

    def test_list_plain_strings(self):
        assert DeerFlowClient._extract_text(["a", "b"]) == "a\nb"

    def test_empty_list(self):
        assert DeerFlowClient._extract_text([]) == ""

    def test_other_type(self):
        assert DeerFlowClient._extract_text(42) == "42"


# ---------------------------------------------------------------------------
# _ensure_agent
# ---------------------------------------------------------------------------

class TestEnsureAgent:
    def test_creates_agent(self, client):
        """_ensure_agent creates an agent on first call."""
        mock_agent = MagicMock()
        config = client._get_runnable_config("t1")

        with (
            patch("src.client.create_chat_model"),
            patch("src.client.create_agent", return_value=mock_agent),
            patch("src.client._build_middlewares", return_value=[]),
            patch("src.client.apply_prompt_template", return_value="prompt"),
            patch.object(client, "_get_tools", return_value=[]),
        ):
            client._ensure_agent(config)

        assert client._agent is mock_agent

    def test_reuses_agent_same_config(self, client):
        """_ensure_agent does not recreate if config key unchanged."""
        mock_agent = MagicMock()
        client._agent = mock_agent
        client._agent_config_key = (None, True, False, False)

        config = client._get_runnable_config("t1")
        client._ensure_agent(config)

        # Should still be the same mock — no recreation
        assert client._agent is mock_agent


# ---------------------------------------------------------------------------
# get_model
# ---------------------------------------------------------------------------

class TestGetModel:
    def test_found(self, client):
        model_cfg = MagicMock()
        model_cfg.model_dump.return_value = {"name": "test-model"}
        client._app_config.get_model_config.return_value = model_cfg

        result = client.get_model("test-model")
        assert result == {"name": "test-model"}

    def test_not_found(self, client):
        client._app_config.get_model_config.return_value = None
        assert client.get_model("nonexistent") is None


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

class TestMcpConfig:
    def test_get_mcp_config(self, client):
        server = MagicMock()
        server.model_dump.return_value = {"enabled": True, "type": "stdio"}
        ext_config = MagicMock()
        ext_config.mcp_servers = {"github": server}

        with patch("src.client.get_extensions_config", return_value=ext_config):
            result = client.get_mcp_config()

        assert "github" in result
        assert result["github"]["enabled"] is True

    def test_update_mcp_config(self, client):
        # Set up current config with skills
        current_config = MagicMock()
        current_config.skills = {}

        reloaded_server = MagicMock()
        reloaded_server.model_dump.return_value = {"enabled": True, "type": "sse"}
        reloaded_config = MagicMock()
        reloaded_config.mcp_servers = {"new-server": reloaded_server}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            tmp_path = Path(f.name)

        try:
            with (
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=tmp_path),
                patch("src.client.get_extensions_config", return_value=current_config),
                patch("src.client.reload_extensions_config", return_value=reloaded_config),
            ):
                result = client.update_mcp_config({"new-server": {"enabled": True, "type": "sse"}})

            assert "new-server" in result

            # Verify file was actually written
            with open(tmp_path) as f:
                saved = json.load(f)
            assert "mcpServers" in saved
        finally:
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# Skills management
# ---------------------------------------------------------------------------

class TestSkillsManagement:
    def _make_skill(self, name="test-skill", enabled=True):
        s = MagicMock()
        s.name = name
        s.description = "A test skill"
        s.license = "MIT"
        s.category = "public"
        s.enabled = enabled
        return s

    def test_get_skill_found(self, client):
        skill = self._make_skill()
        with patch("src.skills.loader.load_skills", return_value=[skill]):
            result = client.get_skill("test-skill")
        assert result is not None
        assert result["name"] == "test-skill"

    def test_get_skill_not_found(self, client):
        with patch("src.skills.loader.load_skills", return_value=[]):
            result = client.get_skill("nonexistent")
        assert result is None

    def test_update_skill(self, client):
        skill = self._make_skill(enabled=True)
        updated_skill = self._make_skill(enabled=False)

        ext_config = MagicMock()
        ext_config.mcp_servers = {}
        ext_config.skills = {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            tmp_path = Path(f.name)

        try:
            with (
                patch("src.skills.loader.load_skills", side_effect=[[skill], [updated_skill]]),
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=tmp_path),
                patch("src.client.get_extensions_config", return_value=ext_config),
                patch("src.client.reload_extensions_config"),
            ):
                result = client.update_skill("test-skill", enabled=False)
            assert result["enabled"] is False
        finally:
            tmp_path.unlink()

    def test_update_skill_not_found(self, client):
        with patch("src.skills.loader.load_skills", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                client.update_skill("nonexistent", enabled=True)

    def test_install_skill(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a valid .skill archive
            skill_dir = tmp_path / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\nContent")

            archive_path = tmp_path / "my-skill.skill"
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.write(skill_dir / "SKILL.md", "my-skill/SKILL.md")

            skills_root = tmp_path / "skills"
            (skills_root / "custom").mkdir(parents=True)

            with (
                patch("src.skills.loader.get_skills_root_path", return_value=skills_root),
                patch("src.gateway.routers.skills._validate_skill_frontmatter", return_value=(True, "OK", "my-skill")),
            ):
                result = client.install_skill(archive_path)

            assert result["success"] is True
            assert result["skill_name"] == "my-skill"
            assert (skills_root / "custom" / "my-skill").exists()

    def test_install_skill_not_found(self, client):
        with pytest.raises(FileNotFoundError):
            client.install_skill("/nonexistent/path.skill")

    def test_install_skill_bad_extension(self, client):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            with pytest.raises(ValueError, match=".skill extension"):
                client.install_skill(tmp_path)
        finally:
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# Memory management
# ---------------------------------------------------------------------------

class TestMemoryManagement:
    def test_reload_memory(self, client):
        data = {"version": "1.0", "facts": []}
        with patch("src.agents.memory.updater.reload_memory_data", return_value=data):
            result = client.reload_memory()
        assert result == data

    def test_get_memory_config(self, client):
        config = MagicMock()
        config.enabled = True
        config.storage_path = ".deer-flow/memory.json"
        config.debounce_seconds = 30
        config.max_facts = 100
        config.fact_confidence_threshold = 0.7
        config.injection_enabled = True
        config.max_injection_tokens = 2000

        with patch("src.config.memory_config.get_memory_config", return_value=config):
            result = client.get_memory_config()

        assert result["enabled"] is True
        assert result["max_facts"] == 100

    def test_get_memory_status(self, client):
        config = MagicMock()
        config.enabled = True
        config.storage_path = ".deer-flow/memory.json"
        config.debounce_seconds = 30
        config.max_facts = 100
        config.fact_confidence_threshold = 0.7
        config.injection_enabled = True
        config.max_injection_tokens = 2000

        data = {"version": "1.0", "facts": []}

        with (
            patch("src.config.memory_config.get_memory_config", return_value=config),
            patch("src.agents.memory.updater.get_memory_data", return_value=data),
        ):
            result = client.get_memory_status()

        assert "config" in result
        assert "data" in result


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

class TestUploads:
    def test_upload_files(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a source file
            src_file = tmp_path / "test.txt"
            src_file.write_text("hello")

            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir()

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                result = client.upload_files("thread-1", [src_file])

            assert len(result) == 1
            assert result[0]["filename"] == "test.txt"
            assert (uploads_dir / "test.txt").exists()

    def test_upload_files_not_found(self, client):
        with pytest.raises(FileNotFoundError):
            client.upload_files("thread-1", ["/nonexistent/file.txt"])

    def test_list_uploads(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            uploads_dir = Path(tmp)
            (uploads_dir / "a.txt").write_text("a")
            (uploads_dir / "b.txt").write_text("bb")

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                result = client.list_uploads("thread-1")

            assert len(result) == 2
            names = {f["filename"] for f in result}
            assert names == {"a.txt", "b.txt"}

    def test_delete_upload(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            uploads_dir = Path(tmp)
            (uploads_dir / "delete-me.txt").write_text("gone")

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                client.delete_upload("thread-1", "delete-me.txt")

            assert not (uploads_dir / "delete-me.txt").exists()

    def test_delete_upload_not_found(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=Path(tmp)):
                with pytest.raises(FileNotFoundError):
                    client.delete_upload("thread-1", "nope.txt")


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class TestArtifacts:
    def test_get_artifact(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            # Simulate thread user-data structure
            base = Path(tmp)
            outputs = base / "outputs"
            outputs.mkdir()
            (outputs / "result.txt").write_text("hello artifact")

            with patch("src.client.THREAD_DATA_BASE_DIR", ""):
                with patch("os.getcwd", return_value=tmp):
                    # Directly test with a simpler path setup
                    pass

        # Use a controlled setup
        with tempfile.TemporaryDirectory() as tmp:
            thread_dir = Path(tmp) / ".deer-flow" / "threads" / "t1" / "user-data" / "outputs"
            thread_dir.mkdir(parents=True)
            (thread_dir / "result.txt").write_text("artifact content")

            with patch("os.getcwd", return_value=tmp):
                with patch("src.client.THREAD_DATA_BASE_DIR", ".deer-flow/threads"):
                    content, mime = client.get_artifact("t1", "mnt/user-data/outputs/result.txt")

            assert content == b"artifact content"
            assert "text" in mime

    def test_get_artifact_not_found(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("os.getcwd", return_value=tmp),
                patch("src.client.THREAD_DATA_BASE_DIR", ".deer-flow/threads"),
            ):
                with pytest.raises(FileNotFoundError):
                    client.get_artifact("t1", "mnt/user-data/outputs/nope.txt")

    def test_get_artifact_bad_prefix(self, client):
        with pytest.raises(ValueError, match="must start with"):
            client.get_artifact("t1", "bad/path/file.txt")
