"""Tests for tool name deduplication in get_available_tools() (issue #1803).

Duplicate tool registrations previously passed through silently and could
produce mangled function-name schemas that caused 100% tool call failures.
``get_available_tools()`` now deduplicates by name, config-loaded tools taking
priority, and logs a warning for every skipped duplicate.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.tools import BaseTool, StructuredTool, tool
from pydantic import BaseModel, Field

from deerflow.tools.tools import get_available_tools

# ---------------------------------------------------------------------------
# Fixture tools
# ---------------------------------------------------------------------------


class AsyncToolArgs(BaseModel):
    x: int = Field(..., description="test input")


@tool
def _tool_alpha(x: str) -> str:
    """Alpha tool."""
    return x


@tool
def _tool_alpha_dup(x: str) -> str:
    """Duplicate of alpha — same name, different object."""
    return x


# Rename duplicate to share the same .name as _tool_alpha
_tool_alpha_dup.name = _tool_alpha.name  # type: ignore[attr-defined]


@tool
def _tool_beta(x: str) -> str:
    """Beta tool."""
    return x


# ---------------------------------------------------------------------------
# Deduplication behaviour
# ---------------------------------------------------------------------------


def _make_minimal_config(tools):
    """Return an AppConfig-like mock with the given tools list."""
    config = MagicMock()
    config.tools = tools
    config.models = []
    config.tool_search.enabled = False
    config.skill_evolution.enabled = False
    config.sandbox = MagicMock()
    config.acp_agents = {}
    return config


@patch("deerflow.tools.tools.get_app_config")
@patch("deerflow.tools.tools.is_host_bash_allowed", return_value=True)
@patch("deerflow.tools.tools.reset_deferred_registry")
def test_config_loaded_async_only_tool_gets_sync_wrapper(mock_reset, mock_bash, mock_cfg):
    """Config-loaded async-only tools can still be invoked by sync clients."""

    async def async_tool_impl(x: int) -> str:
        return f"result: {x}"

    async_tool = StructuredTool(
        name="async_tool",
        description="Async-only test tool.",
        args_schema=AsyncToolArgs,
        func=None,
        coroutine=async_tool_impl,
    )
    tool_cfg = MagicMock()
    tool_cfg.name = "async_tool"
    tool_cfg.group = "test"
    tool_cfg.use = "tests.fake:async_tool"
    mock_cfg.return_value = _make_minimal_config([tool_cfg])

    with (
        patch("deerflow.tools.tools.resolve_variable", return_value=async_tool),
        patch("deerflow.tools.tools.BUILTIN_TOOLS", []),
    ):
        result = get_available_tools(include_mcp=False, app_config=mock_cfg.return_value)

    assert async_tool in result
    assert async_tool.func is not None
    assert async_tool.invoke({"x": 42}) == "result: 42"


@patch("deerflow.tools.tools.get_app_config")
@patch("deerflow.tools.tools.is_host_bash_allowed", return_value=True)
@patch("deerflow.tools.tools.reset_deferred_registry")
def test_no_duplicates_returned(mock_reset, mock_bash, mock_cfg):
    """get_available_tools() never returns two tools with the same name."""
    mock_cfg.return_value = _make_minimal_config([])

    # Patch the builtin tools so we control exactly what comes back.
    with patch("deerflow.tools.tools.BUILTIN_TOOLS", [_tool_alpha, _tool_alpha_dup, _tool_beta]):
        result = get_available_tools(include_mcp=False)

    names = [t.name for t in result]
    assert len(names) == len(set(names)), f"Duplicate names detected: {names}"


@patch("deerflow.tools.tools.get_app_config")
@patch("deerflow.tools.tools.is_host_bash_allowed", return_value=True)
@patch("deerflow.tools.tools.reset_deferred_registry")
def test_first_occurrence_wins(mock_reset, mock_bash, mock_cfg):
    """When duplicates exist, the first occurrence is kept."""
    mock_cfg.return_value = _make_minimal_config([])

    sentinel_alpha = MagicMock(spec=BaseTool, name="_sentinel")
    sentinel_alpha.name = _tool_alpha.name  # same name
    sentinel_alpha_dup = MagicMock(spec=BaseTool, name="_sentinel_dup")
    sentinel_alpha_dup.name = _tool_alpha.name  # same name — should be dropped

    with patch("deerflow.tools.tools.BUILTIN_TOOLS", [sentinel_alpha, sentinel_alpha_dup, _tool_beta]):
        result = get_available_tools(include_mcp=False)

    returned_alpha = next(t for t in result if t.name == _tool_alpha.name)
    assert returned_alpha is sentinel_alpha


@patch("deerflow.tools.tools.get_app_config")
@patch("deerflow.tools.tools.is_host_bash_allowed", return_value=True)
@patch("deerflow.tools.tools.reset_deferred_registry")
def test_duplicate_triggers_warning(mock_reset, mock_bash, mock_cfg, caplog):
    """A warning is logged for every skipped duplicate."""
    import logging

    mock_cfg.return_value = _make_minimal_config([])

    with patch("deerflow.tools.tools.BUILTIN_TOOLS", [_tool_alpha, _tool_alpha_dup]):
        with caplog.at_level(logging.WARNING, logger="deerflow.tools.tools"):
            get_available_tools(include_mcp=False)

    assert any("Duplicate tool name" in r.message for r in caplog.records), "Expected a duplicate-tool warning in log output"
