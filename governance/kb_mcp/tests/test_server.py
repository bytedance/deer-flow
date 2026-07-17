import os

from governance_kb_mcp.server import create_server


def test_search_knowledge_tool_exists():
    mcp = create_server()
    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    assert "search_knowledge" in tool_names


def test_add_document_tool_exists():
    mcp = create_server()
    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    assert "add_document" in tool_names


def test_list_collections_tool_exists():
    mcp = create_server()
    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    assert "list_collections" in tool_names
