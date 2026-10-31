"""A serialized MCP routing index must not break middleware construction.

``McpRoutingMiddleware._normalize_index`` documents that it accepts "arbitrary
serialized routing data, not only the output of the builder". Two shapes the
loader can produce nevertheless escaped the coercion:

- an entry that is not a mapping (``str`` / ``list`` / ``None``) raised
  ``AttributeError`` on ``.get``;
- a non-finite ``priority`` raised ``OverflowError`` from ``int()`` — JSON
  accepts ``Infinity``, so a hand-edited or foreign index can carry one.

Construction happens once per run, so either shape turns every model call in
that process into an exception instead of the entry being ignored.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool

normalize = McpRoutingMiddleware._normalize_index


@pytest.mark.parametrize("bad_entry", ["just-a-string", ["keyword"], None, 7, 1.5])
def test_non_mapping_entries_are_skipped(bad_entry):
    """The malformed entry is dropped; its valid sibling still normalizes."""
    index = {"tool.bad": bad_entry, "tool.good": {"priority": 2, "keywords": ["search"]}}

    assert normalize(index) == {"tool.good": (2, ("search",))}


@pytest.mark.parametrize("priority", [float("inf"), float("-inf")])
def test_non_finite_priority_falls_back_to_zero(priority):
    """int() refuses infinity, and JSON accepts it as a literal."""
    assert normalize({"tool.a": {"priority": priority, "keywords": ["k"]}}) == {"tool.a": (0, ("k",))}


def test_nan_priority_falls_back_to_zero():
    assert normalize({"tool.a": {"priority": float("nan"), "keywords": ["k"]}}) == {"tool.a": (0, ("k",))}


def test_valid_entries_are_unchanged():
    """Control: the builder's own output still normalizes exactly as before."""
    index = {
        "tool.a": {"priority": 3, "keywords": ["search", "find"]},
        "tool.b": {"priority": 0, "keywords": ["read"]},
    }

    assert normalize(index) == {"tool.a": (3, ("search", "find")), "tool.b": (0, ("read",))}


def test_entry_without_keywords_is_dropped():
    """Existing rule: an entry that cannot match text is not indexed."""
    assert normalize({"tool.a": {"priority": 1, "keywords": []}}) == {}
    assert normalize({"tool.a": {"priority": 1, "keywords": "search"}}) == {}


def test_empty_name_is_dropped():
    assert normalize({"": {"priority": 1, "keywords": ["k"]}}) == {}


@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        pytest.param(float("inf"), 0, id="positive-infinity"),
        pytest.param(float("-inf"), 0, id="negative-infinity"),
        pytest.param(float("nan"), 0, id="nan"),
        pytest.param(None, 0, id="none"),
        pytest.param("invalid", 0, id="invalid-string"),
        pytest.param([], 0, id="invalid-list"),
        pytest.param("7", 7, id="numeric-string"),
        pytest.param(7.5, 7, id="finite-float"),
        pytest.param(-2, -2, id="negative-int"),
        pytest.param(True, 1, id="bool"),
    ],
)
def test_builder_and_serialized_index_share_priority_coercion(priority, expected):
    @tool
    def routed_search(query: str) -> str:
        """Search test data."""
        return query

    routing = {"mode": "prefer", "priority": priority, "keywords": ["search"]}
    tag_mcp_routing(tag_mcp_tool(routed_search), routing)
    tools, setup = assemble_deferred_tools([routed_search], enabled=True)

    middleware = build_mcp_routing_middleware(tools, setup, top_k=1)

    assert isinstance(middleware, McpRoutingMiddleware)
    assert middleware._routing_index == normalize({"routed_search": routing}) == {"routed_search": (expected, ("search",))}
    assert middleware._matched_names({"messages": [HumanMessage(content="search")]}) == ["routed_search"]
