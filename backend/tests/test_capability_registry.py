"""The directory is data; installation identity and execution are not display names."""

from types import SimpleNamespace

import pytest

from deerflow.capabilities.catalog import load_catalog
from deerflow.capabilities.runtime import filter_mcp_plugins, installation_id
from deerflow.config.extensions_config import ExtensionsConfig


def test_catalog_has_separate_transport_auth_and_contributions():
    catalog = load_catalog()
    assert len({entry.id for entry in catalog}) == len(catalog)
    github = next(entry for entry in catalog if entry.id == "github")
    assert github.adapter == "mcp"
    assert "api_key" in github.auth_methods
    assert github.version
    assert github.config_schema["type"] == "object"
    assert next(entry for entry in catalog if entry.id == "lark").adapter == "lark"


def test_installation_identity_ignores_display_and_credentials():
    assert installation_id("example", {}) == installation_id("example", {"headers": {"Authorization": "secret"}})
    assert installation_id("one", {"capability": {"id": "persistent"}}) == installation_id("renamed", {"capability": {"id": "persistent"}})
    assert installation_id("one", {}) != installation_id("two", {})


def test_agent_selection_filters_by_source_not_tool_name():
    config = ExtensionsConfig.model_validate({"mcpServers": {"one": {"enabled": True}, "two": {"enabled": True}}})
    ordinary = SimpleNamespace(name="one_fake", metadata={})
    first = SimpleNamespace(name="search", metadata={"deerflow_mcp": True, "deerflow_mcp_source": {"server_name": "one"}})
    second = SimpleNamespace(name="one_search", metadata={"deerflow_mcp": True, "deerflow_mcp_source": {"server_name": "two"}})
    unknown = SimpleNamespace(name="legacy", metadata={"deerflow_mcp": True})
    tools = [ordinary, first, second, unknown]
    assert filter_mcp_plugins(tools, None, config) == tools
    assert filter_mcp_plugins(tools, [], config) == [ordinary]
    assert filter_mcp_plugins(tools, [installation_id("one", {})], config) == [ordinary, first]
    config.mcp_servers["one"].enabled = False
    assert filter_mcp_plugins(tools, [installation_id("one", {})], config) == [ordinary]


def test_duplicate_manifest_ids_fail_instead_of_shadowing(tmp_path):
    manifest = load_catalog()[0].model_dump()
    import json

    source = tmp_path / "catalog.json"
    source.write_text(json.dumps([manifest, manifest]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_catalog(source)


@pytest.mark.asyncio
async def test_selected_mcp_executes_real_stdio_tool_without_mutating_shared_catalog(tmp_path, monkeypatch):
    """No network or LLM: discover and invoke an actual MCP subprocess."""
    import sys

    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.mcp.tools import get_mcp_tools
    from deerflow.tools import get_available_tools
    from deerflow.tools.mcp_metadata import is_mcp_tool

    server = tmp_path / "server.py"
    server.write_text('from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("fixture")\n@mcp.tool()\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\nmcp.run()\n')
    config = ExtensionsConfig.model_validate({"mcpServers": {"fixture": {"enabled": True, "command": sys.executable, "args": [str(server)]}}})
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *args: config)
    discovered = await get_mcp_tools()
    assert len(discovered) == 1
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: discovered)
    app_config = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    selected = get_available_tools(app_config=app_config, mcp_plugins=[installation_id("fixture", {})])
    tool = next(tool for tool in selected if is_mcp_tool(tool))
    # Without a thread ID, the existing wrapper uses a temporary connection.
    result = await tool.ainvoke({"a": 19, "b": 23})
    assert "42" in str(result)
    assert not any(is_mcp_tool(tool) for tool in get_available_tools(app_config=app_config, mcp_plugins=[]))
    assert any(is_mcp_tool(tool) for tool in get_available_tools(app_config=app_config))
