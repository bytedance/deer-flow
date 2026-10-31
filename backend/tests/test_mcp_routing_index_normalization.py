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

from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware

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
