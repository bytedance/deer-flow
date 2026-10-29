"""Real plugin/tool/budget/checkpoint roundtrip, with no provider or model calls."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_messages, convert_to_openai_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.serialization import serialize_channel_values_for_api


@pytest.fixture
def retrieval_plugin(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-retrieval"))

    def load(config=None):
        loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_retrieval:install", config={} if config is None else config)])
        assert diagnostics == []
        return loaded

    return load


def _graph(tool, saver, *, mode="full", limit=10000):
    budget = ToolOutputBudgetMiddleware(ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=limit))
    graph = StateGraph(get_thread_state_schema(mode))
    graph.add_node("tools", ToolNode([tool], awrap_tool_call=budget.awrap_tool_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile(checkpointer=saver)


def _call(tool, query, *, call_id="call-retrieval-1"):
    return AIMessage(content="", id=f"request-{call_id}", tool_calls=[{"id": call_id, "name": tool.name, "args": query, "type": "tool_call"}])


def test_retrieval_example_is_disabled_until_the_operator_enables_it(retrieval_plugin):
    loaded = retrieval_plugin()
    assert len(loaded.plugins) == 1
    assert build_plugin_tools(loaded) == []
    (tool,) = build_plugin_tools(retrieval_plugin({"enabled": True}))
    assert tool.name.startswith("ext_")
    assert tool.name not in {"knowledge_search", "task"}
    assert "synthetic" in tool.description.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("limit", [120, 10000])
async def test_plugin_artifact_survives_budget_sqlite_reopen_and_later_turn(tmp_path, retrieval_plugin, mode, limit):
    (tool,) = build_plugin_tools(retrieval_plugin({"enabled": True}))
    config = {"configurable": {"thread_id": "retrieval-roundtrip"}}
    inject_checkpoint_mode(config, mode)
    context = {"user_id": "alice", "thread_id": "retrieval-roundtrip"}
    database = str(tmp_path / "checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = _graph(tool, saver, mode=mode, limit=limit)
        result = await graph.ainvoke({"messages": [HumanMessage(content="Find the synthetic release note.", id="human-1"), _call(tool, {"query": "RELEASE"})]}, config, context=context)
        message = result["messages"][-1]
        assert isinstance(message, ToolMessage)
        assert (message.name, message.tool_call_id, message.status) == (tool.name, "call-retrieval-1", "success")
        assert message.id
        assert isinstance(message.content, str) and len(message.content) <= limit
        assert message.artifact["schema"] == "example.retrieval.v1"
        assert message.artifact["synthetic"] is True
        assert [item["document_id"] for item in message.artifact["matches"]] == ["demo-release"]
        assert "Tuesday" in message.artifact["matches"][0]["excerpt"]
        if limit == 120:
            assert message.additional_kwargs["deerflow_tool_transforms"][-1]["kind"] == "truncated"
            assert len(message.artifact["matches"][0]["excerpt"]) > len(message.content)
        else:
            assert "Tuesday" in message.content
        saved_message = message.model_dump()

    # New saver and graph, not a live object/cache from the first invocation.
    async with AsyncSqliteSaver.from_conn_string(database) as reopened:
        graph = _graph(tool, reopened, mode=mode, limit=limit)
        accessor = CheckpointStateAccessor.bind(graph, reopened, mode=mode)
        snapshot = await accessor.aget(config)
        restored = snapshot.values["messages"][-1]
        assert restored.model_dump() == saved_message
        api_state = json.loads(json.dumps(serialize_channel_values_for_api(snapshot.values)))
        assert api_state["messages"][-1]["artifact"] == saved_message["artifact"]
        assert api_state["messages"][-1]["content"] == saved_message["content"]
        assert api_state["messages"][-1]["name"] == tool.name
        assert api_state["messages"][-1]["id"] == saved_message["id"]
        assert api_state["messages"][-1]["tool_call_id"] == "call-retrieval-1"
        assert convert_to_messages(api_state["messages"])[-1].model_dump() == saved_message

        continued = await graph.ainvoke({"messages": [HumanMessage(content="Now find support.", id="human-2"), _call(tool, {"query": "support"}, call_id="call-retrieval-2")]}, config, context=context)
        old = next(msg for msg in continued["messages"] if isinstance(msg, ToolMessage) and msg.tool_call_id == "call-retrieval-1")
        assert old.model_dump() == saved_message
        newest = continued["messages"][-1]
        assert newest.artifact["matches"][0]["document_id"] == "demo-support"
        model_messages = convert_to_openai_messages(continued["messages"])
        model_tools = [msg for msg in model_messages if msg["role"] == "tool"]
        assert [msg["tool_call_id"] for msg in model_tools] == ["call-retrieval-1", "call-retrieval-2"]
        assert model_tools[0]["content"] == saved_message["content"]
        assert model_tools[-1]["content"] == newest.content
        assert all("artifact" not in msg for msg in model_tools)
        assert "example.retrieval.v1" not in json.dumps(model_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"query": ""}, {"query": "   "}, {"query": 7}, {"query": "release", "user_id": "bob"}])
async def test_invalid_retrieval_arguments_are_rejected_by_real_tool_dispatch(retrieval_plugin, payload):
    (tool,) = build_plugin_tools(retrieval_plugin({"enabled": True}))
    result = await _graph(tool, None).ainvoke({"messages": [_call(tool, payload)]}, context={"user_id": "alice"})
    message = result["messages"][-1]
    assert (message.name, message.tool_call_id, message.status) == (tool.name, "call-retrieval-1", "error")
    assert message.artifact is None


@pytest.mark.asyncio
async def test_no_matches_is_a_successful_empty_result(retrieval_plugin):
    (tool,) = build_plugin_tools(retrieval_plugin({"enabled": True}))
    result = await _graph(tool, None).ainvoke({"messages": [_call(tool, {"query": "not-in-this-corpus"})]}, context={"user_id": "alice"})
    message = result["messages"][-1]
    assert message.status == "success"
    assert "No matching synthetic documents" in message.content
    assert message.artifact == {"schema": "example.retrieval.v1", "synthetic": True, "matches": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("limit", [120, 10000])
async def test_shared_knowledge_sources_from_plugin_survive_budget_and_replay(tmp_path, retrieval_plugin, mode, limit):
    from dataclasses import replace

    from deerflow_extension_api import PluginToolResult

    from deerflow.knowledge import KnowledgeSource, RetrievalHit, RetrievalResult, format_result, sources_from_messages

    source = KnowledgeSource(provider="plugin-test", title="Synthetic captured guide", excerpt="Synthetic retrieved evidence from the provider.")
    content, artifact = format_result(RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)]))

    async def handler(payload, context):
        return PluginToolResult(content, artifact)

    loaded = retrieval_plugin({"enabled": True})
    attribution, plugin = loaded.plugins[0]
    plugin = replace(plugin, tools=(replace(plugin.tools[0], handler=handler),))
    (tool,) = build_plugin_tools(replace(loaded, plugins=((attribution, plugin),)))
    config = {"configurable": {"thread_id": "plugin-knowledge-replay"}}
    inject_checkpoint_mode(config, mode)
    database = str(tmp_path / "knowledge.db")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = _graph(tool, saver, mode=mode, limit=limit)
        result = await graph.ainvoke({"messages": [_call(tool, {"query": "guide"})]}, config, context={"user_id": "alice"})
        message = result["messages"][-1]
        assert message.status == "success"
        expected = [source] if limit == 10000 else []
        assert sources_from_messages([message.model_dump()]) == expected

    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = _graph(tool, saver, mode=mode, limit=limit)
        snapshot = await CheckpointStateAccessor.bind(graph, saver, mode=mode).aget(config)
        restored = json.loads(json.dumps(serialize_channel_values_for_api(snapshot.values)))
        assert sources_from_messages(restored["messages"]) == expected
        assert restored["messages"][-1]["artifact"] == message.artifact
