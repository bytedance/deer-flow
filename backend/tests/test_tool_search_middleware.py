"""Unit tests for ToolSearchMiddleware."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import BaseTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agents.middlewares.tool_search_middleware import (
    ToolSearchMiddleware,
)
from src.tools.catalog import ToolCatalog, ToolEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyInput(BaseModel):
    query: str = Field(description="Search query")


class DummyTool(BaseTool):
    name: str = "dummy"
    description: str = "A dummy tool"
    args_schema: type[BaseModel] | None = None

    def _run(self, **kwargs):
        return "ok"


def _make_tool(name: str, description: str, schema: type[BaseModel] | None = None) -> DummyTool:
    return DummyTool(name=name, description=description, args_schema=schema)


def _make_catalog_and_middleware(
    tools: list[DummyTool],
    core_names: set[str] | None = None,
    activation_threshold: int = 0,
) -> tuple[ToolCatalog, ToolSearchMiddleware, DummyTool]:
    """Create a catalog, tool_search tool, and middleware for testing."""
    core = core_names or set()
    catalog = ToolCatalog.from_tools(tools=tools, core_tool_names=core)

    tool_search = _make_tool("tool_search", "Search for specialized tools")

    middleware = ToolSearchMiddleware(
        catalog=catalog,
        tool_search_tool=tool_search,
        activation_threshold=activation_threshold,
        core_tool_names=core,
    )

    return catalog, middleware, tool_search


# ---------------------------------------------------------------------------
# Activation / deactivation
# ---------------------------------------------------------------------------


class TestActivation:
    def test_active_when_above_threshold(self):
        tools = [_make_tool(f"tool_{i}", f"Tool {i}") for i in range(10)]
        _, middleware, _ = _make_catalog_and_middleware(tools, activation_threshold=5)
        assert middleware._is_active is True

    def test_inactive_when_below_threshold(self):
        tools = [_make_tool(f"tool_{i}", f"Tool {i}") for i in range(3)]
        _, middleware, _ = _make_catalog_and_middleware(tools, activation_threshold=20)
        assert middleware._is_active is False

    def test_inactive_at_exact_threshold(self):
        tools = [_make_tool(f"tool_{i}", f"Tool {i}") for i in range(5)]
        _, middleware, _ = _make_catalog_and_middleware(tools, activation_threshold=5)
        assert middleware._is_active is False


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------


class TestToolFiltering:
    def test_core_tools_always_included(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("web_search", "Search web"),
            _make_tool("mcp_tool", "MCP tool"),
        ]
        _, middleware, tool_search = _make_catalog_and_middleware(
            tools, core_names={"bash", "web_search"}
        )

        all_tools = tools + [tool_search]
        filtered = middleware._filter_tools(all_tools, discovered_names=set())

        names = {t.name for t in filtered if isinstance(t, BaseTool)}
        assert "bash" in names
        assert "web_search" in names
        assert "tool_search" in names
        assert "mcp_tool" not in names

    def test_discovered_tools_included(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("mcp_tool", "MCP tool"),
        ]
        _, middleware, tool_search = _make_catalog_and_middleware(
            tools, core_names={"bash"}
        )

        all_tools = tools + [tool_search]
        filtered = middleware._filter_tools(all_tools, discovered_names={"mcp_tool"})

        names = {t.name for t in filtered if isinstance(t, BaseTool)}
        assert "mcp_tool" in names

    def test_dict_tools_always_included(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools, core_names={"bash"})

        dict_tool = {"name": "provider_tool", "type": "function"}
        all_tools = [dict_tool] + tools
        filtered = middleware._filter_tools(all_tools, discovered_names=set())

        assert dict_tool in filtered

    def test_tool_search_always_included(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, tool_search = _make_catalog_and_middleware(
            tools, core_names={"bash"}
        )

        filtered = middleware._filter_tools([tools[0]], discovered_names=set())
        names = {t.name for t in filtered if isinstance(t, BaseTool)}
        assert "tool_search" in names

    def test_no_duplicate_tools(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, tool_search = _make_catalog_and_middleware(
            tools, core_names={"bash"}
        )

        # Include tool_search twice in the input
        all_tools = tools + [tool_search, tool_search]
        filtered = middleware._filter_tools(all_tools, discovered_names=set())

        names = [t.name for t in filtered if isinstance(t, BaseTool)]
        assert names.count("tool_search") == 1


# ---------------------------------------------------------------------------
# Search execution
# ---------------------------------------------------------------------------


class TestSearchExecution:
    def test_search_returns_results(self):
        tools = [
            _make_tool("ncbi_search", "Search NCBI for biomedical articles"),
            _make_tool("bash", "Execute commands"),
        ]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        result_text, discovered = middleware._execute_search({"query": "ncbi biomedical"})
        assert len(discovered) > 0
        assert "ncbi_search" in discovered
        data = json.loads(result_text)
        assert data["found"] > 0
        assert any(t["name"] == "ncbi_search" for t in data["tools"])

    def test_search_empty_query(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        result_text, discovered = middleware._execute_search({"query": ""})
        assert discovered == []
        data = json.loads(result_text)
        assert data["found"] == 0
        assert "provide a search query" in data["message"].lower()

    def test_search_no_match(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        result_text, discovered = middleware._execute_search({"query": "quantum cryptography"})
        assert discovered == []
        data = json.loads(result_text)
        assert data["found"] == 0
        assert "no matching" in data["message"].lower()

    def test_search_respects_max_results(self):
        tools = [_make_tool(f"search_tool_{i}", f"Search tool {i}") for i in range(10)]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        result_text, discovered = middleware._execute_search(
            {"query": "search tool", "max_results": 3}
        )
        assert len(discovered) <= 3

    def test_search_max_results_capped_at_10(self):
        tools = [_make_tool(f"tool_{i}", f"Tool {i}") for i in range(15)]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        result_text, discovered = middleware._execute_search(
            {"query": "tool", "max_results": 50}
        )
        assert len(discovered) <= 10


# ---------------------------------------------------------------------------
# wrap_model_call
# ---------------------------------------------------------------------------


class TestWrapModelCall:
    def test_passthrough_when_inactive(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools, activation_threshold=20)

        request = MagicMock()
        handler = MagicMock(return_value="response")

        result = middleware.wrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "response"

    def test_filters_tools_when_active(self):
        tools = [
            _make_tool("bash", "Execute commands"),
            _make_tool("mcp_tool_1", "MCP tool 1"),
            _make_tool("mcp_tool_2", "MCP tool 2"),
        ]
        _, middleware, tool_search = _make_catalog_and_middleware(
            tools, core_names={"bash"}, activation_threshold=0
        )

        request = MagicMock()
        request.tools = tools + [tool_search]
        request.state = {"discovered_tools": []}
        request.override = MagicMock(return_value=request)

        handler = MagicMock(return_value="response")
        middleware.wrap_model_call(request, handler)

        # override should have been called with filtered tools
        request.override.assert_called_once()
        call_kwargs = request.override.call_args
        filtered = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools")
        filtered_names = {t.name for t in filtered if isinstance(t, BaseTool)}

        assert "bash" in filtered_names
        assert "tool_search" in filtered_names
        assert "mcp_tool_1" not in filtered_names
        assert "mcp_tool_2" not in filtered_names


# ---------------------------------------------------------------------------
# wrap_tool_call
# ---------------------------------------------------------------------------


class TestWrapToolCall:
    def test_passthrough_non_search_tools(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        request = MagicMock()
        request.tool_call = {"name": "bash", "args": {}, "id": "call_123"}

        handler = MagicMock(return_value="tool_result")
        result = middleware.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "tool_result"

    def test_intercepts_tool_search(self):
        tools = [
            _make_tool("ncbi_search", "Search NCBI for biomedical research"),
            _make_tool("bash", "Execute commands"),
        ]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        request = MagicMock()
        request.tool_call = {
            "name": "tool_search",
            "args": {"query": "ncbi biomedical"},
            "id": "call_456",
        }

        handler = MagicMock()
        result = middleware.wrap_tool_call(request, handler)

        # Handler should NOT be called (intercepted)
        handler.assert_not_called()

        # Should return a Command with discovered tools
        assert isinstance(result, Command)
        update = result.update
        assert "discovered_tools" in update
        assert "ncbi_search" in update["discovered_tools"]

    def test_search_no_results_returns_tool_message(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        request = MagicMock()
        request.tool_call = {
            "name": "tool_search",
            "args": {"query": "quantum cryptography"},
            "id": "call_789",
        }

        handler = MagicMock()
        result = middleware.wrap_tool_call(request, handler)

        handler.assert_not_called()
        # No results → ToolMessage (not Command)
        assert not isinstance(result, Command)
        data = json.loads(result.content)
        assert data["found"] == 0
        assert "no matching" in data["message"].lower()

    def test_search_empty_query_returns_tool_message(self):
        tools = [_make_tool("bash", "Execute commands")]
        _, middleware, _ = _make_catalog_and_middleware(tools)

        request = MagicMock()
        request.tool_call = {
            "name": "tool_search",
            "args": {"query": "   "},
            "id": "call_000",
        }

        handler = MagicMock()
        result = middleware.wrap_tool_call(request, handler)

        handler.assert_not_called()
        assert not isinstance(result, Command)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class TestMiddlewareStateSchema:
    def test_state_schema_has_discovered_tools(self):
        from src.agents.middlewares.tool_search_middleware import ToolSearchMiddlewareState

        # Verify the state schema declares discovered_tools
        annotations = ToolSearchMiddlewareState.__annotations__
        assert "discovered_tools" in annotations
