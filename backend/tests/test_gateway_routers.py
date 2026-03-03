"""Integration tests for gateway API routers (models, agent, MCP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config.app_config import AppConfig
from src.config.extensions_config import ExtensionsConfig, McpServerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_model_config(name: str = "test-model", **overrides) -> MagicMock:
    """Create a minimal mock ModelConfig."""
    m = MagicMock()
    m.name = name
    m.display_name = overrides.get("display_name", f"Test Model {name}")
    m.description = overrides.get("description", f"Description for {name}")
    m.supports_thinking = overrides.get("supports_thinking", False)
    return m


def _make_app_config(models: list | None = None) -> AppConfig:
    """Create a minimal AppConfig with mock model list."""
    config = MagicMock(spec=AppConfig)
    config.models = models or [_minimal_model_config()]
    config.get_model_config = lambda name: next(
        (m for m in config.models if m.name == name), None
    )
    return config


@pytest.fixture()
def app():
    """Create a test FastAPI app with patched dependencies."""
    # Patch config before importing the app factory
    mock_config = _make_app_config([
        _minimal_model_config("gpt-4", display_name="GPT-4", supports_thinking=False),
        _minimal_model_config("claude-3", display_name="Claude 3", supports_thinking=True),
    ])

    with patch("src.config.app_config.get_app_config", return_value=mock_config):
        with patch("src.gateway.routers.models.get_app_config", return_value=mock_config):
            with patch("src.gateway.routers.agent.get_app_config", return_value=mock_config):
                # Import here to avoid circular import issues
                from src.gateway.app import create_app
                yield create_app()


@pytest.fixture()
async def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Models Router
# ---------------------------------------------------------------------------
class TestModelsRouter:
    """Tests for /api/models endpoints."""

    @pytest.mark.asyncio
    async def test_list_models(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 2
        names = [m["name"] for m in data["models"]]
        assert "gpt-4" in names
        assert "claude-3" in names

    @pytest.mark.asyncio
    async def test_get_model_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models/gpt-4")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "gpt-4"
        assert data["display_name"] == "GPT-4"
        assert data["supports_thinking"] is False

    @pytest.mark.asyncio
    async def test_get_model_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_model_supports_thinking(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models/claude-3")
        assert resp.status_code == 200
        assert resp.json()["supports_thinking"] is True

    @pytest.mark.asyncio
    async def test_list_models_returns_all_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models")
        model = resp.json()["models"][0]
        assert "name" in model
        assert "display_name" in model
        assert "description" in model
        assert "supports_thinking" in model


# ---------------------------------------------------------------------------
# Agent Router
# ---------------------------------------------------------------------------
class TestAgentRouter:
    """Tests for /api/agent endpoints."""

    @pytest.mark.asyncio
    async def test_get_agent_context(self, client: AsyncClient) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "bash"
        mock_tool.description = "Execute commands"

        with patch("src.gateway.routers.agent.get_available_tools", return_value=[mock_tool]):
            with patch("src.gateway.routers.agent.load_skills", return_value=[]):
                resp = await client.get("/api/agent/context")

        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert "skills" in data
        assert data["subagent_enabled"] is False

    @pytest.mark.asyncio
    async def test_get_agent_context_with_skills(self, client: AsyncClient) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "bash"
        mock_tool.description = "Execute commands"

        mock_skill = MagicMock()
        mock_skill.name = "deep-research"
        mock_skill.description = "Research deeply"

        with patch("src.gateway.routers.agent.get_available_tools", return_value=[mock_tool]):
            with patch("src.gateway.routers.agent.load_skills", return_value=[mock_skill]):
                resp = await client.get("/api/agent/context")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "deep-research"

    @pytest.mark.asyncio
    async def test_get_agent_context_with_subagent(self, client: AsyncClient) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "task"
        mock_tool.description = "Launch subagent"

        with patch("src.gateway.routers.agent.get_available_tools", return_value=[mock_tool]):
            with patch("src.gateway.routers.agent.load_skills", return_value=[]):
                resp = await client.get("/api/agent/context?subagent_enabled=true")

        assert resp.status_code == 200
        assert resp.json()["subagent_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_agent_context_deduplicates_tools(self, client: AsyncClient) -> None:
        tool1 = MagicMock()
        tool1.name = "bash"
        tool1.description = "Execute commands"
        tool2 = MagicMock()
        tool2.name = "bash"
        tool2.description = "Execute commands again"

        with patch("src.gateway.routers.agent.get_available_tools", return_value=[tool1, tool2]):
            with patch("src.gateway.routers.agent.load_skills", return_value=[]):
                resp = await client.get("/api/agent/context")

        tools = resp.json()["tools"]
        bash_tools = [t for t in tools if t["name"] == "bash"]
        assert len(bash_tools) == 1

    @pytest.mark.asyncio
    async def test_get_agent_context_error(self, client: AsyncClient) -> None:
        with patch("src.gateway.routers.agent.get_available_tools", side_effect=RuntimeError("broken")):
            resp = await client.get("/api/agent/context")

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# MCP Router
# ---------------------------------------------------------------------------
class TestMcpRouter:
    """Tests for /api/mcp endpoints."""

    @pytest.mark.asyncio
    async def test_get_mcp_config_empty(self, client: AsyncClient) -> None:
        mock_ext = ExtensionsConfig(mcp_servers={})
        with patch("src.gateway.routers.mcp.get_extensions_config", return_value=mock_ext):
            resp = await client.get("/api/mcp/config")

        assert resp.status_code == 200
        assert resp.json()["mcp_servers"] == {}

    @pytest.mark.asyncio
    async def test_get_mcp_config_with_servers(self, client: AsyncClient) -> None:
        server = McpServerConfig(
            enabled=True,
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            description="GitHub MCP",
        )
        mock_ext = ExtensionsConfig(mcp_servers={"github": server})
        with patch("src.gateway.routers.mcp.get_extensions_config", return_value=mock_ext):
            resp = await client.get("/api/mcp/config")

        assert resp.status_code == 200
        data = resp.json()
        assert "github" in data["mcp_servers"]
        assert data["mcp_servers"]["github"]["command"] == "npx"
        assert data["mcp_servers"]["github"]["enabled"] is True
