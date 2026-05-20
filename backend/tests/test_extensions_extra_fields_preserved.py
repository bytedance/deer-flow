"""Verify that extra top-level fields in extensions_config.json (e.g. mcpInterceptors)
are preserved when MCP server config or skill state is updated via the API or client.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, SkillStateConfig, reset_extensions_config, set_extensions_config


@pytest.fixture(autouse=True)
def _reset_extensions_config():
    reset_extensions_config()
    yield
    reset_extensions_config()


def _make_config_with_interceptors(tmp_path: Path) -> tuple[Path, ExtensionsConfig]:
    """Write an extensions_config.json with an mcpInterceptors extra field and return its path."""
    data = {
        "mcpServers": {
            "github": {
                "enabled": True,
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {},
                "description": "GitHub MCP",
            }
        },
        "skills": {"my-skill": {"enabled": True}},
        "mcpInterceptors": ["my_pkg.module:builder"],
    }
    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps(data, indent=2))
    cfg = ExtensionsConfig.from_file(str(config_file))
    set_extensions_config(cfg)
    return config_file, cfg


class TestMcpRouterPreservesExtraFields:
    @pytest.mark.anyio
    async def test_update_mcp_config_preserves_mcp_interceptors(self, tmp_path: Path) -> None:
        config_file, current_cfg = _make_config_with_interceptors(tmp_path)

        from app.gateway.routers.mcp import McpConfigUpdateRequest, McpServerConfigResponse, update_mcp_configuration

        request = McpConfigUpdateRequest(
            mcp_servers={
                "github": McpServerConfigResponse(
                    enabled=False,
                    type="stdio",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                )
            }
        )

        with (
            patch("app.gateway.routers.mcp.ExtensionsConfig.resolve_config_path", return_value=config_file),
            patch("app.gateway.routers.mcp.get_extensions_config", return_value=current_cfg),
            patch("app.gateway.routers.mcp.reload_extensions_config", return_value=current_cfg),
        ):
            await update_mcp_configuration(request)

        saved = json.loads(config_file.read_text())
        assert "mcpInterceptors" in saved
        assert saved["mcpInterceptors"] == ["my_pkg.module:builder"]


class TestSkillsRouterPreservesExtraFields:
    @pytest.mark.anyio
    async def test_update_skill_preserves_mcp_interceptors(self, tmp_path: Path) -> None:
        config_file, current_cfg = _make_config_with_interceptors(tmp_path)

        from app.gateway.routers.skills import SkillUpdateRequest, update_skill

        skill_mock = MagicMock()
        skill_mock.name = "my-skill"
        skill_mock.description = "A skill"
        skill_mock.license = "MIT"
        skill_mock.category = "public"
        skill_mock.enabled = True
        skill_mock.tools = []
        skill_mock.content = ""

        mock_storage = MagicMock()
        mock_storage.load_skills.return_value = [skill_mock]

        with (
            patch("app.gateway.routers.skills.ExtensionsConfig.resolve_config_path", return_value=config_file),
            patch("app.gateway.routers.skills.get_extensions_config", return_value=current_cfg),
            patch("app.gateway.routers.skills.reload_extensions_config", return_value=current_cfg),
            patch("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", new_callable=AsyncMock),
            patch("app.gateway.routers.skills.get_or_new_skill_storage", return_value=mock_storage),
        ):
            await update_skill("my-skill", SkillUpdateRequest(enabled=False), config=MagicMock())

        saved = json.loads(config_file.read_text())
        assert "mcpInterceptors" in saved
        assert saved["mcpInterceptors"] == ["my_pkg.module:builder"]


class TestClientPreservesExtraFields:
    def test_update_mcp_config_preserves_mcp_interceptors(self, tmp_path: Path) -> None:
        config_file, current_cfg = _make_config_with_interceptors(tmp_path)

        from deerflow.client import DeerFlowClient

        client = DeerFlowClient.__new__(DeerFlowClient)
        client._agent = None
        client._agent_config_key = None

        with (
            patch("deerflow.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
            patch("deerflow.client.get_extensions_config", return_value=current_cfg),
            patch("deerflow.client.reload_extensions_config", return_value=current_cfg),
        ):
            client.update_mcp_config({"github": {"enabled": False, "type": "stdio", "command": "npx"}})

        saved = json.loads(config_file.read_text())
        assert "mcpInterceptors" in saved
        assert saved["mcpInterceptors"] == ["my_pkg.module:builder"]

    def test_update_skill_preserves_mcp_interceptors(self, tmp_path: Path) -> None:
        config_file, current_cfg = _make_config_with_interceptors(tmp_path)
        current_cfg.skills["my-skill"] = SkillStateConfig(enabled=True)

        from deerflow.client import DeerFlowClient

        client = DeerFlowClient.__new__(DeerFlowClient)
        client._agent = None
        client._agent_config_key = None

        skill_mock = MagicMock()
        skill_mock.name = "my-skill"
        skill_mock.description = "A skill"
        skill_mock.license = "MIT"
        skill_mock.category = "public"
        skill_mock.enabled = False

        mock_storage = MagicMock()
        mock_storage.load_skills.return_value = [skill_mock]

        with (
            patch("deerflow.client.ExtensionsConfig.resolve_config_path", return_value=config_file),
            patch("deerflow.client.get_extensions_config", return_value=current_cfg),
            patch("deerflow.client.reload_extensions_config", return_value=current_cfg),
            patch("deerflow.skills.storage.get_or_new_skill_storage", return_value=mock_storage),
        ):
            client.update_skill("my-skill", enabled=False)

        saved = json.loads(config_file.read_text())
        assert "mcpInterceptors" in saved
        assert saved["mcpInterceptors"] == ["my_pkg.module:builder"]
