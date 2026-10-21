"""Exercise actual LangGraph tool dispatch, not just manifest serialization."""

import asyncio
import json
from dataclasses import FrozenInstanceError, dataclass, replace
from types import MappingProxyType, SimpleNamespace

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


@pytest.mark.asyncio
async def test_model_tool_receives_run_control_from_host_runtime(installed):
    from unittest.mock import Mock

    from deerflow_extension_api import AGENT_RUNS_CONTEXT_KEY

    loaded, plugin, calls = installed
    (tool,) = build_plugin_tools(loaded)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    scoped = object()
    handle = SimpleNamespace(for_plugin=Mock(return_value=scoped))
    await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": tool.name, "args": {"query": "hello"}}])]},
        context={"user_id": "alice", "thread_id": "thread", AGENT_RUNS_CONTEXT_KEY: handle},
    )
    handle.for_plugin.assert_called_once_with(plugin.namespace)
    assert calls[0].agent_runs is scoped


def _tool_graph(plugin, declaration):
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(replace(plugin, tools=(declaration,)))
    (tool,) = build_plugin_tools(registry.build())
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(), tool


async def _call_tool(graph, tool, **context):
    result = await graph.ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "artifact-call", "name": tool.name, "args": {"query": "hello"}}])]},
        context={"user_id": "trusted-user", "thread_id": "thread-a", **context},
    )
    return result["messages"][-1]


@pytest.mark.asyncio
async def test_opt_in_mode_rejects_legacy_tuple_through_real_tool_node(installed):
    # A trusted package can subclass the old declaration. This drives ToolNode
    # even on a pre-feature host, exposing ignored response-format declarations.
    @dataclass(frozen=True)
    class ArtifactTool(ModelTool):
        response_format: str = "content_and_artifact"

    async def handler(payload, context):
        return ("visible", {"private": "must not become content"})

    _, plugin, _ = installed
    old = plugin.tools[0]
    graph, tool = _tool_graph(plugin, ArtifactTool(old.name, old.description, old.input_schema, handler))
    message = await _call_tool(graph, tool)
    assert message.status == "error"
    assert message.artifact is None
    assert "must not become content" not in message.content


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact", [None, {"rows": [{"label": "故障", "score": 0.9}]}])
async def test_typed_result_separates_content_from_artifact_and_preserves_identity(installed, artifact):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    contexts = []

    async def handler(payload, context):
        contexts.append(context)
        return PluginToolResult("One record classified.", artifact)

    declaration = replace(plugin.tools[0], handler=handler, response_format="content_and_artifact")
    graph, tool = _tool_graph(plugin, declaration)
    message = await _call_tool(graph, tool)
    assert (message.content, message.artifact, message.status) == ("One record classified.", artifact, "success")
    assert (message.tool_call_id, message.name) == ("artifact-call", tool.name)
    assert (contexts[0].principal.user_id, contexts[0].thread_id) == ("trusted-user", "thread-a")
    assert "runtime" not in json.dumps(tool.tool_call_schema)


@pytest.mark.asyncio
async def test_artifact_is_independent_json_snapshot(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    rows = [{"label": "original"}]
    artifact = MappingProxyType({"rows": rows})

    async def handler(payload, context):
        return PluginToolResult("ready", artifact)

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    rows[0]["label"] = "changed after return"
    assert message.artifact == {"rows": [{"label": "original"}]}
    json.dumps(message.artifact, allow_nan=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["plain", "tuple", "bad-content", "list-artifact", "nan", "object", "int-key", "bool-key", "null-key", "float-key", "key-collision", "nested-key", "list-key", "tuple-key"])
async def test_opt_in_invalid_result_is_sanitized_without_artifact(installed, kind):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    values = {
        "plain": {"sensitive": "secret"},
        "tuple": ("visible", {"sensitive": "secret"}),
        "bad-content": PluginToolResult({"sensitive": "secret"}, None),
        "list-artifact": PluginToolResult("visible", ["secret"]),
        "nan": PluginToolResult("visible", {"score": float("nan")}),
        "object": PluginToolResult("visible", {"sensitive": object()}),
        "int-key": PluginToolResult("visible", {1: "secret"}),
        "bool-key": PluginToolResult("visible", {True: "secret"}),
        "null-key": PluginToolResult("visible", {None: "secret"}),
        "float-key": PluginToolResult("visible", {1.5: "secret"}),
        "key-collision": PluginToolResult("visible", {1: "secret", "1": "other"}),
        "nested-key": PluginToolResult("visible", {"record": {1: "secret", "1": "other"}}),
        "list-key": PluginToolResult("visible", {"rows": [{1: "secret"}]}),
        "tuple-key": PluginToolResult("visible", {"rows": ({1: "secret"},)}),
    }

    async def handler(payload, context):
        return values[kind]

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    assert message.status == "error"
    assert message.artifact is None
    assert message.content == "Plugin tool unavailable or input rejected."


@pytest.mark.asyncio
@pytest.mark.parametrize("over_limit", [False, True])
async def test_artifact_mode_combines_utf8_content_and_artifact_budget(installed, over_limit):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    artifact = {"value": "中" * 1000}
    overhead = len(json.dumps({"content": "", "artifact": artifact}, ensure_ascii=False).encode())
    content = "a" * (64 * 1024 - overhead + int(over_limit))

    async def handler(payload, context):
        return PluginToolResult(content, artifact)

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    message = await _call_tool(graph, tool)
    if over_limit:
        assert message.status == "error"
        assert message.artifact is None
        assert message.content == "Plugin result exceeds 64 KiB."
    else:
        assert message.status == "success"
        assert message.content == content
        assert message.artifact == artifact


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{"text": "中文"}, ("legacy tuple", {"a": 1}), "quoted string", None, {1: "integer", "nested": {None: "null"}}])
async def test_default_mode_keeps_legacy_json_encoding(installed, value):
    _, plugin, _ = installed

    async def handler(payload, context):
        return value

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler))
    message = await _call_tool(graph, tool)
    assert message.content == json.dumps(value, ensure_ascii=False, allow_nan=False)
    assert message.artifact is None


@pytest.mark.asyncio
async def test_default_mode_cannot_serialize_typed_artifact_result(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    result = PluginToolResult("visible", {"sensitive": "secret"})
    # This is also what the old host's unchanged JSON path does.
    with pytest.raises(TypeError):
        json.dumps(result)

    async def handler(payload, context):
        return result

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler))
    message = await _call_tool(graph, tool)
    assert message.status == "error" and message.artifact is None
    assert message.content == "Plugin tool unavailable or input rejected."


@pytest.mark.asyncio
async def test_artifact_mode_propagates_caller_cancellation(installed):
    _, plugin, _ = installed
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def handler(payload, context):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    graph, tool = _tool_graph(plugin, replace(plugin.tools[0], handler=handler, response_format="content_and_artifact"))
    task = asyncio.create_task(_call_tool(graph, tool))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_new_contract_keeps_old_positional_signature_and_is_frozen(installed):
    from deerflow_extension_api import PluginToolResult

    _, plugin, _ = installed
    old = plugin.tools[0]
    declaration = ModelTool(old.name, old.description, old.input_schema, old.handler, "custom-group")
    assert declaration.response_format == "content" and declaration.group == "custom-group"
    with pytest.raises(TypeError):
        ModelTool(old.name, old.description, old.input_schema, old.handler, "custom-group", "content_and_artifact")
    result = PluginToolResult("visible", None)
    with pytest.raises(FrozenInstanceError):
        result.content = "changed"


@pytest.mark.parametrize("mode", ["unknown", None, []])
def test_invalid_response_format_rejects_whole_plugin_before_registration(installed, mode):
    _, plugin, _ = installed
    registry = ExtensionRegistry()
    declaration = replace(plugin.tools[0], name="other", response_format=mode)
    with registry.attributed_to("test"):
        with pytest.raises(ValueError, match="response format"):
            registry.plugin(replace(plugin, tools=(*plugin.tools, declaration)))
    assert not registry.build().plugins
