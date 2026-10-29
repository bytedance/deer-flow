"""End-to-end: tool_search promotes a deferred tool into the next model turn.

Locks the full loop through a real ``create_agent`` graph:
  turn 1  -> deferred MCP tools hidden from bind_tools; model calls tool_search
  ToolNode-> tool_search returns Command(update={"promoted": {...}}) -> state
  turn 2  -> middleware reads state["promoted"] (hash-scoped) -> the searched
             tool's schema is now bound; un-searched deferred tools stay hidden

This is the behavior #3272's redesign depends on (no ContextVar): promotion
flows through graph state, so it works regardless of build/execute context.
"""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as as_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Overwrite

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool


@as_tool
def active_tool(x: str) -> str:
    "An always-active tool."
    return x


@as_tool
def mcp_calc(expression: str) -> str:
    "Evaluate arithmetic."
    return expression


@as_tool
def mcp_other(x: str) -> str:
    "Another deferred MCP tool."
    return x


def test_tool_search_promotes_into_next_turn():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)], enabled=True)
    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, mcp_other, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="use the deferred calculator", id="user-1")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted (visible); the un-searched one stays hidden.
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    # Promotion recorded in graph state, scoped by catalog and user turn.
    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["mcp_calc"],
        "turn_id": "user-1",
    }


def test_promoted_schema_is_deferred_again_on_next_user_turn():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc)], enabled=True)
    search = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "search-1", "type": "tool_call"}])
    model = RecordingModel(messages=iter([search, AIMessage(content="first done"), AIMessage(content="second done")]))
    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "turn-scoped-promotion"}}

    asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="calculate", id="user-1")]}, config))
    asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="now just say hello", id="user-2")]}, config))

    assert "mcp_calc" not in bound[0]
    assert "mcp_calc" in bound[1]
    assert "mcp_calc" not in bound[2]


def test_promoted_schema_survives_checkpoint_resume_within_same_turn():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc)], enabled=True)
    search = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "search-1", "type": "tool_call"}])
    model = RecordingModel(messages=iter([search, AIMessage(content="done")]))
    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
        interrupt_after=["tools"],
    )
    config = {"configurable": {"thread_id": "resume-turn-scoped-promotion"}}

    interrupted = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="calculate", id="user-1")]}, config))
    resumed = asyncio.run(graph.ainvoke(None, config))

    assert interrupted["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["mcp_calc"],
        "turn_id": "user-1",
    }
    assert resumed["promoted"] == interrupted["promoted"]
    assert "mcp_calc" not in bound[0]
    assert "mcp_calc" in bound[1]


def test_in_flight_legacy_checkpoint_promotion_migrates_on_resume():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc)], enabled=True)
    search = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "search-1", "type": "tool_call"}])
    model = RecordingModel(messages=iter([search, AIMessage(content="done")]))
    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
        interrupt_after=["tools"],
    )
    config = {"configurable": {"thread_id": "resume-legacy-promotion"}}

    asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="calculate", id="user-1")]}, config))
    graph.update_state(
        config,
        {
            "promoted": Overwrite(
                {
                    "catalog_hash": setup.catalog_hash,
                    "names": ["mcp_calc"],
                }
            )
        },
        as_node="tools",
    )
    resumed = asyncio.run(graph.ainvoke(None, config))

    assert resumed["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["mcp_calc"],
        "turn_id": "user-1",
    }
    assert "mcp_calc" not in bound[0]
    assert "mcp_calc" in bound[1]


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
def test_routing_preserves_searched_tools_on_legacy_checkpoint_resume(use_async):
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, tag_mcp_tool(mcp_calc), tag_mcp_tool(mcp_other)], enabled=True)
    search = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "search-1", "type": "tool_call"}])
    calculate = AIMessage(content="", tool_calls=[{"name": "mcp_calc", "args": {"expression": "1+1"}, "id": "calc-1", "type": "tool_call"}])
    model = RecordingModel(messages=iter([search, calculate, AIMessage(content="done")]))
    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, mcp_other, setup.tool_search_tool],
        middleware=[
            McpRoutingMiddleware({"mcp_other": {"priority": 1, "keywords": ["calculate"]}}, setup.catalog_hash, 3),
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
        interrupt_after=["tools"],
    )
    config = {"configurable": {"thread_id": "resume-legacy-routing-promotion"}}

    def invoke(value):
        return asyncio.run(graph.ainvoke(value, config)) if use_async else graph.invoke(value, config)

    invoke({"messages": [HumanMessage(content="calculate", id="user-1")]})
    graph.update_state(
        config,
        {"promoted": Overwrite({"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]})},
        as_node="tools",
    )
    resumed = invoke(None)

    assert "mcp_calc" not in bound[0]
    assert {"mcp_calc", "mcp_other"} <= set(bound[1])
    assert resumed["promoted"]["turn_id"] == "user-1"
    assert set(resumed["promoted"]["names"]) == {"mcp_calc", "mcp_other"}
    result = next(message for message in resumed["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "calc-1")
    assert result.status == "success"
    assert result.content == "1+1"
    invoke(None)
