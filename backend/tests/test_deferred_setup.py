from langchain_core.tools import tool as as_tool
from langgraph.types import Command

from deerflow.tools.builtins.tool_search import DeferredToolCatalog, build_deferred_tool_setup, build_tool_search_tool
from deerflow.tools.mcp_metadata import is_mcp_tool, tag_mcp_tool


@as_tool
def mcp_calc(expression: str) -> str:
    "Evaluate arithmetic."
    return expression


@as_tool
def local_echo(text: str) -> str:
    "Echo text."
    return text


def test_is_mcp_tool_reads_metadata():
    assert is_mcp_tool(tag_mcp_tool(mcp_calc)) is True
    assert is_mcp_tool(local_echo) is False


def test_setup_disabled_returns_empty():
    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_calc), local_echo], enabled=False)
    assert setup.tool_search_tool is None
    assert setup.deferred_names == frozenset()
    assert setup.catalog_hash is None


def test_setup_no_mcp_returns_empty():
    setup = build_deferred_tool_setup([local_echo], enabled=True)
    assert setup.tool_search_tool is None
    assert setup.deferred_names == frozenset()


def test_setup_builds_from_mcp_survivors():
    setup = build_deferred_tool_setup([tag_mcp_tool(mcp_calc), local_echo], enabled=True)
    assert setup.deferred_names == frozenset({"mcp_calc"})
    assert setup.tool_search_tool is not None
    assert setup.tool_search_tool.name == "tool_search"
    assert setup.catalog_hash


def test_tool_search_returns_command_with_hash_scoped_promotion():
    catalog = DeferredToolCatalog((mcp_calc,))
    ts = build_tool_search_tool(catalog)
    out = ts.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "tc1"})
    assert isinstance(out, Command)
    promoted = out.update["promoted"]
    assert promoted == {"catalog_hash": catalog.hash, "names": ["mcp_calc"]}
    msg = out.update["messages"][0]
    assert msg.tool_call_id == "tc1" and msg.name == "tool_search"
    assert "mcp_calc" in msg.content


def test_tool_search_no_match_empty_names():
    catalog = DeferredToolCatalog((mcp_calc,))
    ts = build_tool_search_tool(catalog)
    out = ts.invoke({"type": "tool_call", "name": "tool_search", "args": {"query": "select:nonexistent"}, "id": "tc2"})
    assert out.update["promoted"]["names"] == []
