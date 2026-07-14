"""Tests for PR2 MCP routing auto-promotion."""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware, assert_mcp_routing_before_deferred_filter
from deerflow.agents.thread_state import ThreadState, merge_promoted
from deerflow.tools.builtins.tool_search import assemble_deferred_tools, build_mcp_routing_middleware
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


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


@as_tool
def archive_lookup(query: str) -> str:
    "Search archived records."
    return query


def _routed(tool, *, keywords: list[str], priority: int = 0, mode: str = "prefer"):
    tag_mcp_tool(tool)
    tag_mcp_routing(
        tool,
        {
            "mode": mode,
            "priority": priority,
            "keywords": keywords,
        },
    )
    return tool


def test_builder_indexes_only_deferred_prefer_tools():
    routed = _routed(postgres_query, keywords=["orders"], priority=100)
    off = _routed(metrics_query, keywords=["metrics"], priority=50, mode="off")
    empty_keywords = _routed(archive_lookup, keywords=[], priority=90)
    final_tools, setup = assemble_deferred_tools([active_tool, routed, off, empty_keywords], enabled=True)

    middleware = build_mcp_routing_middleware(final_tools, setup, top_k=3)

    assert isinstance(middleware, McpRoutingMiddleware)
    assert middleware._matched_names({"messages": [HumanMessage(content="show ORDERS")]}) == ["postgres_query"]
    assert middleware._matched_names({"messages": [HumanMessage(content="metrics archive")]}) == []


def test_builder_skips_when_tool_search_disabled_or_no_index():
    routed = _routed(postgres_query, keywords=["orders"], priority=100)
    final_tools, setup = assemble_deferred_tools([routed], enabled=False)

    assert build_mcp_routing_middleware(final_tools, setup, top_k=3) is None

    _, setup = assemble_deferred_tools([_routed(metrics_query, keywords=[], priority=50)], enabled=True)
    assert build_mcp_routing_middleware([metrics_query], setup, top_k=3) is None


def test_matching_uses_latest_real_human_message_only():
    middleware = McpRoutingMiddleware(
        {
            "postgres_query": {"priority": 100, "keywords": ["orders"]},
            "metrics_query": {"priority": 90, "keywords": ["metrics"]},
        },
        "hash1",
        3,
    )

    assert middleware._matched_names({"messages": [HumanMessage(content="orders"), HumanMessage(content="no match now")]}) == []
    assert middleware._matched_names({"messages": [HumanMessage(content="metrics", name="summary"), HumanMessage(content="orders", additional_kwargs={"hide_from_ui": True})]}) == []


def test_matching_supports_casefold_chinese_priority_tiebreak_and_top_k():
    middleware = McpRoutingMiddleware(
        {
            "z_tool": {"priority": 50, "keywords": ["订单"]},
            "a_tool": {"priority": 50, "keywords": ["orders"]},
            "top_tool": {"priority": 100, "keywords": ["ORDERS"]},
        },
        "hash1",
        2,
    )

    assert middleware._matched_names({"messages": [HumanMessage(content="查订单 and orders")]}) == ["top_tool", "a_tool"]


def test_structured_original_user_text_is_used():
    middleware = McpRoutingMiddleware(
        {"postgres_query": {"priority": 100, "keywords": ["orders"]}},
        "hash1",
        3,
    )
    message = HumanMessage(
        content=[{"type": "text", "text": "sanitized replacement"}],
        additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "show orders"},
    )

    assert middleware._matched_names({"messages": [message]}) == ["postgres_query"]


def test_before_model_returns_minimal_promoted_update_and_reducer_unions():
    middleware = McpRoutingMiddleware(
        {"postgres_query": {"priority": 100, "keywords": ["orders"]}},
        "hash1",
        3,
    )

    update = middleware.before_model(
        {"messages": [HumanMessage(content="orders")], "promoted": {"catalog_hash": "hash1", "names": ["metrics_query"]}},
        runtime=None,
    )

    assert update == {"promoted": {"catalog_hash": "hash1", "names": ["postgres_query"]}}
    assert merge_promoted({"catalog_hash": "hash1", "names": ["metrics_query"]}, update["promoted"]) == {
        "catalog_hash": "hash1",
        "names": ["metrics_query", "postgres_query"],
    }


@pytest.mark.asyncio
async def test_abefore_model_matches_sync_behavior():
    middleware = McpRoutingMiddleware(
        {"postgres_query": {"priority": 100, "keywords": ["orders"]}},
        "hash1",
        3,
    )

    assert await middleware.abefore_model({"messages": [HumanMessage(content="orders")]}, runtime=None) == {"promoted": {"catalog_hash": "hash1", "names": ["postgres_query"]}}


def test_no_match_and_missing_catalog_hash_return_no_update():
    assert McpRoutingMiddleware({"postgres_query": {"priority": 100, "keywords": ["orders"]}}, None, 3).before_model({"messages": [HumanMessage(content="orders")]}, runtime=None) is None
    assert McpRoutingMiddleware({"postgres_query": {"priority": 100, "keywords": ["orders"]}}, "hash1", 3).before_model({"messages": [HumanMessage(content="nothing")]}, runtime=None) is None


def test_order_invariant_rejects_reversed_middlewares():
    routing = McpRoutingMiddleware({"postgres_query": {"priority": 100, "keywords": ["orders"]}}, "hash1", 3)
    deferred = DeferredToolFilterMiddleware(frozenset({"postgres_query"}), "hash1")

    assert_mcp_routing_before_deferred_filter([routing, deferred])
    with pytest.raises(RuntimeError, match="McpRoutingMiddleware must be installed before DeferredToolFilterMiddleware"):
        assert_mcp_routing_before_deferred_filter([deferred, routing])


def test_auto_promote_makes_schema_visible_in_same_model_cycle():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    routed = _routed(postgres_query, keywords=["orders"], priority=100)
    other = _routed(metrics_query, keywords=["metrics"], priority=90)
    final_tools, setup = assemble_deferred_tools([active_tool, routed, other], enabled=True)
    routing_middleware = build_mcp_routing_middleware(final_tools, setup, top_k=3)
    assert routing_middleware is not None

    model = RecordingModel(messages=iter([AIMessage(content="done")]))
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=[
            routing_middleware,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="show orders")]}))

    assert "postgres_query" in bound[0]
    assert "metrics_query" not in bound[0]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["postgres_query"]}
    assert not any(isinstance(message, ToolMessage) for message in result["messages"])


def test_auto_promoted_tool_can_be_called_without_tool_search():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    routed = _routed(postgres_query, keywords=["orders"], priority=100)
    final_tools, setup = assemble_deferred_tools([active_tool, routed], enabled=True)
    routing_middleware = build_mcp_routing_middleware(final_tools, setup, top_k=3)
    assert routing_middleware is not None

    turn1 = AIMessage(content="", tool_calls=[{"name": "postgres_query", "args": {"sql": "select * from orders"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=[
            routing_middleware,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="show orders")]}))

    assert "postgres_query" in bound[0]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["postgres_query"]}
    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert tool_messages
    assert tool_messages[0].name == "postgres_query"
    assert tool_messages[0].status == "success"


def test_explicit_tool_search_merges_with_auto_promoted_names():
    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    routed = _routed(postgres_query, keywords=["orders"], priority=100)
    other = _routed(metrics_query, keywords=["metrics"], priority=90)
    final_tools, setup = assemble_deferred_tools([active_tool, routed, other], enabled=True)
    routing_middleware = build_mcp_routing_middleware(final_tools, setup, top_k=3)
    assert routing_middleware is not None

    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:metrics_query"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))
    graph = create_agent(
        model=model,
        tools=final_tools,
        middleware=[
            routing_middleware,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="show orders")]}))

    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["postgres_query", "metrics_query"],
    }


def test_bootstrap_like_no_mcp_tools_skips_middleware():
    final_tools, setup = assemble_deferred_tools([active_tool], enabled=True)

    assert build_mcp_routing_middleware(final_tools, setup, top_k=3) is None


def test_acp_tool_without_mcp_metadata_is_not_indexed():
    final_tools, setup = assemble_deferred_tools([active_tool], enabled=True)

    assert setup.deferred_names == frozenset()
    assert build_mcp_routing_middleware(final_tools, setup, top_k=3) is None


def test_privacy_no_trace_metadata_or_info_logs(caplog):
    caplog.set_level("INFO")
    middleware = McpRoutingMiddleware(
        {"secret_tool": {"priority": 100, "keywords": ["sensitive-keyword"]}},
        "hash1",
        3,
    )
    state = {
        "messages": [HumanMessage(content="contains sensitive-keyword")],
        "metadata": {"trace": "existing"},
    }

    update = middleware.before_model(state, runtime=None)

    assert update == {"promoted": {"catalog_hash": "hash1", "names": ["secret_tool"]}}
    assert state["metadata"] == {"trace": "existing"}
    assert "sensitive-keyword" not in caplog.text
    assert "secret_tool" not in caplog.text
