"""A Steer stays inside the Run's promotion scope for deferred MCP tools.

Steers are delivered as ordinary user messages in the middle of a Run. They
must not reset the tools that ``tool_search`` or routing promoted earlier in the
same Run; the next Run's own opening message still does.
"""

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
from deerflow.agents.middlewares.message_utils import genuine_user_turn_id
from deerflow.agents.middlewares.run_input_middleware import RunInputAdmissionMiddleware, RunInputMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.runtime.runs.input_control import RunInputControl
from deerflow.runtime.runs.inputs import INPUT_CONTEXT_KEY, RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool


def test_turn_id_skips_a_steer_delivered_inside_the_run():
    opening = HumanMessage(content="Build it", id="user-1")
    steer = HumanMessage(content="Also label it", id="steer-1", additional_kwargs={"run_input_id": "input-1", "run_input_source": "user", "run_id": "run"})

    assert genuine_user_turn_id([opening, AIMessage(content="working"), steer]) == "user-1"
    assert genuine_user_turn_id([opening, steer, HumanMessage(content="Next request", id="user-2")]) == "user-2"


class SteeredModel(BaseChatModel):
    """Search for the issue tool, run a slow build, then use the tool after the Steer."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    bound: list

    @property
    def _llm_type(self):
        return "steered-promotion-model"

    def bind_tools(self, tools, **kwargs):
        self.bound.append({getattr(t, "name", None) for t in tools})
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        results = {m.name for m in messages if isinstance(m, ToolMessage)}
        steered = any(m.additional_kwargs.get("run_input_id") for m in messages)
        opening = _latest_opening(messages)
        if opening.id != "user-1":
            message = AIMessage(content="hello")
        elif not any(isinstance(m, AIMessage) for m in messages[messages.index(opening) :]):
            message = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_create_issue"}, "id": "search"}])
        elif "slow_build" not in results:
            message = AIMessage(content="", tool_calls=[{"name": "slow_build", "args": {}, "id": "build"}])
        elif steered and "mcp_create_issue" not in results:
            message = AIMessage(content="", tool_calls=[{"name": "mcp_create_issue", "args": {"title": "Build failure"}, "id": "issue"}])
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


def _latest_opening(messages):
    return next(m for m in reversed(messages) if isinstance(m, HumanMessage) and not m.additional_kwargs.get("run_input_id"))


async def _run_with_steer(steer_text, *, routing_index=None):
    entered, release = asyncio.Event(), asyncio.Event()
    created = []

    @tool
    async def slow_build() -> str:
        """Run the long build."""
        entered.set()
        await release.wait()
        return "built"

    @tool
    def mcp_create_issue(title: str) -> str:
        """Create an issue."""
        created.append(title)
        return "created"

    @tool
    def mcp_add_label(label: str) -> str:
        """Add a label to an issue."""
        return "labelled"

    setup = build_deferred_tool_setup([slow_build, tag_mcp_tool(mcp_create_issue), tag_mcp_tool(mcp_add_label)], enabled=True)
    middleware = [RunInputAdmissionMiddleware()]
    if routing_index is not None:
        middleware.append(McpRoutingMiddleware(routing_index, setup.catalog_hash, 3))
    middleware += [DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash), RunInputMiddleware()]

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)
    model = SteeredModel(bound=[])
    graph = create_agent(model, tools=[slow_build, mcp_create_issue, mcp_add_label, setup.tool_search_tool], middleware=middleware, state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    config = {"configurable": {"thread_id": "thread"}}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Build it, then file an issue", id="user-1")]}, config, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await inputs.submit("steer", steer_text, "steer")
        release.set()
        result = await asyncio.wait_for(run, 10)
    finally:
        release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()
    return graph, config, model, result, created


@pytest.mark.asyncio
async def test_steer_keeps_tools_promoted_earlier_in_the_run():
    graph, config, model, result, created = await _run_with_steer("Mention the failing step in the issue")

    # search -> build -> (steer delivered) -> issue -> final answer
    assert len(model.bound) == 4
    assert "mcp_create_issue" not in model.bound[0]
    assert all("mcp_create_issue" in names for names in model.bound[1:])
    assert created == ["Build failure"]
    issue = next(m for m in result["messages"] if isinstance(m, ToolMessage) and m.name == "mcp_create_issue")
    assert issue.status != "error"
    assert result["promoted"]["turn_id"] == "user-1"
    assert result["promoted"]["names"] == ["mcp_create_issue"]

    # The next Run's own opening message still starts a new promotion scope.
    await graph.ainvoke({"messages": [HumanMessage(content="Now just say hello", id="user-2")]}, config, context={})
    assert "mcp_create_issue" not in model.bound[-1]


@pytest.mark.asyncio
async def test_steer_routing_adds_to_tools_promoted_earlier_in_the_run():
    _, _, model, result, created = await _run_with_steer("Also add the bug label", routing_index={"mcp_add_label": {"priority": 1, "keywords": ["label"]}})

    assert "mcp_add_label" not in model.bound[1]
    assert {"mcp_create_issue", "mcp_add_label"} <= model.bound[2]
    assert created == ["Build failure"]
    assert result["promoted"]["turn_id"] == "user-1"
    assert sorted(result["promoted"]["names"]) == ["mcp_add_label", "mcp_create_issue"]
