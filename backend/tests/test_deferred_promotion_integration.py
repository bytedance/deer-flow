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

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup


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


def _tag(t):
    t.metadata = {**(t.metadata or {}), "deerflow_mcp": True}
    return t


def test_tool_search_promotes_into_next_turn():
    bound: list[list[str]] = []

    class RecordingModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append([getattr(t, "name", None) for t in tools])
            return self

    setup = build_deferred_tool_setup([active_tool, _tag(mcp_calc), _tag(mcp_other)], enabled=True)
    turn1 = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_calc"}, "id": "c1", "type": "tool_call"}])
    turn2 = AIMessage(content="done")
    model = RecordingModel(messages=iter([turn1, turn2]))

    graph = create_agent(
        model=model,
        tools=[active_tool, mcp_calc, mcp_other, setup.tool_search_tool],
        middleware=[DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash)],
        state_schema=ThreadState,
    )

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="use the deferred calculator")]}))

    assert len(bound) >= 2, f"expected >=2 model binds, got {bound}"
    # Turn 1: both deferred MCP tools hidden.
    assert "mcp_calc" not in bound[0] and "mcp_other" not in bound[0]
    # Turn 2: the searched tool is promoted (visible); the un-searched one stays hidden.
    assert "mcp_calc" in bound[1]
    assert "mcp_other" not in bound[1]
    # Promotion recorded in graph state, scoped by catalog hash.
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["mcp_calc"]}
