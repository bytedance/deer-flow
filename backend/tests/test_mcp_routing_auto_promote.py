"""Advisory MCP metadata never promotes schemas from natural-language guesses."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as as_tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware, assert_mcp_routing_before_deferred_filter
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    "An always-active tool."
    return x


@as_tool
def postgres_query(sql: str) -> str:
    "Query Postgres."
    return sql


@as_tool
def metrics_query(query: str) -> str:
    "Query metrics."
    return query


def _routed(tool, *, keywords, priority=0, mode="prefer"):
    tag_mcp_tool(tool)
    tag_mcp_routing(tool, {"mode": mode, "priority": priority, "keywords": keywords})
    return tool


def _setup():
    tools, setup = assemble_deferred_tools(
        [
            active_tool,
            _routed(postgres_query, keywords=["orders", "订单"], priority=100),
            _routed(metrics_query, keywords=["metrics"], priority=90),
        ],
        enabled=True,
    )
    routing = build_mcp_routing_middleware(tools, setup, top_k=3)
    assert isinstance(routing, McpRoutingMiddleware)
    return tools, setup, routing


def test_builder_keeps_configuration_compatible_without_implicit_selection():
    _, _, routing = _setup()
    assert set(routing._routing_index) == {"postgres_query", "metrics_query"}
    assert routing._matched_names({"messages": [HumanMessage(content="show ORDERS")]}) == []


def test_builder_skips_without_deferred_routing_metadata():
    routed = _routed(postgres_query, keywords=["orders"])
    tools, setup = assemble_deferred_tools([routed], enabled=False)
    assert build_mcp_routing_middleware(tools, setup, top_k=3) is None
    tools, setup = assemble_deferred_tools([active_tool], enabled=True)
    assert build_mcp_routing_middleware(tools, setup, top_k=3) is None


@pytest.mark.parametrize("text", ["orders", "Do not query orders", "Explain the quoted word 'metrics'", "数据库订单", "BORDERS", "metrics and orders"])
@pytest.mark.parametrize("use_async", [False, True])
def test_user_prose_never_changes_promotions_or_emits_routing_audit(text, use_async, caplog):
    _, _, routing = _setup()
    state = {"messages": [HumanMessage(content=text, id="user-1")], "promoted": {"catalog_hash": "previous", "names": ["active_tool"]}, "metadata": {"trace": "existing"}}
    original = deepcopy(state)
    calls = []
    runtime = SimpleNamespace(context={"__run_journal": SimpleNamespace(record_middleware=lambda **kw: calls.append(kw))})
    update = asyncio.run(routing.abefore_model(state, runtime)) if use_async else routing.before_model(state, runtime)
    assert update is None
    assert state == original
    assert calls == []
    assert text not in caplog.text


@pytest.mark.parametrize("promoted", [None, {}, {"names": "metrics_query"}, {"catalog_hash": "old", "names": ["postgres_query"]}])
def test_malformed_or_stale_state_cannot_create_an_implicit_promotion(promoted):
    _, _, routing = _setup()
    assert routing.before_model({"messages": [HumanMessage(content="orders")], "promoted": promoted}, runtime=None) is None


def test_order_contract_remains_compatible():
    _, setup, routing = _setup()
    deferred = DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)
    assert_mcp_routing_before_deferred_filter([routing, deferred])
    with pytest.raises(RuntimeError, match="must be installed before"):
        assert_mcp_routing_before_deferred_filter([deferred, routing])


def _graph(responses, *, checkpointer=None):
    bound = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    tools, setup, routing = _setup()
    graph = create_agent(model=RecordingModel(messages=iter(responses)), tools=tools, middleware=[routing, DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)], state_schema=ThreadState, checkpointer=checkpointer)
    return graph, bound, setup


def _call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def test_keyword_does_not_expose_schema_in_real_model_cycle():
    graph, bound, setup = _graph([AIMessage(content="done")])
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="show orders", id="user-1")]}))
    assert "postgres_query" not in bound[0] and "metrics_query" not in bound[0]
    assert "tool_search" in bound[0]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": [], "turn_id": "user-1"}


def test_undiscovered_direct_tool_call_is_blocked_even_when_keyword_matches():
    graph, bound, _ = _graph([_call("postgres_query", {"sql": "select * from orders"}, "c1"), AIMessage(content="done")])
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="show orders", id="user-1")]}))
    messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(messages) == 1 and messages[0].status == "error"
    assert "tool_search first" in messages[0].content
    assert all("postgres_query" not in names for names in bound)


def test_explicit_search_promotes_only_selected_tool_then_allows_execution():
    graph, bound, setup = _graph([_call("tool_search", {"query": "select:metrics_query"}, "search-1"), _call("metrics_query", {"query": "request_count"}, "query-1"), AIMessage(content="done")])
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="compare metrics and orders", id="user-1")]}))
    assert "metrics_query" not in bound[0]
    assert "metrics_query" in bound[1]
    assert all("postgres_query" not in names for names in bound)
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["metrics_query"], "turn_id": "user-1"}
    executed = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.name == "metrics_query"]
    assert len(executed) == 1 and executed[0].status == "success"


def test_explicit_promotion_expires_at_next_user_turn():
    graph, bound, setup = _graph([_call("tool_search", {"query": "select:metrics_query"}, "c1"), AIMessage(content="first done"), AIMessage(content="second done")], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "explicit-routing-turn"}}
    asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="metrics", id="user-1")]}, config))
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="metrics again", id="user-2")]}, config))
    assert "metrics_query" in bound[1]
    assert "metrics_query" not in bound[2]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": [], "turn_id": "user-2"}


@pytest.mark.parametrize("catalog,turn", [("old", "user-1"), ("hash1", "old-user")])
def test_explicit_selection_cannot_cross_catalog_or_turn(catalog, turn):
    filter_ = DeferredToolFilterMiddleware(frozenset({"metrics_query"}), "hash1")
    state = {"messages": [HumanMessage(content="metrics", id="user-1")], "promoted": {"catalog_hash": catalog, "turn_id": turn, "names": ["metrics_query"]}}
    assert filter_._hidden(state) == {"metrics_query"}
