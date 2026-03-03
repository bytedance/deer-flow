"""Tests for tools assembly: get_available_tools loading, filtering, and MCP integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tools.tools import BUILTIN_TOOLS, SUBAGENT_TOOLS, get_available_tools


def _mock_app_config(models=None, tools=None):
    """Create a mock AppConfig."""
    config = MagicMock()
    config.tools = tools or []
    config.models = models or []
    config.get_model_config.return_value = None
    return config


def _make_tool_config(name: str, group: str, use: str):
    """Create a mock ToolConfig."""
    tc = MagicMock()
    tc.name = name
    tc.group = group
    tc.use = use
    return tc


def _make_model_config(name: str, supports_vision: bool = False):
    """Create a mock ModelConfig."""
    mc = MagicMock()
    mc.name = name
    mc.supports_vision = supports_vision
    return mc


# ---------------------------------------------------------------------------
# get_available_tools
# ---------------------------------------------------------------------------
class TestGetAvailableTools:
    """Tests for get_available_tools()."""

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_includes_config_tools(self, mock_resolve, mock_config) -> None:
        tool1 = MagicMock(name="my_tool")
        mock_resolve.return_value = tool1

        tc = _make_tool_config("my_tool", "core", "src.tools:my_tool")
        config = _mock_app_config(tools=[tc])
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, subagent_enabled=False)
        assert tool1 in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_includes_builtin_tools(self, mock_resolve, mock_config) -> None:
        mock_resolve.return_value = MagicMock()
        config = _mock_app_config(tools=[_make_tool_config("t", "g", "u")])
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, subagent_enabled=False)
        # All BUILTIN_TOOLS should be present
        for bt in BUILTIN_TOOLS:
            assert bt in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_excludes_subagent_tools_when_disabled(self, mock_resolve, mock_config) -> None:
        from src.tools.builtins import task_tool

        mock_resolve.return_value = MagicMock()
        config = _mock_app_config(tools=[_make_tool_config("t", "g", "u")])
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, subagent_enabled=False)
        # task_tool is subagent-only (not in BUILTIN_TOOLS), so it should be absent
        assert task_tool not in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_includes_subagent_tools_when_enabled(self, mock_resolve, mock_config) -> None:
        mock_resolve.return_value = MagicMock()
        config = _mock_app_config(tools=[_make_tool_config("t", "g", "u")])
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, subagent_enabled=True)
        for st in SUBAGENT_TOOLS:
            assert st in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_includes_view_image_when_model_supports_vision(self, mock_resolve, mock_config) -> None:
        from src.tools.builtins import view_image_tool

        mock_resolve.return_value = MagicMock()
        mc = _make_model_config("gpt-4-vision", supports_vision=True)
        config = _mock_app_config(
            tools=[_make_tool_config("t", "g", "u")],
            models=[mc],
        )
        config.get_model_config.return_value = mc
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, model_name="gpt-4-vision")
        assert view_image_tool in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_excludes_view_image_when_no_vision(self, mock_resolve, mock_config) -> None:
        from src.tools.builtins import view_image_tool

        mock_resolve.return_value = MagicMock()
        mc = _make_model_config("gpt-4", supports_vision=False)
        config = _mock_app_config(
            tools=[_make_tool_config("t", "g", "u")],
            models=[mc],
        )
        config.get_model_config.return_value = mc
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False, model_name="gpt-4")
        assert view_image_tool not in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_includes_view_image_from_runtime_model(self, mock_resolve, mock_config) -> None:
        from src.tools.builtins import view_image_tool

        mock_resolve.return_value = MagicMock()
        config = _mock_app_config(tools=[_make_tool_config("t", "g", "u")])
        mock_config.return_value = config

        result = get_available_tools(
            include_mcp=False,
            runtime_model={"supports_vision": True},
        )
        assert view_image_tool in result

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_group_filtering(self, mock_resolve, mock_config) -> None:
        mock_resolve.return_value = MagicMock()
        tc1 = _make_tool_config("bash", "core", "u")
        tc2 = _make_tool_config("web_search", "research", "u")
        config = _mock_app_config(tools=[tc1, tc2])
        mock_config.return_value = config

        result = get_available_tools(groups=["core"], include_mcp=False)
        # resolve_variable should only be called once (for the "core" group tool)
        mock_resolve.assert_called_once()

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_mcp_import_error_handled(self, mock_resolve, mock_config) -> None:
        mock_resolve.return_value = MagicMock()
        config = _mock_app_config(tools=[_make_tool_config("t", "g", "u")])
        mock_config.return_value = config

        with patch.dict("sys.modules", {"src.config.extensions_config": None}):
            # Should not raise, just logs warning
            result = get_available_tools(include_mcp=True)
            assert isinstance(result, list)

    @patch("src.tools.tools.get_app_config")
    @patch("src.tools.tools.resolve_variable")
    def test_no_tools_returns_builtins_only(self, mock_resolve, mock_config) -> None:
        config = _mock_app_config(tools=[])
        mock_config.return_value = config

        result = get_available_tools(include_mcp=False)
        # Should contain only builtin tools
        assert len(result) == len(BUILTIN_TOOLS)
