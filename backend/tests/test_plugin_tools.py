"""Exercise actual LangGraph tool dispatch, not just manifest serialization."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from deerflow_extension_api.plugins import ModelTool, PluginContribution
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.extensions.plugin_tools import build_plugin_tools
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture
def installed():
    calls = []

    async def search(payload, context):
        calls.append(context)
        return {"query": payload["query"], "user": context.principal.user_id}

    plugin = PluginContribution(
        namespace="community.search",
        title="Search",
        enabled=True,
        tools=(ModelTool("search", "Search selected documents", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}, search),),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(plugin)
    return registry.build(), plugin, calls


@pytest.mark.asyncio
async def test_real_tool_node_binds_identity_and_deployment_policy(installed):
    loaded, plugin, calls = installed
    (tool,) = build_plugin_tools(loaded)
    assert "runtime" not in json.dumps(tool.tool_call_schema)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    agent = graph.compile()

    async def invoke(args):
        return (
            await agent.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"id": "c", "name": tool.name, "args": args}])]},
                context={"user_id": "trusted-user", "thread_id": "thread-a"},
            )
        )["messages"][-1]

    result = await invoke({"query": "hello"})
    assert json.loads(result.content) == {"query": "hello", "user": "trusted-user"}
    assert calls[0].thread_id == "thread-a"
    with pytest.raises(TypeError):
        calls[0].settings["enabled"] = False
    assert (await invoke({"query": "x", "user_id": "victim"})).status == "error"
    assert len(calls) == 1
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, enabled=False))
    assert build_plugin_tools(registry.build()) == []


def test_registration_rejects_invalid_schema_without_partial_install(installed):
    _, plugin, _ = installed
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        for schema in ({"type": "string"}, {"type": "object", "$ref": "https://example.test/schema"}, {"type": "object", "properties": {"runtime": {"type": "string"}}}):
            with pytest.raises(ValueError):
                registry.plugin(replace(plugin, tools=(replace(plugin.tools[0], input_schema=schema),)))
            assert not registry.build().plugins


def test_group_filter_and_name_collision_fail_closed(installed):
    loaded, _, _ = installed
    assert build_plugin_tools(loaded, groups=["web"]) == []
    (tool,) = build_plugin_tools(loaded, groups=["extensions"])
    with pytest.raises(ValueError, match="collision"):
        build_plugin_tools(loaded, reserved_names={tool.name})


def test_built_tools_carry_host_recorded_plugin_provenance(installed):
    """The tag is written at construction, from registry-validated values."""
    from deerflow.tools.tool_provenance import get_plugin_source, is_plugin_tool, resolve_tool_provenance

    loaded, plugin, _ = installed
    (tool,) = build_plugin_tools(loaded)

    assert is_plugin_tool(tool) is True
    assert get_plugin_source(tool) == {
        "namespace": plugin.namespace,
        "declaration": "search",
        "installation": "test",
    }
    provenance = resolve_tool_provenance(tool)
    assert provenance is not None
    assert provenance.source == f"plugin:{plugin.namespace}"
    assert provenance.declaration == "search"


@pytest.mark.parametrize("source", ["config", "builtin", "mcp", "acp"])
def test_assembly_keeps_ordinary_and_unaffected_plugin_tools_on_collision(installed, monkeypatch, caplog, source):
    from langchain_core.tools import Tool

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.extensions.plugin_tools import plugin_tool_name
    from deerflow.tools import tools as assembly

    loaded, plugin, _ = installed
    name = plugin_tool_name(plugin.namespace, "search")
    ordinary = Tool(name=name, description="Ordinary tool", func=lambda query: "ordinary result")
    healthy = replace(plugin, namespace="community.healthy")
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(plugin)
        registry.plugin(healthy)
    config = SimpleNamespace(
        tools=[SimpleNamespace(name=name, use="test:ordinary", group="extensions")] if source == "config" else [],
        models=[],
        acp_agents={"test": {}} if source == "acp" else {},
    )
    monkeypatch.setattr(assembly, "BUILTIN_TOOLS", [ordinary] if source == "builtin" else [])
    monkeypatch.setattr(assembly, "is_mcp_task_runtime_available", lambda: False)
    monkeypatch.setattr(assembly, "is_host_bash_allowed", lambda config: False)
    monkeypatch.setattr(assembly, "resolve_variable", lambda *args: ordinary)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: SimpleNamespace(get_enabled_mcp_servers=lambda: {"test": {}}))
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [ordinary])
    monkeypatch.setattr("deerflow.tools.builtins.invoke_acp_agent_tool.build_invoke_acp_agent_tool", lambda agents: ordinary)

    result = assembly.get_available_tools(app_config=config, extensions=registry.build(), include_mcp=source == "mcp", include_upload_tool=False)
    assert [tool.name for tool in result] == [name, plugin_tool_name(healthy.namespace, "search")]
    assert result[0] is ordinary
    assert result[0].invoke("hello") == "ordinary result"
    assert "Duplicate tool name" in caplog.text

    # A host collision must not weaken the strict plugin-vs-plugin check.
    duplicate_snapshot = replace(loaded, plugins=loaded.plugins + loaded.plugins)
    with pytest.raises(ValueError, match="collision"):
        assembly.get_available_tools(app_config=config, extensions=duplicate_snapshot, include_mcp=False, include_upload_tool=False)
