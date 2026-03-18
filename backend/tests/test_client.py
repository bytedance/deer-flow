"""Tests for DeerFlowClient."""

import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: F401

from src.client import DeerFlowClient
from src.gateway.routers.mcp import McpConfigResponse
from src.gateway.routers.memory import MemoryConfigResponse, MemoryStatusResponse
from src.gateway.routers.models import ModelResponse, ModelsListResponse
from src.gateway.routers.reports import (
    ImageReportPdfResponse,
    LatexDiagnosticsMarkdownResponse,
)
from src.gateway.routers.research_writing import (
    CapabilityAssessmentResponse,
    CapabilityCatalogResponse,
    EvalAcademicResponse,
    FulltextIngestResponse,
    HitlDecisionsResponse,
    HypothesisGenerateResponse,
    LatexCompileResponse,
    NarrativePlanResponse,
    PeerReviewLoopResponse,
    ProjectResponse,
    ProjectsListResponse,
    ReviewSimulateResponse,
    SectionCompileResponse,
)
from src.gateway.routers.skills import SkillInstallResponse, SkillResponse, SkillsListResponse
from src.gateway.routers.uploads import UploadResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app_config():
    """Provide a minimal AppConfig mock."""
    model = MagicMock()
    model.name = "test-model"
    model.supports_thinking = False
    model.supports_reasoning_effort = False
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
        result = client.list_models()
        assert "models" in result
        assert len(result["models"]) == 1
        assert result["models"][0]["name"] == "test-model"
        # Verify Gateway-aligned fields are present
        assert "display_name" in result["models"][0]
        assert "supports_thinking" in result["models"][0]

    def test_list_skills(self, client):
        skill = MagicMock()
        skill.name = "web-search"
        skill.description = "Search the web"
        skill.license = "MIT"
        skill.category = "public"
        skill.enabled = True

        with patch("src.skills.loader.load_skills", return_value=[skill]) as mock_load:
            result = client.list_skills()
            mock_load.assert_called_once_with(enabled_only=False)

        assert "skills" in result
        assert len(result["skills"]) == 1
        assert result["skills"][0] == {
            "name": "web-search",
            "description": "Search the web",
            "license": "MIT",
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


def _ai_events(events):
    """Filter messages-tuple events with type=ai and non-empty content."""
    return [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai" and e.data.get("content")]


def _tool_call_events(events):
    """Filter messages-tuple events with type=ai and tool_calls."""
    return [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai" and "tool_calls" in e.data]


def _tool_result_events(events):
    """Filter messages-tuple events with type=tool."""
    return [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "tool"]


class TestStream:
    def test_basic_message(self, client):
        """stream() emits messages-tuple + values + end for a simple AI reply."""
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
        assert "messages-tuple" in types
        assert "values" in types
        assert types[-1] == "end"
        msg_events = _ai_events(events)
        assert msg_events[0].data["content"] == "Hello!"

    def test_tool_call_and_result(self, client):
        """stream() emits messages-tuple events for tool calls and results."""
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

        assert len(_tool_call_events(events)) >= 1
        assert len(_tool_result_events(events)) >= 1
        assert len(_ai_events(events)) >= 1
        assert events[-1].type == "end"

    def test_values_event_with_title(self, client):
        """stream() emits values event containing title when present in state."""
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

        values_events = [e for e in events if e.type == "values"]
        assert len(values_events) >= 1
        assert values_events[-1].data["title"] == "Greeting"
        assert "messages" in values_events[-1].data

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

        msg_events = _ai_events(events)
        assert len(msg_events) == 1

    def test_auto_thread_id(self, client):
        """stream() auto-generates a thread_id if not provided."""
        agent = _make_agent_mock([{"messages": [AIMessage(content="ok", id="ai-1")]}])

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi"))

        # Should not raise; end event proves it completed
        assert events[-1].type == "end"

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

        msg_events = _ai_events(events)
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
        model_cfg.name = "test-model"
        model_cfg.display_name = "Test Model"
        model_cfg.description = "A test model"
        model_cfg.supports_thinking = True
        model_cfg.supports_reasoning_effort = True
        client._app_config.get_model_config.return_value = model_cfg

        result = client.get_model("test-model")
        assert result == {
            "name": "test-model",
            "display_name": "Test Model",
            "description": "A test model",
            "supports_thinking": True,
            "supports_reasoning_effort": True,
        }

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

        assert "mcp_servers" in result
        assert "github" in result["mcp_servers"]
        assert result["mcp_servers"]["github"]["enabled"] is True

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
            # Pre-set agent to verify it gets invalidated
            client._agent = MagicMock()

            with (
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=tmp_path),
                patch("src.client.get_extensions_config", return_value=current_config),
                patch("src.client.reload_extensions_config", return_value=reloaded_config),
            ):
                result = client.update_mcp_config({"new-server": {"enabled": True, "type": "sse"}})

            assert "mcp_servers" in result
            assert "new-server" in result["mcp_servers"]
            assert client._agent is None  # M2: agent invalidated

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
            # Pre-set agent to verify it gets invalidated
            client._agent = MagicMock()

            with (
                patch("src.skills.loader.load_skills", side_effect=[[skill], [updated_skill]]),
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=tmp_path),
                patch("src.client.get_extensions_config", return_value=ext_config),
                patch("src.client.reload_extensions_config"),
            ):
                result = client.update_skill("test-skill", enabled=False)
            assert result["enabled"] is False
            assert client._agent is None  # M2: agent invalidated
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

            assert result["success"] is True
            assert len(result["files"]) == 1
            assert result["files"][0]["filename"] == "test.txt"
            assert "artifact_url" in result["files"][0]
            assert "message" in result
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

            assert result["count"] == 2
            assert len(result["files"]) == 2
            names = {f["filename"] for f in result["files"]}
            assert names == {"a.txt", "b.txt"}
            # Verify artifact_url is present
            for f in result["files"]:
                assert "artifact_url" in f

    def test_delete_upload(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            uploads_dir = Path(tmp)
            (uploads_dir / "delete-me.txt").write_text("gone")

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                result = client.delete_upload("thread-1", "delete-me.txt")

            assert result["success"] is True
            assert "delete-me.txt" in result["message"]
            assert not (uploads_dir / "delete-me.txt").exists()

    def test_delete_upload_not_found(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=Path(tmp)):
                with pytest.raises(FileNotFoundError):
                    client.delete_upload("thread-1", "nope.txt")

    def test_delete_upload_path_traversal(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            uploads_dir = Path(tmp)
            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                with pytest.raises(PermissionError):
                    client.delete_upload("thread-1", "../../etc/passwd")


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_get_artifact(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            user_data_dir = Path(tmp) / "user-data"
            outputs = user_data_dir / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "result.txt").write_text("artifact content")

            mock_paths = MagicMock()
            mock_paths.sandbox_user_data_dir.return_value = user_data_dir

            with patch("src.client.get_paths", return_value=mock_paths):
                content, mime = client.get_artifact("t1", "mnt/user-data/outputs/result.txt")

            assert content == b"artifact content"
            assert "text" in mime

    def test_get_artifact_not_found(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            user_data_dir = Path(tmp) / "user-data"
            user_data_dir.mkdir()

            mock_paths = MagicMock()
            mock_paths.sandbox_user_data_dir.return_value = user_data_dir

            with patch("src.client.get_paths", return_value=mock_paths):
                with pytest.raises(FileNotFoundError):
                    client.get_artifact("t1", "mnt/user-data/outputs/nope.txt")

    def test_get_artifact_bad_prefix(self, client):
        with pytest.raises(ValueError, match="must start with"):
            client.get_artifact("t1", "bad/path/file.txt")

    def test_get_artifact_path_traversal(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            user_data_dir = Path(tmp) / "user-data"
            user_data_dir.mkdir()

            mock_paths = MagicMock()
            mock_paths.sandbox_user_data_dir.return_value = user_data_dir

            with patch("src.client.get_paths", return_value=mock_paths):
                with pytest.raises(PermissionError):
                    client.get_artifact("t1", "mnt/user-data/../../../etc/passwd")


class TestReports:
    def test_export_image_report_pdf_from_payload(self, client):
        fake_index = {"thread_id": "t1", "reports": []}
        with (
            patch("src.config.scientific_vision_config.get_scientific_vision_config", return_value=SimpleNamespace(artifact_subdir="scientific-vision/image-reports")),
            patch("src.utils.image_report_pdf.generate_image_report_pdf", return_value="/mnt/user-data/outputs/scientific-vision/image-reports/pdfs/report.pdf"),
        ):
            result = client.export_image_report_pdf("t1", index_payload=fake_index)

        assert result["pdf_path"].endswith(".pdf")

    def test_export_image_report_pdf_requires_index(self, client):
        with pytest.raises(ValueError, match="Either index_path or index_payload"):
            client.export_image_report_pdf("t1")

    def test_export_latex_diagnostics_markdown(self, client):
        from src.config.paths import Paths

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.client.get_paths",
            return_value=Paths(base_dir=tmp),
        ):
            result = client.export_latex_diagnostics_markdown(
                "t1",
                title="Latex diag",
                compile_status="failed",
                compile_log_path="/mnt/user-data/outputs/research-writing/latex/p1.compile.log",
                issue_clusters=[
                    {
                        "id": "missing-package",
                        "title": "Missing package",
                        "severity": "error",
                        "match_count": 1,
                        "matched_lines": ["L31: ! LaTeX Error: File `booktabs.sty' not found."],
                        "suggestions": ["tlmgr install booktabs"],
                    }
                ],
                output_filename="diag.md",
            )
        assert result["report_path"].endswith("/research-writing/latex/reports/diag.md")


class TestResearchRuntime:
    def test_research_upsert_and_get_project(self, client):
        project_payload = {
            "project_id": "p1",
            "title": "Structured Research Project",
            "discipline": "ai_cs",
            "sections": [{"section_id": "intro", "section_name": "Introduction"}],
        }
        with (
            patch("src.research_writing.runtime_service.upsert_project", return_value=SimpleNamespace(model_dump=lambda: project_payload)),
            patch("src.research_writing.runtime_service.get_project", return_value=SimpleNamespace(model_dump=lambda: project_payload)),
        ):
            upsert_result = client.research_upsert_project("t1", project_payload)
            get_result = client.research_get_project("t1", "p1")
        assert upsert_result["project"]["project_id"] == "p1"
        assert get_result is not None
        assert get_result["project"]["title"] == "Structured Research Project"

    def test_research_ingest_compile_review_eval(self, client):
        with (
            patch(
                "src.research_writing.runtime_service.ingest_fulltext_evidence",
                return_value={
                    "record": {"source": "arxiv", "external_id": "2501.00001"},
                    "evidence_count": 2,
                    "persisted_evidence_ids": ["arxiv:2501.00001:p1"],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/artifacts/ingest-arxiv-2501.00001.json",
                },
            ),
            patch(
                "src.research_writing.runtime_service.compile_project_section",
                return_value={
                    "section_id": "intro",
                    "compiled_text": "Compiled section content",
                    "issues": [],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p1-intro.md",
                },
            ),
            patch(
                "src.research_writing.runtime_service.simulate_review_and_plan",
                return_value={
                    "venue": "NeurIPS",
                    "overall_assessment": "minor revision",
                    "comments": [],
                    "actions": [],
                    "rebuttal_letter": "Response to reviewers.",
                    "artifact_path": "/mnt/user-data/outputs/research-writing/review/review-neurips.json",
                    "letter_path": "/mnt/user-data/outputs/research-writing/review/review-neurips.md",
                },
            ),
            patch(
                "src.research_writing.runtime_service.evaluate_academic_and_persist",
                return_value={
                    "case_count": 1,
                    "average_overall_score": 0.8,
                    "average_citation_fidelity": 0.9,
                    "average_claim_grounding": 0.8,
                    "average_abstract_body_consistency": 0.7,
                    "average_reviewer_rebuttal_completeness": 0.8,
                    "average_venue_fit": 0.8,
                    "average_cross_modality_synthesis": 0.9,
                    "average_long_horizon_consistency": 0.7,
                    "results": [],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/evals/eval.json",
                },
            ),
        ):
            ingest = client.research_ingest_fulltext("t1", source="arxiv", external_id="2501.00001")
            compiled = client.research_compile_section("t1", project_id="p1", section_id="intro")
            review = client.research_simulate_review("t1", venue_name="NeurIPS", manuscript_text="A complete manuscript text.")
            eval_result = client.research_evaluate_academic(
                "t1",
                cases=[
                    {
                        "case_id": "c1",
                        "domain": "ai_cs",
                        "venue": "NeurIPS",
                        "generated_citations": [],
                        "verified_citations": [],
                        "claims": [],
                        "abstract_numbers": [],
                        "body_numbers": [],
                        "reviewer_comment_ids": [],
                        "rebuttal_addressed_ids": [],
                        "venue_checklist_items": [],
                        "venue_satisfied_items": [],
                        "cross_modal_items_expected": 0,
                        "cross_modal_items_used": 0,
                        "revision_terms": [],
                        "revision_numbers": [],
                    }
                ],
            )
        assert ingest["evidence_count"] == 2
        assert compiled["section_id"] == "intro"
        assert review["venue"] == "NeurIPS"
        assert eval_result["case_count"] == 1

    def test_research_peer_review_loop_and_hypothesis_generation(self, client):
        with (
            patch(
                "src.research_writing.runtime_service.simulate_peer_review_cycle",
                return_value={
                    "venue": "NeurIPS",
                    "section_id": "discussion",
                    "red_team_agents": ["reviewer_agent", "area_chair_agent"],
                    "blue_team_agents": ["author_agent"],
                    "rounds": [],
                    "final_text": "revised",
                    "final_decision": "accept",
                    "unresolved_issue_count": 0,
                    "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.json",
                    "final_text_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.md",
                },
            ) as peer_mock,
            patch(
                "src.research_writing.runtime_service.generate_project_hypotheses",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "feature_summary": ["Evidence coverage: 2 units."],
                    "hypotheses": [{"hypothesis_id": "H1"}],
                    "synthesis_paragraph": "Top-ranked hypothesis ...",
                    "artifact_path": "/mnt/user-data/outputs/research-writing/hypotheses/hypothesis-p1-discussion.json",
                },
            ),
        ):
            peer = client.research_simulate_peer_review_loop(
                "t1",
                venue_name="NeurIPS",
                manuscript_text="draft",
                section_id="discussion",
                reviewer2_styles=["statistical_tyrant", "domain_traditionalist"],
                peer_review_ab_variant="B",
            )
            hypothesis = client.research_generate_hypotheses(
                "t1",
                project_id="p1",
                section_id="discussion",
            )

        assert peer["final_decision"] == "accept"
        assert hypothesis["project_id"] == "p1"
        _, peer_kwargs = peer_mock.call_args
        assert peer_kwargs["reviewer2_styles"] == ["statistical_tyrant", "domain_traditionalist"]
        assert peer_kwargs["peer_review_ab_variant"] == "B"

    def test_research_compile_latex(self, client):
        with patch(
            "src.research_writing.runtime_service.build_latex_manuscript",
            return_value={
                "project_id": "p1",
                "section_ids": ["discussion"],
                "title": "Paper",
                "source_markdown_path": "/mnt/user-data/outputs/research-writing/latex/p1.source.md",
                "tex_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
                "pdf_path": "/mnt/user-data/outputs/research-writing/latex/p1.pdf",
                "compile_log_path": "/mnt/user-data/outputs/research-writing/latex/p1.compile.log",
                "compile_status": "success",
                "compiler": "latexmk",
                "engine_requested": "auto",
                "compile_pdf_requested": True,
                "citation_keys": ["10.1000/demo"],
                "citation_count": 1,
                "warning": None,
                "artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
                "summary_artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.json",
            },
        ):
            latex = client.research_compile_latex("t1", project_id="p1", section_ids=["discussion"], compile_pdf=True)
        assert latex["compile_status"] == "success"
        assert latex["pdf_path"].endswith(".pdf")

    def test_research_plan_narrative(self, client):
        with patch(
            "src.research_writing.runtime_service.plan_project_section_narrative",
            return_value={
                "project_id": "p1",
                "section_id": "intro",
                "section_name": "Introduction",
                "planner_version": "deerflow.narrative_plan.v1",
                "takeaway_message": "Takeaway",
                "gap_statement": "Gap",
                "disruption_statement": "Disruption",
                "logical_flow": ["f1", "f2"],
                "figure_storyboard": [{"figure_id": "F1"}],
                "self_questioning": [{"round_index": 1}],
                "introduction_hook": "hook",
                "discussion_pivot": "pivot",
                "self_question_rounds": 3,
                "include_storyboard": True,
                "artifact_path": "/mnt/user-data/outputs/research-writing/narrative-plans/p1-intro.json",
            },
        ):
            payload = client.research_plan_narrative("t1", project_id="p1", section_id="intro", self_question_rounds=3)
        assert payload["planner_version"] == "deerflow.narrative_plan.v1"
        assert payload["self_question_rounds"] == 3

    def test_research_hitl_decisions_roundtrip(self, client):
        with (
            patch(
                "src.research_writing.runtime_service.upsert_project_hitl_decisions",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "decisions": [
                        {
                            "action_id": "peer-r1-abc",
                            "source": "Peer Loop Round 1",
                            "label": "Add ablation",
                            "decision": "approved",
                            "section_id": "discussion",
                            "updated_at": "2026-03-16T00:00:00Z",
                            "metadata": {},
                        }
                    ],
                    "total_count": 1,
                    "updated_at": "2026-03-16T00:00:00Z",
                    "artifact_path": "/mnt/user-data/outputs/research-writing/hitl/hitl-decisions-p1.json",
                },
            ),
            patch(
                "src.research_writing.runtime_service.get_project_hitl_decisions",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "decisions": [
                        {
                            "action_id": "peer-r1-abc",
                            "source": "Peer Loop Round 1",
                            "label": "Add ablation",
                            "decision": "approved",
                            "section_id": "discussion",
                            "updated_at": "2026-03-16T00:00:00Z",
                            "metadata": {},
                        }
                    ],
                    "total_count": 1,
                    "updated_at": "2026-03-16T00:00:00Z",
                },
            ),
        ):
            upserted = client.research_upsert_hitl_decisions(
                "t1",
                project_id="p1",
                section_id="discussion",
                decisions=[
                    {
                        "action_id": "peer-r1-abc",
                        "source": "Peer Loop Round 1",
                        "label": "Add ablation",
                        "decision": "approved",
                    }
                ],
            )
            fetched = client.research_get_hitl_decisions(
                "t1",
                project_id="p1",
                section_id="discussion",
            )

        assert upserted["total_count"] == 1
        assert fetched["total_count"] == 1
        assert fetched["decisions"][0]["decision"] == "approved"

    def test_research_policy_snapshot_and_compliance_and_self_play(self, client):
        with (
            patch(
                "src.research_writing.runtime_service.get_project_policy_snapshot",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "policy_snapshot": {"signal_count": 2, "recommended_tone": "conservative"},
                    "artifact_path": "/mnt/user-data/outputs/research-writing/policy/policy-p1-discussion.json",
                },
            ),
            patch(
                "src.research_writing.runtime_service.audit_project_section_compliance",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "compliance_audit": {"risk_level": "high"},
                    "artifact_path": "/mnt/user-data/outputs/research-writing/compliance/audit-p1-discussion.json",
                },
            ),
            patch(
                "src.research_writing.runtime_service.run_peer_self_play_training",
                return_value={
                    "schema_version": "deerflow.self_play_training.v1",
                    "generated_at": "2026-03-16T00:00:00Z",
                    "run_name": "peer-self-play",
                    "total_episodes": 1,
                    "accepted_episodes": 0,
                    "hard_negative_count": 1,
                    "hard_negative_rate": 1.0,
                    "episodes": [{"episode_id": "ep-1"}],
                    "hard_negatives": [{"hard_negative_id": "hn-1"}],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.json",
                    "hard_negatives_artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.hard-negatives.json",
                },
            ),
            patch(
                "src.research_writing.runtime_service.get_weekly_academic_leaderboard",
                return_value={
                    "schema_version": "deerflow.academic_leaderboard.v1",
                    "cadence": "weekly",
                    "updated_at": "2026-03-16T00:00:00Z",
                    "buckets": [{"discipline": "ai_cs", "venue": "NeurIPS", "entries": []}],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/evals/leaderboard/weekly.json",
                },
            ),
        ):
            policy = client.research_get_policy_snapshot("t1", project_id="p1", section_id="discussion")
            compliance = client.research_audit_compliance("t1", project_id="p1", section_id="discussion")
            self_play = client.research_run_self_play_training(
                "t1",
                episodes=[{"episode_id": "ep-1", "manuscript_text": "draft"}],
                max_rounds=2,
            )
            leaderboard = client.research_get_academic_leaderboard("t1")

        assert policy["policy_snapshot"]["signal_count"] == 2
        assert compliance["compliance_audit"]["risk_level"] == "high"
        assert self_play["hard_negative_count"] == 1
        assert leaderboard["schema_version"] == "deerflow.academic_leaderboard.v1"


# ===========================================================================
# Scenario-based integration tests
# ===========================================================================
# These tests simulate realistic user workflows end-to-end, exercising
# multiple methods in sequence to verify they compose correctly.


class TestScenarioMultiTurnConversation:
    """Scenario: User has a multi-turn conversation within a single thread."""

    def test_two_turn_conversation(self, client):
        """Two sequential chat() calls on the same thread_id produce
        independent results (without checkpointer, each call is stateless)."""
        ai1 = AIMessage(content="I'm a helpful assistant.", id="ai-1")
        ai2 = AIMessage(content="Python is great!", id="ai-2")

        agent = MagicMock()
        agent.stream.side_effect = [
            iter([{"messages": [HumanMessage(content="who are you?", id="h-1"), ai1]}]),
            iter([{"messages": [HumanMessage(content="what language?", id="h-2"), ai2]}]),
        ]

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            r1 = client.chat("who are you?", thread_id="thread-multi")
            r2 = client.chat("what language?", thread_id="thread-multi")

        assert r1 == "I'm a helpful assistant."
        assert r2 == "Python is great!"
        assert agent.stream.call_count == 2

    def test_stream_collects_all_event_types_across_turns(self, client):
        """A full turn emits messages-tuple (tool_call, tool_result, ai text) + values + end."""
        ai_tc = AIMessage(
            content="",
            id="ai-1",
            tool_calls=[
                {"name": "web_search", "args": {"query": "LangGraph"}, "id": "tc-1"},
            ],
        )
        tool_r = ToolMessage(content="LangGraph is a framework...", id="tm-1", tool_call_id="tc-1", name="web_search")
        ai_final = AIMessage(content="LangGraph is a framework for building agents.", id="ai-2")

        chunks = [
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tc]},
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tc, tool_r]},
            {"messages": [HumanMessage(content="search", id="h-1"), ai_tc, tool_r, ai_final], "title": "LangGraph Search"},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("search", thread_id="t-full"))

        # Verify expected event types
        types = set(e.type for e in events)
        assert types == {"messages-tuple", "values", "end"}
        assert events[-1].type == "end"

        # Verify tool_call data
        tc_events = _tool_call_events(events)
        assert len(tc_events) == 1
        assert tc_events[0].data["tool_calls"][0]["name"] == "web_search"
        assert tc_events[0].data["tool_calls"][0]["args"] == {"query": "LangGraph"}

        # Verify tool_result data
        tr_events = _tool_result_events(events)
        assert len(tr_events) == 1
        assert tr_events[0].data["tool_call_id"] == "tc-1"
        assert "LangGraph" in tr_events[0].data["content"]

        # Verify AI text
        msg_events = _ai_events(events)
        assert any("framework" in e.data["content"] for e in msg_events)

        # Verify values event contains title
        values_events = [e for e in events if e.type == "values"]
        assert any(e.data.get("title") == "LangGraph Search" for e in values_events)


class TestScenarioToolChain:
    """Scenario: Agent chains multiple tool calls in sequence."""

    def test_multi_tool_chain(self, client):
        """Agent calls bash → reads output → calls write_file → responds."""
        ai_bash = AIMessage(
            content="",
            id="ai-1",
            tool_calls=[
                {"name": "bash", "args": {"cmd": "ls /mnt/user-data/workspace"}, "id": "tc-1"},
            ],
        )
        bash_result = ToolMessage(content="README.md\nsrc/", id="tm-1", tool_call_id="tc-1", name="bash")
        ai_write = AIMessage(
            content="",
            id="ai-2",
            tool_calls=[
                {"name": "write_file", "args": {"path": "/mnt/user-data/outputs/listing.txt", "content": "README.md\nsrc/"}, "id": "tc-2"},
            ],
        )
        write_result = ToolMessage(content="File written successfully.", id="tm-2", tool_call_id="tc-2", name="write_file")
        ai_final = AIMessage(content="I listed the workspace and saved the output.", id="ai-3")

        chunks = [
            {"messages": [HumanMessage(content="list and save", id="h-1"), ai_bash]},
            {"messages": [HumanMessage(content="list and save", id="h-1"), ai_bash, bash_result]},
            {"messages": [HumanMessage(content="list and save", id="h-1"), ai_bash, bash_result, ai_write]},
            {"messages": [HumanMessage(content="list and save", id="h-1"), ai_bash, bash_result, ai_write, write_result]},
            {"messages": [HumanMessage(content="list and save", id="h-1"), ai_bash, bash_result, ai_write, write_result, ai_final]},
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("list and save", thread_id="t-chain"))

        tool_calls = _tool_call_events(events)
        tool_results = _tool_result_events(events)
        messages = _ai_events(events)

        assert len(tool_calls) == 2
        assert tool_calls[0].data["tool_calls"][0]["name"] == "bash"
        assert tool_calls[1].data["tool_calls"][0]["name"] == "write_file"
        assert len(tool_results) == 2
        assert len(messages) == 1
        assert events[-1].type == "end"


class TestScenarioFileLifecycle:
    """Scenario: Upload files → list them → use in chat → download artifact."""

    def test_upload_list_delete_lifecycle(self, client):
        """Upload → list → verify → delete → list again."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir()

            # Create source files
            (tmp_path / "report.txt").write_text("quarterly report data")
            (tmp_path / "data.csv").write_text("a,b,c\n1,2,3")

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                # Step 1: Upload
                result = client.upload_files(
                    "t-lifecycle",
                    [
                        tmp_path / "report.txt",
                        tmp_path / "data.csv",
                    ],
                )
                assert result["success"] is True
                assert len(result["files"]) == 2
                assert {f["filename"] for f in result["files"]} == {"report.txt", "data.csv"}

                # Step 2: List
                listed = client.list_uploads("t-lifecycle")
                assert listed["count"] == 2
                assert all("virtual_path" in f for f in listed["files"])

                # Step 3: Delete one
                del_result = client.delete_upload("t-lifecycle", "report.txt")
                assert del_result["success"] is True

                # Step 4: Verify deletion
                listed = client.list_uploads("t-lifecycle")
                assert listed["count"] == 1
                assert listed["files"][0]["filename"] == "data.csv"

    def test_upload_then_read_artifact(self, client):
        """Upload a file, simulate agent producing artifact, read it back."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir()
            user_data_dir = tmp_path / "user-data"
            outputs_dir = user_data_dir / "outputs"
            outputs_dir.mkdir(parents=True)

            # Upload phase
            src_file = tmp_path / "input.txt"
            src_file.write_text("raw data to process")

            with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
                uploaded = client.upload_files("t-artifact", [src_file])
                assert len(uploaded["files"]) == 1

            # Simulate agent writing an artifact
            (outputs_dir / "analysis.json").write_text('{"result": "processed"}')

            # Retrieve artifact
            mock_paths = MagicMock()
            mock_paths.sandbox_user_data_dir.return_value = user_data_dir

            with patch("src.client.get_paths", return_value=mock_paths):
                content, mime = client.get_artifact("t-artifact", "mnt/user-data/outputs/analysis.json")

            assert json.loads(content) == {"result": "processed"}
            assert "json" in mime


class TestScenarioConfigManagement:
    """Scenario: Query and update configuration through a management session."""

    def test_model_and_skill_discovery(self, client):
        """List models → get specific model → list skills → get specific skill."""
        # List models
        result = client.list_models()
        assert len(result["models"]) >= 1
        model_name = result["models"][0]["name"]

        # Get specific model
        model_cfg = MagicMock()
        model_cfg.name = model_name
        model_cfg.display_name = None
        model_cfg.description = None
        model_cfg.supports_thinking = False
        model_cfg.supports_reasoning_effort = False
        client._app_config.get_model_config.return_value = model_cfg
        detail = client.get_model(model_name)
        assert detail["name"] == model_name

        # List skills
        skill = MagicMock()
        skill.name = "web-search"
        skill.description = "Search the web"
        skill.license = "MIT"
        skill.category = "public"
        skill.enabled = True

        with patch("src.skills.loader.load_skills", return_value=[skill]):
            skills_result = client.list_skills()
        assert len(skills_result["skills"]) == 1

        # Get specific skill
        with patch("src.skills.loader.load_skills", return_value=[skill]):
            detail = client.get_skill("web-search")
        assert detail is not None
        assert detail["enabled"] is True

    def test_mcp_update_then_skill_toggle(self, client):
        """Update MCP config → toggle skill → verify both invalidate agent."""
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "extensions_config.json"
            config_file.write_text("{}")

            # --- MCP update ---
            current_config = MagicMock()
            current_config.skills = {}

            reloaded_server = MagicMock()
            reloaded_server.model_dump.return_value = {"enabled": True, "type": "sse"}
            reloaded_config = MagicMock()
            reloaded_config.mcp_servers = {"my-mcp": reloaded_server}

            client._agent = MagicMock()  # Simulate existing agent
            with (
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
                patch("src.client.get_extensions_config", return_value=current_config),
                patch("src.client.reload_extensions_config", return_value=reloaded_config),
            ):
                mcp_result = client.update_mcp_config({"my-mcp": {"enabled": True}})
            assert "my-mcp" in mcp_result["mcp_servers"]
            assert client._agent is None  # Agent invalidated

            # --- Skill toggle ---
            skill = MagicMock()
            skill.name = "code-gen"
            skill.description = "Generate code"
            skill.license = "MIT"
            skill.category = "custom"
            skill.enabled = True

            toggled = MagicMock()
            toggled.name = "code-gen"
            toggled.description = "Generate code"
            toggled.license = "MIT"
            toggled.category = "custom"
            toggled.enabled = False

            ext_config = MagicMock()
            ext_config.mcp_servers = {}
            ext_config.skills = {}

            client._agent = MagicMock()  # Simulate re-created agent
            with (
                patch("src.skills.loader.load_skills", side_effect=[[skill], [toggled]]),
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
                patch("src.client.get_extensions_config", return_value=ext_config),
                patch("src.client.reload_extensions_config"),
            ):
                skill_result = client.update_skill("code-gen", enabled=False)
            assert skill_result["enabled"] is False
            assert client._agent is None  # Agent invalidated again


class TestScenarioAgentRecreation:
    """Scenario: Config changes trigger agent recreation at the right times."""

    def test_different_model_triggers_rebuild(self, client):
        """Switching model_name between calls forces agent rebuild."""
        agents_created = []

        def fake_create_agent(**kwargs):
            agent = MagicMock()
            agents_created.append(agent)
            return agent

        config_a = client._get_runnable_config("t1", model_name="gpt-4")
        config_b = client._get_runnable_config("t1", model_name="claude-3")

        with (
            patch("src.client.create_chat_model"),
            patch("src.client.create_agent", side_effect=fake_create_agent),
            patch("src.client._build_middlewares", return_value=[]),
            patch("src.client.apply_prompt_template", return_value="prompt"),
            patch.object(client, "_get_tools", return_value=[]),
        ):
            client._ensure_agent(config_a)
            first_agent = client._agent

            client._ensure_agent(config_b)
            second_agent = client._agent

        assert len(agents_created) == 2
        assert first_agent is not second_agent

    def test_same_config_reuses_agent(self, client):
        """Repeated calls with identical config do not rebuild."""
        agents_created = []

        def fake_create_agent(**kwargs):
            agent = MagicMock()
            agents_created.append(agent)
            return agent

        config = client._get_runnable_config("t1", model_name="gpt-4")

        with (
            patch("src.client.create_chat_model"),
            patch("src.client.create_agent", side_effect=fake_create_agent),
            patch("src.client._build_middlewares", return_value=[]),
            patch("src.client.apply_prompt_template", return_value="prompt"),
            patch.object(client, "_get_tools", return_value=[]),
        ):
            client._ensure_agent(config)
            client._ensure_agent(config)
            client._ensure_agent(config)

        assert len(agents_created) == 1

    def test_reset_agent_forces_rebuild(self, client):
        """reset_agent() clears cache, next call rebuilds."""
        agents_created = []

        def fake_create_agent(**kwargs):
            agent = MagicMock()
            agents_created.append(agent)
            return agent

        config = client._get_runnable_config("t1")

        with (
            patch("src.client.create_chat_model"),
            patch("src.client.create_agent", side_effect=fake_create_agent),
            patch("src.client._build_middlewares", return_value=[]),
            patch("src.client.apply_prompt_template", return_value="prompt"),
            patch.object(client, "_get_tools", return_value=[]),
        ):
            client._ensure_agent(config)
            client.reset_agent()
            client._ensure_agent(config)

        assert len(agents_created) == 2

    def test_per_call_override_triggers_rebuild(self, client):
        """stream() with model_name override creates a different agent config."""
        ai = AIMessage(content="ok", id="ai-1")
        agent = _make_agent_mock([{"messages": [ai]}])

        agents_created = []

        def fake_ensure(config):
            key = tuple(config.get("configurable", {}).get(k) for k in ["model_name", "thinking_enabled", "is_plan_mode", "subagent_enabled"])
            agents_created.append(key)
            client._agent = agent

        with patch.object(client, "_ensure_agent", side_effect=fake_ensure):
            list(client.stream("hi", thread_id="t1"))
            list(client.stream("hi", thread_id="t1", model_name="other-model"))

        # Two different config keys should have been created
        assert len(agents_created) == 2
        assert agents_created[0] != agents_created[1]


class TestScenarioThreadIsolation:
    """Scenario: Operations on different threads don't interfere."""

    def test_uploads_isolated_per_thread(self, client):
        """Files uploaded to thread-A are not visible in thread-B."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            uploads_a = tmp_path / "thread-a" / "uploads"
            uploads_b = tmp_path / "thread-b" / "uploads"
            uploads_a.mkdir(parents=True)
            uploads_b.mkdir(parents=True)

            src_file = tmp_path / "secret.txt"
            src_file.write_text("thread-a only")

            def get_dir(thread_id):
                return uploads_a if thread_id == "thread-a" else uploads_b

            with patch.object(DeerFlowClient, "_get_uploads_dir", side_effect=get_dir):
                client.upload_files("thread-a", [src_file])

                files_a = client.list_uploads("thread-a")
                files_b = client.list_uploads("thread-b")

            assert files_a["count"] == 1
            assert files_b["count"] == 0

    def test_artifacts_isolated_per_thread(self, client):
        """Artifacts in thread-A are not accessible from thread-B."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            data_a = tmp_path / "thread-a"
            data_b = tmp_path / "thread-b"
            (data_a / "outputs").mkdir(parents=True)
            (data_b / "outputs").mkdir(parents=True)
            (data_a / "outputs" / "result.txt").write_text("thread-a artifact")

            mock_paths = MagicMock()
            mock_paths.sandbox_user_data_dir.side_effect = lambda tid: data_a if tid == "thread-a" else data_b

            with patch("src.client.get_paths", return_value=mock_paths):
                content, _ = client.get_artifact("thread-a", "mnt/user-data/outputs/result.txt")
                assert content == b"thread-a artifact"

                with pytest.raises(FileNotFoundError):
                    client.get_artifact("thread-b", "mnt/user-data/outputs/result.txt")


class TestScenarioMemoryWorkflow:
    """Scenario: Memory query → reload → status check."""

    def test_memory_full_lifecycle(self, client):
        """get_memory → reload → get_status covers the full memory API."""
        initial_data = {"version": "1.0", "facts": [{"id": "f1", "content": "User likes Python"}]}
        updated_data = {
            "version": "1.0",
            "facts": [
                {"id": "f1", "content": "User likes Python"},
                {"id": "f2", "content": "User prefers dark mode"},
            ],
        }

        config = MagicMock()
        config.enabled = True
        config.storage_path = ".deer-flow/memory.json"
        config.debounce_seconds = 30
        config.max_facts = 100
        config.fact_confidence_threshold = 0.7
        config.injection_enabled = True
        config.max_injection_tokens = 2000

        with patch("src.agents.memory.updater.get_memory_data", return_value=initial_data):
            mem = client.get_memory()
        assert len(mem["facts"]) == 1

        with patch("src.agents.memory.updater.reload_memory_data", return_value=updated_data):
            refreshed = client.reload_memory()
        assert len(refreshed["facts"]) == 2

        with (
            patch("src.config.memory_config.get_memory_config", return_value=config),
            patch("src.agents.memory.updater.get_memory_data", return_value=updated_data),
        ):
            status = client.get_memory_status()
        assert status["config"]["enabled"] is True
        assert len(status["data"]["facts"]) == 2


class TestScenarioSkillInstallAndUse:
    """Scenario: Install a skill → verify it appears → toggle it."""

    def test_install_then_toggle(self, client):
        """Install .skill archive → list to verify → disable → verify disabled."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create .skill archive
            skill_src = tmp_path / "my-analyzer"
            skill_src.mkdir()
            (skill_src / "SKILL.md").write_text("---\nname: my-analyzer\ndescription: Analyze code\nlicense: MIT\n---\nAnalysis skill")
            archive = tmp_path / "my-analyzer.skill"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.write(skill_src / "SKILL.md", "my-analyzer/SKILL.md")

            skills_root = tmp_path / "skills"
            (skills_root / "custom").mkdir(parents=True)

            # Step 1: Install
            with (
                patch("src.skills.loader.get_skills_root_path", return_value=skills_root),
                patch("src.gateway.routers.skills._validate_skill_frontmatter", return_value=(True, "OK", "my-analyzer")),
            ):
                result = client.install_skill(archive)
            assert result["success"] is True
            assert (skills_root / "custom" / "my-analyzer" / "SKILL.md").exists()

            # Step 2: List and find it
            installed_skill = MagicMock()
            installed_skill.name = "my-analyzer"
            installed_skill.description = "Analyze code"
            installed_skill.license = "MIT"
            installed_skill.category = "custom"
            installed_skill.enabled = True

            with patch("src.skills.loader.load_skills", return_value=[installed_skill]):
                skills_result = client.list_skills()
            assert any(s["name"] == "my-analyzer" for s in skills_result["skills"])

            # Step 3: Disable it
            disabled_skill = MagicMock()
            disabled_skill.name = "my-analyzer"
            disabled_skill.description = "Analyze code"
            disabled_skill.license = "MIT"
            disabled_skill.category = "custom"
            disabled_skill.enabled = False

            ext_config = MagicMock()
            ext_config.mcp_servers = {}
            ext_config.skills = {}

            config_file = tmp_path / "extensions_config.json"
            config_file.write_text("{}")

            with (
                patch("src.skills.loader.load_skills", side_effect=[[installed_skill], [disabled_skill]]),
                patch("src.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
                patch("src.client.get_extensions_config", return_value=ext_config),
                patch("src.client.reload_extensions_config"),
            ):
                toggled = client.update_skill("my-analyzer", enabled=False)
            assert toggled["enabled"] is False


class TestScenarioEdgeCases:
    """Scenario: Edge cases and error boundaries in realistic workflows."""

    def test_empty_stream_response(self, client):
        """Agent produces no messages — only values + end events."""
        agent = _make_agent_mock([{"messages": []}])

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t-empty"))

        # values event (empty messages) + end
        assert len(events) == 2
        assert events[0].type == "values"
        assert events[-1].type == "end"

    def test_chat_on_empty_response(self, client):
        """chat() returns empty string for no-message response."""
        agent = _make_agent_mock([{"messages": []}])

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            result = client.chat("hi", thread_id="t-empty-chat")

        assert result == ""

    def test_multiple_title_changes(self, client):
        """Title changes are carried in values events."""
        ai = AIMessage(content="ok", id="ai-1")
        chunks = [
            {"messages": [ai], "title": "First Title"},
            {"messages": [], "title": "First Title"},  # same title repeated
            {"messages": [], "title": "Second Title"},  # different title
        ]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("hi", thread_id="t-titles"))

        # Every chunk produces a values event with the title
        values_events = [e for e in events if e.type == "values"]
        assert len(values_events) == 3
        assert values_events[0].data["title"] == "First Title"
        assert values_events[1].data["title"] == "First Title"
        assert values_events[2].data["title"] == "Second Title"

    def test_concurrent_tool_calls_in_single_message(self, client):
        """Agent produces multiple tool_calls in one AIMessage — emitted as single messages-tuple."""
        ai = AIMessage(
            content="",
            id="ai-1",
            tool_calls=[
                {"name": "web_search", "args": {"q": "a"}, "id": "tc-1"},
                {"name": "web_search", "args": {"q": "b"}, "id": "tc-2"},
                {"name": "bash", "args": {"cmd": "echo hi"}, "id": "tc-3"},
            ],
        )
        chunks = [{"messages": [ai]}]
        agent = _make_agent_mock(chunks)

        with (
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", agent),
        ):
            events = list(client.stream("do things", thread_id="t-parallel"))

        tc_events = _tool_call_events(events)
        assert len(tc_events) == 1  # One messages-tuple event for the AIMessage
        tool_calls = tc_events[0].data["tool_calls"]
        assert len(tool_calls) == 3
        assert {tc["id"] for tc in tool_calls} == {"tc-1", "tc-2", "tc-3"}

    def test_upload_convertible_file_conversion_failure(self, client):
        """Upload a .pdf file where conversion fails — file still uploaded, no markdown."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            uploads_dir = tmp_path / "uploads"
            uploads_dir.mkdir()

            pdf_file = tmp_path / "doc.pdf"
            pdf_file.write_bytes(b"%PDF-1.4 fake content")

            with (
                patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir),
                patch("src.gateway.routers.uploads.CONVERTIBLE_EXTENSIONS", {".pdf"}),
                patch("src.gateway.routers.uploads.convert_file_to_markdown", side_effect=Exception("conversion failed")),
            ):
                result = client.upload_files("t-pdf-fail", [pdf_file])

            assert result["success"] is True
            assert len(result["files"]) == 1
            assert result["files"][0]["filename"] == "doc.pdf"
            assert "markdown_file" not in result["files"][0]  # Conversion failed gracefully
            assert (uploads_dir / "doc.pdf").exists()  # File still uploaded


# ---------------------------------------------------------------------------
# Gateway conformance — validate client output against Gateway Pydantic models
# ---------------------------------------------------------------------------


class TestGatewayConformance:
    """Validate that DeerFlowClient return dicts conform to Gateway Pydantic response models.

    Each test calls a client method, then parses the result through the
    corresponding Gateway response model. If the client drifts (missing or
    wrong-typed fields), Pydantic raises ``ValidationError`` and CI catches it.
    """

    def test_list_models(self, mock_app_config):
        model = MagicMock()
        model.name = "test-model"
        model.display_name = "Test Model"
        model.description = "A test model"
        model.supports_thinking = False
        mock_app_config.models = [model]

        with patch("src.client.get_app_config", return_value=mock_app_config):
            client = DeerFlowClient()

        result = client.list_models()
        parsed = ModelsListResponse(**result)
        assert len(parsed.models) == 1
        assert parsed.models[0].name == "test-model"

    def test_get_model(self, mock_app_config):
        model = MagicMock()
        model.name = "test-model"
        model.display_name = "Test Model"
        model.description = "A test model"
        model.supports_thinking = True
        mock_app_config.models = [model]
        mock_app_config.get_model_config.return_value = model

        with patch("src.client.get_app_config", return_value=mock_app_config):
            client = DeerFlowClient()

        result = client.get_model("test-model")
        assert result is not None
        parsed = ModelResponse(**result)
        assert parsed.name == "test-model"

    def test_list_skills(self, client):
        skill = MagicMock()
        skill.name = "web-search"
        skill.description = "Search the web"
        skill.license = "MIT"
        skill.category = "public"
        skill.enabled = True

        with patch("src.skills.loader.load_skills", return_value=[skill]):
            result = client.list_skills()

        parsed = SkillsListResponse(**result)
        assert len(parsed.skills) == 1
        assert parsed.skills[0].name == "web-search"

    def test_get_skill(self, client):
        skill = MagicMock()
        skill.name = "web-search"
        skill.description = "Search the web"
        skill.license = "MIT"
        skill.category = "public"
        skill.enabled = True

        with patch("src.skills.loader.load_skills", return_value=[skill]):
            result = client.get_skill("web-search")

        assert result is not None
        parsed = SkillResponse(**result)
        assert parsed.name == "web-search"

    def test_install_skill(self, client, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\nBody\n")

        archive = tmp_path / "my-skill.skill"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(skill_dir / "SKILL.md", "my-skill/SKILL.md")

        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        with patch("src.skills.loader.get_skills_root_path", return_value=tmp_path):
            result = client.install_skill(archive)

        parsed = SkillInstallResponse(**result)
        assert parsed.success is True
        assert parsed.skill_name == "my-skill"

    def test_get_mcp_config(self, client):
        server = MagicMock()
        server.model_dump.return_value = {
            "enabled": True,
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "server"],
            "env": {},
            "url": None,
            "headers": {},
            "description": "test server",
        }
        ext_config = MagicMock()
        ext_config.mcp_servers = {"test": server}

        with patch("src.client.get_extensions_config", return_value=ext_config):
            result = client.get_mcp_config()

        parsed = McpConfigResponse(**result)
        assert "test" in parsed.mcp_servers

    def test_update_mcp_config(self, client, tmp_path):
        server = MagicMock()
        server.model_dump.return_value = {
            "enabled": True,
            "type": "stdio",
            "command": "npx",
            "args": [],
            "env": {},
            "url": None,
            "headers": {},
            "description": "",
        }
        ext_config = MagicMock()
        ext_config.mcp_servers = {"srv": server}
        ext_config.skills = {}

        config_file = tmp_path / "extensions_config.json"
        config_file.write_text("{}")

        with (
            patch("src.client.get_extensions_config", return_value=ext_config),
            patch("src.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
            patch("src.client.reload_extensions_config", return_value=ext_config),
        ):
            result = client.update_mcp_config({"srv": server.model_dump.return_value})

        parsed = McpConfigResponse(**result)
        assert "srv" in parsed.mcp_servers

    def test_upload_files(self, client, tmp_path):
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()

        src_file = tmp_path / "hello.txt"
        src_file.write_text("hello")

        with patch.object(DeerFlowClient, "_get_uploads_dir", return_value=uploads_dir):
            result = client.upload_files("t-conform", [src_file])

        parsed = UploadResponse(**result)
        assert parsed.success is True
        assert len(parsed.files) == 1

    def test_get_memory_config(self, client):
        mem_cfg = MagicMock()
        mem_cfg.enabled = True
        mem_cfg.storage_path = ".deer-flow/memory.json"
        mem_cfg.debounce_seconds = 30
        mem_cfg.max_facts = 100
        mem_cfg.fact_confidence_threshold = 0.7
        mem_cfg.injection_enabled = True
        mem_cfg.max_injection_tokens = 2000
        mem_cfg.long_horizon_storage_path = ".deer-flow/long-horizon-memory.json"
        mem_cfg.long_horizon_enabled = True
        mem_cfg.long_horizon_max_entries = 500
        mem_cfg.long_horizon_summary_chars = 900
        mem_cfg.long_horizon_injection_enabled = True
        mem_cfg.long_horizon_top_k = 5
        mem_cfg.long_horizon_min_similarity = 0.12
        mem_cfg.long_horizon_injection_max_chars = 2400
        mem_cfg.long_horizon_embedding_dim = 256
        mem_cfg.long_horizon_cross_thread_enabled = True
        mem_cfg.long_horizon_topic_memory_enabled = True
        mem_cfg.long_horizon_topic_top_k = 2
        mem_cfg.long_horizon_project_memory_enabled = True
        mem_cfg.long_horizon_project_top_k = 2
        mem_cfg.long_horizon_current_thread_boost = 0.08
        mem_cfg.long_horizon_project_boost = 0.12
        mem_cfg.long_horizon_topic_overlap_boost = 0.03

        with patch("src.config.memory_config.get_memory_config", return_value=mem_cfg):
            result = client.get_memory_config()

        parsed = MemoryConfigResponse(**result)
        assert parsed.enabled is True
        assert parsed.max_facts == 100

    def test_get_memory_status(self, client):
        mem_cfg = MagicMock()
        mem_cfg.enabled = True
        mem_cfg.storage_path = ".deer-flow/memory.json"
        mem_cfg.debounce_seconds = 30
        mem_cfg.max_facts = 100
        mem_cfg.fact_confidence_threshold = 0.7
        mem_cfg.injection_enabled = True
        mem_cfg.max_injection_tokens = 2000
        mem_cfg.long_horizon_storage_path = ".deer-flow/long-horizon-memory.json"
        mem_cfg.long_horizon_enabled = True
        mem_cfg.long_horizon_max_entries = 500
        mem_cfg.long_horizon_summary_chars = 900
        mem_cfg.long_horizon_injection_enabled = True
        mem_cfg.long_horizon_top_k = 5
        mem_cfg.long_horizon_min_similarity = 0.12
        mem_cfg.long_horizon_injection_max_chars = 2400
        mem_cfg.long_horizon_embedding_dim = 256
        mem_cfg.long_horizon_cross_thread_enabled = True
        mem_cfg.long_horizon_topic_memory_enabled = True
        mem_cfg.long_horizon_topic_top_k = 2
        mem_cfg.long_horizon_project_memory_enabled = True
        mem_cfg.long_horizon_project_top_k = 2
        mem_cfg.long_horizon_current_thread_boost = 0.08
        mem_cfg.long_horizon_project_boost = 0.12
        mem_cfg.long_horizon_topic_overlap_boost = 0.03

        memory_data = {
            "version": "1.0",
            "lastUpdated": "",
            "user": {
                "workContext": {"summary": "", "updatedAt": ""},
                "personalContext": {"summary": "", "updatedAt": ""},
                "topOfMind": {"summary": "", "updatedAt": ""},
            },
            "history": {
                "recentMonths": {"summary": "", "updatedAt": ""},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""},
            },
            "facts": [],
        }

        with (
            patch("src.config.memory_config.get_memory_config", return_value=mem_cfg),
            patch("src.agents.memory.updater.get_memory_data", return_value=memory_data),
        ):
            result = client.get_memory_status()

        parsed = MemoryStatusResponse(**result)
        assert parsed.config.enabled is True
        assert parsed.data.version == "1.0"

    def test_export_image_report_pdf(self, client):
        with (
            patch("src.config.scientific_vision_config.get_scientific_vision_config", return_value=SimpleNamespace(artifact_subdir="scientific-vision/image-reports")),
            patch("src.utils.image_report_pdf.generate_image_report_pdf", return_value="/mnt/user-data/outputs/scientific-vision/image-reports/pdfs/report.pdf"),
        ):
            result = client.export_image_report_pdf("thread-1", index_payload={"thread_id": "thread-1", "reports": []})

        parsed = ImageReportPdfResponse(**result)
        assert parsed.pdf_path.endswith(".pdf")

    def test_export_latex_diagnostics_markdown(self, client):
        from src.config.paths import Paths

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.client.get_paths",
            return_value=Paths(base_dir=tmp),
        ):
            result = client.export_latex_diagnostics_markdown(
                "thread-1",
                title="Latex diag",
                compile_status="failed",
                compile_log_path="/mnt/user-data/outputs/research-writing/latex/p1.compile.log",
                issue_clusters=[
                    {
                        "id": "missing-package",
                        "title": "Missing package",
                        "severity": "error",
                        "match_count": 1,
                        "matched_lines": ["L31: ! LaTeX Error: File `booktabs.sty' not found."],
                        "suggestions": ["tlmgr install booktabs"],
                    }
                ],
                output_filename="diag.md",
            )
        parsed = LatexDiagnosticsMarkdownResponse(**result)
        assert parsed.report_path.endswith("/research-writing/latex/reports/diag.md")

    def test_research_upsert_project(self, client):
        payload = {
            "project_id": "p1",
            "title": "Conformance Project",
            "discipline": "ai_cs",
            "sections": [],
        }
        with patch("src.research_writing.runtime_service.upsert_project", return_value=SimpleNamespace(model_dump=lambda: payload)):
            result = client.research_upsert_project("thread-1", payload)
        parsed = ProjectResponse(**result)
        assert parsed.project["project_id"] == "p1"

    def test_research_list_projects(self, client):
        with patch(
            "src.research_writing.runtime_service.list_projects",
            return_value=[SimpleNamespace(model_dump=lambda: {"project_id": "p1", "title": "P1"})],
        ):
            result = client.research_list_projects("thread-1")
        parsed = ProjectsListResponse(**result)
        assert len(parsed.projects) == 1

    def test_research_ingest_fulltext(self, client):
        with patch(
            "src.research_writing.runtime_service.ingest_fulltext_evidence",
            return_value={
                "record": {"source": "arxiv", "external_id": "2501.00001"},
                "evidence_count": 2,
                "persisted_evidence_ids": ["id-1"],
                "artifact_path": "/mnt/user-data/outputs/research-writing/artifacts/ingest.json",
            },
        ):
            result = client.research_ingest_fulltext("thread-1", source="arxiv", external_id="2501.00001")
        parsed = FulltextIngestResponse(**result)
        assert parsed.evidence_count == 2

    def test_research_compile_section(self, client):
        with patch(
            "src.research_writing.runtime_service.compile_project_section",
            return_value={
                "section_id": "intro",
                "compiled_text": "Compiled",
                "issues": [],
                "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/intro.md",
            },
        ) as compile_mock:
            result = client.research_compile_section(
                "thread-1",
                project_id="p1",
                section_id="intro",
                reviewer2_styles=["statistical_tyrant"],
                peer_review_ab_variant="A",
                claim_map_json={
                    "claims": [
                        {
                            "claim_id": "c1",
                            "claim_type": "strong",
                            "sentence_type": "general",
                            "sentence_draft": "Draft sentence [data:ev1] [citation:cit1]",
                            "data_ids": ["ev1"],
                            "citation_ids": ["cit1"],
                        }
                    ]
                },
                require_claim_map_submission=True,
            )
        parsed = SectionCompileResponse(**result)
        assert parsed.section_id == "intro"
        _, kwargs = compile_mock.call_args
        assert kwargs["reviewer2_styles"] == ["statistical_tyrant"]
        assert kwargs["peer_review_ab_variant"] == "A"
        assert isinstance(kwargs["claim_map_json"], dict)
        assert kwargs["require_claim_map_submission"] is True

    def test_research_verify_claim_map_only(self, client):
        with patch(
            "src.research_writing.runtime_service.verify_project_section_claim_map",
            return_value={
                "project_id": "p1",
                "section_id": "discussion",
                "claim_map": {"schema_version": "deerflow.claim_map.v1", "summary": {"total_claim_ids": 1}, "claims": []},
                "claim_map_artifact_path": "/mnt/user-data/outputs/research-writing/claim-maps/p1-discussion.verified.json",
                "claim_map_validation": {"status": "passed"},
            },
        ) as verify_mock:
            result = client.research_verify_claim_map_only(
                "thread-1",
                project_id="p1",
                section_id="discussion",
                claim_map_json={
                    "claims": [
                        {
                            "claim_id": "c1",
                            "claim_type": "weak",
                            "sentence_type": "general",
                            "sentence_draft": "Draft sentence [data:ev1]",
                            "data_ids": ["ev1"],
                            "citation_ids": [],
                        }
                    ]
                },
                require_claim_map_submission=True,
            )
        assert result["section_id"] == "discussion"
        _, kwargs = verify_mock.call_args
        assert isinstance(kwargs["claim_map_json"], dict)
        assert kwargs["require_claim_map_submission"] is True

    def test_research_plan_narrative(self, client):
        with patch(
            "src.research_writing.runtime_service.plan_project_section_narrative",
            return_value={
                "project_id": "p1",
                "section_id": "intro",
                "section_name": "Introduction",
                "planner_version": "deerflow.narrative_plan.v1",
                "takeaway_message": "Takeaway",
                "gap_statement": "Gap",
                "disruption_statement": "Disruption",
                "logical_flow": ["f1", "f2"],
                "figure_storyboard": [{"figure_id": "F1"}],
                "self_questioning": [{"round_index": 1}],
                "introduction_hook": "hook",
                "discussion_pivot": "pivot",
                "self_question_rounds": 3,
                "include_storyboard": True,
                "artifact_path": "/mnt/user-data/outputs/research-writing/narrative-plans/p1-intro.json",
            },
        ):
            result = client.research_plan_narrative("thread-1", project_id="p1", section_id="intro")
        parsed = NarrativePlanResponse(**result)
        assert parsed.section_id == "intro"

    def test_research_compile_latex(self, client):
        with patch(
            "src.research_writing.runtime_service.build_latex_manuscript",
            return_value={
                "project_id": "p1",
                "section_ids": ["discussion"],
                "title": "Paper",
                "source_markdown_path": "/mnt/user-data/outputs/research-writing/latex/p1.source.md",
                "tex_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
                "pdf_path": "/mnt/user-data/outputs/research-writing/latex/p1.pdf",
                "compile_log_path": "/mnt/user-data/outputs/research-writing/latex/p1.compile.log",
                "compile_status": "success",
                "compiler": "latexmk",
                "engine_requested": "auto",
                "compile_pdf_requested": True,
                "citation_keys": ["10.1000/demo"],
                "citation_count": 1,
                "warning": None,
                "artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
                "summary_artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.json",
            },
        ):
            result = client.research_compile_latex("thread-1", project_id="p1", section_ids=["discussion"], compile_pdf=True)
        parsed = LatexCompileResponse(**result)
        assert parsed.compile_status == "success"

    def test_research_simulate_review(self, client):
        with patch(
            "src.research_writing.runtime_service.simulate_review_and_plan",
            return_value={
                "venue": "NeurIPS",
                "overall_assessment": "major revision",
                "comments": [],
                "actions": [],
                "rebuttal_letter": "Letter",
                "artifact_path": "/mnt/user-data/outputs/research-writing/review/review.json",
                "letter_path": "/mnt/user-data/outputs/research-writing/review/review.md",
            },
        ):
            result = client.research_simulate_review("thread-1", venue_name="NeurIPS", manuscript_text="Draft")
        parsed = ReviewSimulateResponse(**result)
        assert parsed.venue == "NeurIPS"

    def test_research_simulate_peer_review_loop(self, client):
        with patch(
            "src.research_writing.runtime_service.simulate_peer_review_cycle",
            return_value={
                "venue": "NeurIPS",
                "section_id": "discussion",
                "red_team_agents": ["reviewer_agent", "area_chair_agent"],
                "blue_team_agents": ["author_agent"],
                "rounds": [],
                "final_text": "Revised text",
                "final_decision": "accept",
                "unresolved_issue_count": 0,
                "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.json",
                "final_text_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.md",
            },
        ) as peer_mock:
            result = client.research_simulate_peer_review_loop(
                "thread-1",
                venue_name="NeurIPS",
                manuscript_text="Draft",
                section_id="discussion",
                max_rounds=3,
                reviewer2_styles=["methodology_fundamentalist"],
                peer_review_ab_variant="A",
            )
        parsed = PeerReviewLoopResponse(**result)
        assert parsed.final_decision == "accept"
        _, kwargs = peer_mock.call_args
        assert kwargs["reviewer2_styles"] == ["methodology_fundamentalist"]
        assert kwargs["peer_review_ab_variant"] == "A"

    def test_research_get_peer_review_ab_metrics(self, client):
        with patch(
            "src.research_writing.runtime_service.get_peer_review_ab_metrics",
            return_value={
                "metrics_schema_version": "deerflow.peer_review_ab_metrics.v1",
                "thread_id": "thread-1",
                "total_runs": 2,
                "window_size": 2,
                "by_variant_total": {},
                "by_variant_window": {},
                "recent_runs": [],
                "strategy_config": {},
                "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-review-ab-metrics.json",
            },
        ) as metrics_mock:
            result = client.research_get_peer_review_ab_metrics("thread-1")
        assert result["thread_id"] == "thread-1"
        assert result["total_runs"] == 2
        metrics_mock.assert_called_once_with(thread_id="thread-1")

    def test_research_get_engineering_gates_metrics(self, client):
        with patch(
            "src.research_writing.runtime_service.get_engineering_gates_metrics",
            return_value={
                "metrics_schema_version": "deerflow.engineering_gates_runtime_metrics.v1",
                "thread_id": "thread-1",
                "project_id": "p1",
                "run_limit": 80,
                "updated_at": "2026-03-17T00:00:00+00:00",
                "compile_runs": [],
                "latex_runs": [],
                "compile_summary": {"run_count": 0},
                "latex_summary": {"run_count": 0},
                "thresholds": {},
                "alerts": [],
                "status": "pass",
                "counters": {},
                "artifacts": {},
            },
        ) as metrics_mock:
            result = client.research_get_engineering_gates_metrics(
                "thread-1",
                project_id="p1",
                run_limit=80,
                max_constraint_violation_rate=0.15,
                max_safety_valve_trigger_rate=0.25,
                max_hitl_block_rate=0.2,
                min_traceability_coverage_rate=0.85,
                min_delivery_completeness_rate=1.0,
                min_latex_success_rate=0.9,
            )
        assert result["thread_id"] == "thread-1"
        assert result["project_id"] == "p1"
        assert result["run_limit"] == 80
        metrics_mock.assert_called_once_with(
            thread_id="thread-1",
            project_id="p1",
            run_limit=80,
            max_constraint_violation_rate=0.15,
            max_safety_valve_trigger_rate=0.25,
            max_hitl_block_rate=0.2,
            min_traceability_coverage_rate=0.85,
            min_delivery_completeness_rate=1.0,
            min_latex_success_rate=0.9,
        )

    def test_research_optimize_prompt_layers(self, client):
        with patch(
            "src.research_writing.runtime_service.run_prompt_layer_optimizer",
            return_value={
                "optimizer_schema_version": "deerflow.prompt_optimizer.v1",
                "thread_id": "thread-1",
                "generated_at": "2026-03-18T00:00:00Z",
                "status": "candidate_generated",
                "optimizer_config": {
                    "enabled": True,
                    "optimizer_mode": "llm_structured_patch",
                    "model_name": "optimizer-llm",
                    "thinking_enabled": True,
                    "temperature": 0.1,
                    "max_candidate_count": 2,
                    "fallback_to_rules": True,
                },
                "optimizer_mode_requested": "llm_structured_patch",
                "optimizer_mode_used": "llm_structured_patch",
                "fallback_reason": None,
                "signals": {"binding_failures": True},
                "changes": [{"layer_id": "L1", "new_version": "v2"}],
                "change_count": 1,
                "candidate_prompt_layers_path": "/mnt/user-data/outputs/research-writing/prompt-optimizer/prompt_layers.candidate.yaml",
                "candidate_prompt_patch_path": "/mnt/user-data/outputs/research-writing/prompt-optimizer/prompt_patch_plan.candidate.json",
                "applied_prompt_patch": False,
                "applied_prompt_layers_path": None,
                "source_paths": {},
                "llm_candidate": {"summary": "tighten L1"},
                "validation_issues": [],
                "offline_validation": {"status": "pass"},
            },
        ) as optimizer_mock:
            result = client.research_optimize_prompt_layers(
                "thread-1",
                compile_metrics_path="/mnt/user-data/outputs/research-writing/metrics/compile-gates.json",
                offline_regression_report_path="/mnt/user-data/outputs/research-writing/evals/offline-benchmark-regression.json",
                prompt_layers_path="/tmp/prompt_layers.yaml",
                apply_prompt_patch=False,
                run_offline_validation=True,
                dataset_version="2026_03",
                optimizer_config={
                    "enabled": True,
                    "optimizer_mode": "llm_structured_patch",
                    "model_name": "optimizer-llm",
                    "thinking_enabled": True,
                    "temperature": 0.1,
                    "max_candidate_count": 2,
                    "fallback_to_rules": True,
                },
            )
        assert result["thread_id"] == "thread-1"
        assert result["status"] == "candidate_generated"
        assert result["optimizer_config"]["model_name"] == "optimizer-llm"
        assert result["optimizer_mode_used"] == "llm_structured_patch"
        optimizer_mock.assert_called_once_with(
            thread_id="thread-1",
            compile_metrics_path="/mnt/user-data/outputs/research-writing/metrics/compile-gates.json",
            offline_regression_report_path="/mnt/user-data/outputs/research-writing/evals/offline-benchmark-regression.json",
            prompt_layers_path="/tmp/prompt_layers.yaml",
            apply_prompt_patch=False,
            run_offline_validation=True,
            dataset_version="2026_03",
            optimizer_config={
                "enabled": True,
                "optimizer_mode": "llm_structured_patch",
                "model_name": "optimizer-llm",
                "thinking_enabled": True,
                "temperature": 0.1,
                "max_candidate_count": 2,
                "fallback_to_rules": True,
            },
            optimizer_mode="rules",
            llm_model_name=None,
            llm_thinking_enabled=False,
            llm_temperature=0.0,
        )

    def test_research_generate_hypotheses(self, client):
        with patch(
            "src.research_writing.runtime_service.generate_project_hypotheses",
            return_value={
                "project_id": "p1",
                "section_id": "discussion",
                "feature_summary": ["Evidence coverage: 2 units."],
                "hypotheses": [{"hypothesis_id": "H1"}],
                "synthesis_paragraph": "Top-ranked hypothesis ...",
                "artifact_path": "/mnt/user-data/outputs/research-writing/hypotheses/hypothesis-p1-discussion.json",
            },
        ):
            result = client.research_generate_hypotheses(
                "thread-1",
                project_id="p1",
                section_id="discussion",
                max_hypotheses=5,
            )
        parsed = HypothesisGenerateResponse(**result)
        assert parsed.project_id == "p1"

    def test_research_capability_catalog_and_assessment(self, client):
        with (
            patch(
                "src.research_writing.runtime_service.get_capability_catalog",
                return_value={
                    "catalog_schema_version": "deerflow.capability_catalog.v1",
                    "generated_at": "2026-03-17T00:00:00Z",
                    "capabilities": [{"capability_id": "claim_engineering"}],
                },
            ) as catalog_mock,
            patch(
                "src.research_writing.runtime_service.assess_project_capabilities",
                return_value={
                    "schema_version": "deerflow.capability_assessment.v1",
                    "generated_at": "2026-03-17T00:00:00Z",
                    "project_id": "p1",
                    "section_id": "discussion",
                    "catalog": {"schema_version": "deerflow.capability_catalog.v1", "capabilities": []},
                    "assessment": {"overall_score": 0.77, "status": "pass", "scorecards": []},
                    "artifact_path": "/mnt/user-data/outputs/research-writing/capabilities/assessment-p1-discussion.json",
                },
            ) as assess_mock,
        ):
            catalog = client.research_get_capability_catalog("thread-1")
            assessment = client.research_assess_capabilities("thread-1", project_id="p1", section_id="discussion")
        parsed_catalog = CapabilityCatalogResponse(**catalog)
        parsed_assessment = CapabilityAssessmentResponse(**assessment)
        assert parsed_catalog.catalog_schema_version == "deerflow.capability_catalog.v1"
        assert parsed_assessment.assessment["overall_score"] == 0.77
        catalog_mock.assert_called_once_with("thread-1")
        assess_mock.assert_called_once_with(thread_id="thread-1", project_id="p1", section_id="discussion")

    def test_research_hitl_decisions(self, client):
        hitl_payload = {
            "project_id": "p1",
            "section_id": "discussion",
            "decisions": [
                {
                    "action_id": "peer-r1-abc",
                    "source": "Peer Loop Round 1",
                    "label": "Add ablation",
                    "decision": "approved",
                    "section_id": "discussion",
                    "updated_at": "2026-03-16T00:00:00Z",
                    "metadata": {},
                }
            ],
            "total_count": 1,
            "updated_at": "2026-03-16T00:00:00Z",
            "artifact_path": "/mnt/user-data/outputs/research-writing/hitl/hitl-decisions-p1.json",
        }
        with (
            patch(
                "src.research_writing.runtime_service.upsert_project_hitl_decisions",
                return_value=hitl_payload,
            ),
            patch(
                "src.research_writing.runtime_service.get_project_hitl_decisions",
                return_value={**hitl_payload, "artifact_path": None},
            ),
        ):
            upserted = client.research_upsert_hitl_decisions(
                "thread-1",
                project_id="p1",
                section_id="discussion",
                decisions=[
                    {
                        "action_id": "peer-r1-abc",
                        "source": "Peer Loop Round 1",
                        "label": "Add ablation",
                        "decision": "approved",
                    }
                ],
            )
            fetched = client.research_get_hitl_decisions(
                "thread-1",
                project_id="p1",
                section_id="discussion",
            )
        parsed_upsert = HitlDecisionsResponse(**upserted)
        parsed_get = HitlDecisionsResponse(**fetched)
        assert parsed_upsert.total_count == 1
        assert parsed_get.total_count == 1

    def test_research_evaluate_academic(self, client):
        with patch(
            "src.research_writing.runtime_service.evaluate_academic_and_persist",
            return_value={
                "case_count": 1,
                "average_overall_score": 0.8,
                "average_citation_fidelity": 0.8,
                "average_claim_grounding": 0.8,
                "average_abstract_body_consistency": 0.8,
                "average_reviewer_rebuttal_completeness": 0.8,
                "average_venue_fit": 0.8,
                "average_cross_modality_synthesis": 0.8,
                "average_long_horizon_consistency": 0.8,
                "results": [],
                "artifact_path": "/mnt/user-data/outputs/research-writing/evals/eval.json",
            },
        ):
            result = client.research_evaluate_academic(
                "thread-1",
                cases=[
                    {
                        "case_id": "c1",
                        "domain": "ai_cs",
                        "venue": "NeurIPS",
                        "generated_citations": [],
                        "verified_citations": [],
                        "claims": [],
                        "abstract_numbers": [],
                        "body_numbers": [],
                        "reviewer_comment_ids": [],
                        "rebuttal_addressed_ids": [],
                        "venue_checklist_items": [],
                        "venue_satisfied_items": [],
                        "cross_modal_items_expected": 0,
                        "cross_modal_items_used": 0,
                        "revision_terms": [],
                        "revision_numbers": [],
                    }
                ],
            )
        parsed = EvalAcademicResponse(**result)
        assert parsed.case_count == 1
