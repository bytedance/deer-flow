"""Phase 2 introspection against real LangGraph execution, without providers."""

import asyncio
import json

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.tools.builtins.inspect_run_status_tool import build_inspect_run_status_tool
from deerflow.tools.types import Runtime


class _Model(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _status_call(call_id="status"):
    return AIMessage(content="", tool_calls=[{"name": "inspect_run_status", "args": {}, "id": call_id}])


def _graph(messages, *, mode="full", **kwargs):
    return create_agent(
        model=_Model(messages=iter(messages)),
        tools=[build_inspect_run_status_tool(context_window=None)],
        state_schema=get_thread_state_schema(mode),
        **kwargs,
    )


def _invoke(graph, value, config, execution):
    if execution == "async":
        return asyncio.run(graph.ainvoke(value, config))
    return graph.invoke(value, config)


def _snapshots(result):
    return [json.loads(message.content)["recursion"] for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "inspect_run_status"]


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("execution", ["sync", "async"])
def test_recursion_tracks_tool_supersteps_instead_of_message_counts(mode, execution):
    first = AIMessage(content="", tool_calls=[{"name": "inspect_run_status", "args": {}, "id": call_id} for call_id in ("first", "parallel")])
    graph = _graph([first, _status_call("second"), AIMessage(content="done")], mode=mode)

    result = _invoke(graph, {"messages": [("user", "check twice")]}, {"recursion_limit": 10}, execution)

    assert _snapshots(result) == [
        {"step": 2, "limit": 10, "remaining": 8},
        {"step": 2, "limit": 10, "remaining": 8},
        {"step": 4, "limit": 10, "remaining": 6},
    ]


def test_recursion_counts_middleware_nodes():
    class Hooks(AgentMiddleware):
        def before_model(self, state, runtime):
            return None

        def after_model(self, state, runtime):
            return None

    graph = _graph([_status_call(), AIMessage(content="done")], middleware=[Hooks()])

    result = graph.invoke({"messages": [("user", "check")]}, {"recursion_limit": 10})

    assert _snapshots(result) == [{"step": 4, "limit": 10, "remaining": 6}]


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("execution", ["sync", "async"])
def test_new_turn_uses_fresh_budget_despite_cumulative_checkpoint_step(mode, execution):
    graph = _graph([_status_call("first"), AIMessage(content="done"), _status_call("second"), AIMessage(content="done")], mode=mode, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "recursion-turns"}, "recursion_limit": 10}
    first = _invoke(graph, {"messages": [("user", "first")]}, config, execution)
    second = _invoke(graph, {"messages": [("user", "second")]}, dict(config, recursion_limit=5), execution)

    assert _snapshots(first) == [{"step": 2, "limit": 10, "remaining": 8}]
    assert _snapshots(second)[-1] == {"step": 7, "limit": 5, "remaining": 3}


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("execution", ["sync", "async"])
def test_resume_uses_live_budget_not_limit_minus_checkpoint_step(mode, execution):
    graph = _graph([_status_call(), AIMessage(content="done")], mode=mode, checkpointer=InMemorySaver(), interrupt_before=["tools"])
    config = {"configurable": {"thread_id": "recursion-resume"}, "recursion_limit": 10}
    paused = _invoke(graph, {"messages": [("user", "check")]}, config, execution)
    assert _snapshots(paused) == []

    resumed = _invoke(graph, None, dict(config, recursion_limit=5), execution)

    # LangGraph grants a fresh invocation budget when resuming. Its native
    # RemainingSteps value can exceed the configured limit at the pending node.
    assert _snapshots(resumed) == [{"step": 2, "limit": 5, "remaining": 6}]


def test_read_only_status_does_not_bypass_recursion_exhaustion():
    graph = _graph([_status_call("first"), _status_call("second"), _status_call("third")])
    snapshots = []
    with pytest.raises(GraphRecursionError):
        for update in graph.stream({"messages": [("user", "keep checking")]}, {"recursion_limit": 4}, stream_mode="updates"):
            for state in update.values():
                snapshots.extend(_snapshots(state))

    assert snapshots == [{"step": 2, "limit": 4, "remaining": 2}, {"step": 4, "limit": 4, "remaining": 0}]


def test_default_budget_comes_from_langgraph_instead_of_a_hardcoded_limit():
    graph = _graph([_status_call(), AIMessage(content="done")])
    effective_limit = graph.config["recursion_limit"]

    result = graph.invoke({"messages": [("user", "check")]})

    assert _snapshots(result) == [{"step": 2, "limit": effective_limit, "remaining": effective_limit - 2}]


@pytest.mark.parametrize("execution", ["sync", "async"])
def test_nested_agent_reports_its_own_budget_without_changing_parent(execution):
    child = _graph([_status_call("child"), AIMessage(content="child done")])

    @tool
    def delegate_status() -> str:
        """Read the child graph's own status."""
        result = child.invoke({"messages": [("user", "child check")]}, {"recursion_limit": 8})
        return json.dumps(_snapshots(result))

    parent_model = _Model(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "delegate_status", "args": {}, "id": "delegate"}]),
                _status_call("parent"),
                AIMessage(content="parent done"),
            ]
        )
    )
    parent = create_agent(model=parent_model, tools=[delegate_status, build_inspect_run_status_tool(context_window=None)], state_schema=get_thread_state_schema("full"))

    result = _invoke(parent, {"messages": [("user", "delegate then check")]}, {"recursion_limit": 12}, execution)

    child_result = next(message for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "delegate_status")
    assert json.loads(child_result.content) == [{"step": 2, "limit": 8, "remaining": 6}]
    assert _snapshots(result) == [{"step": 4, "limit": 12, "remaining": 8}]


@pytest.mark.parametrize("config", [{}, {"recursion_limit": 10}, {"recursion_limit": 10, "metadata": {"langgraph_step": 2}, "configurable": {"recursion": {"remaining": 999}}}])
def test_outside_graph_recursion_is_unknown_instead_of_guessed(config):
    tool = build_inspect_run_status_tool(context_window=None)
    runtime = Runtime(state={}, context={}, config=config, store=None, stream_writer=lambda _: None, tool_call_id="status")

    snapshot = json.loads(tool.func(runtime=runtime))

    assert snapshot["recursion"] is None
