"""A rejected gated call must not let its ungated siblings escape suppression.

``tests/test_hitl_middleware_order.py`` pins the chain *positions*. This file
pins the behaviour those positions exist for, by running the assembled chain's
real ``after_model`` hooks in LangChain's real dispatch order (reverse of the
list) and then asking LangChain's own ``model_to_tools`` router what it would
execute.

The failure being guarded: every AI-only guard bails on "last message is not an
``AIMessage``", and a ``reject``/``respond`` decision appends a synthetic
``ToolMessage``. With approval dispatching first, a safety- or length-terminated
response holding a gated ``bash_tool`` plus an ungated ``write_file`` would have
its suppression skipped, while the router — which searches *backward* for the AI
message — still dispatched ``write_file``. Rejecting one call would execute the
other, against the provider-termination rule that suppresses the whole batch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, TypedDict

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import InterruptOnConfig, ToolConfig

GATED = "bash_tool"
UNGATED = "write_file"


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _chain():
    return build_middlewares(
        config={"configurable": {"thread_id": "t-1"}},
        model_name="gpt-4o",
        app_config=AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            tools=[
                ToolConfig(
                    name=GATED,
                    group="sandbox",
                    use="deerflow.sandbox.tools:bash_tool",
                    interrupt_on=InterruptOnConfig(allowed_decisions=["approve", "reject"]),
                ),
                ToolConfig(name=UNGATED, group="sandbox", use="deerflow.sandbox.tools:write_file"),
            ],
        ),
    )


def _dispatch_order(chain):
    """The middlewares with an ``after_model`` hook, in dispatch order.

    LangChain builds ``middleware_w_after_model`` from the list and wires the
    model node to its *last* entry, walking backwards — so the list is
    dispatched in reverse. Reproduced here rather than asserted on indices so a
    change to either end of the chain shows up as a behaviour failure.
    """
    hooked = [m for m in chain if type(m).after_model is not AgentMiddleware.after_model or type(m).aafter_model is not AgentMiddleware.aafter_model]
    return list(reversed(hooked))


def _terminated_batch():
    """One AI message the provider safety-terminated, holding both calls."""
    return AIMessage(
        content="",
        id="ai-1",
        tool_calls=[
            {"name": GATED, "args": {"command": "rm -rf /"}, "id": "call-gated"},
            {"name": UNGATED, "args": {"path": "/tmp/x", "content": "y"}, "id": "call-ungated"},
        ],
        response_metadata={"finish_reason": "content_filter"},
    )


def _pending_calls(messages):
    """What LangChain's model-to-tools router would dispatch for *messages*.

    Uses the real edge function, so this reflects its backward search for the AI
    message rather than a local re-implementation of it.
    """
    from langchain.agents.factory import _make_model_to_tools_edge

    edge = _make_model_to_tools_edge(model_destination="model", structured_output_tools={}, end_destination=END)
    result = edge({"messages": messages})
    if isinstance(result, str):
        return []
    return [call["name"] for send in result for call in send.arg]


def _run_the_chain(*, decisions):
    """Park on the gated call, answer it, and return the resulting messages.

    Every ``after_model`` hook in the assembled chain runs as one graph node, in
    dispatch order, under a real checkpointer — so the interrupt parks and the
    resume replays exactly as in production.
    """
    middlewares = _dispatch_order(_chain())

    def node(state, runtime):
        messages = list(state["messages"])
        for middleware in middlewares:
            update = middleware.after_model({**state, "messages": messages}, runtime)
            if not update:
                continue
            # add_messages semantics: same id replaces, new id appends.
            for message in update.get("messages") or ():
                replaced = False
                for index, existing in enumerate(messages):
                    if getattr(existing, "id", None) is not None and getattr(existing, "id", None) == getattr(message, "id", None):
                        messages[index] = message
                        replaced = True
                        break
                if not replaced:
                    messages.append(message)
        return {"messages": messages}

    graph = StateGraph(_State, context_schema=dict)
    graph.add_node("node", node)
    graph.add_edge(START, "node")
    graph.add_edge("node", END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "t-suppress"}}
    state = {"messages": [HumanMessage(content="do it", id="h-1"), _terminated_batch()]}
    context = {"thread_id": "t-suppress", "run_id": "r-1"}

    for _ in compiled.stream(state, config, context=context):
        pass
    for _ in compiled.stream(Command(resume={"decisions": decisions}), config, context=context):
        pass

    return compiled.get_state(config).values["messages"]


@pytest.fixture(autouse=True)
def _safety_detects_the_termination(monkeypatch):
    """Force the safety detector to match, independent of its shipped config.

    The point under test is the ordering, not which ``finish_reason`` strings a
    given deployment recognizes.
    """
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyTermination

    monkeypatch.setattr(
        SafetyFinishReasonMiddleware,
        "_detect",
        lambda self, message: SafetyTermination(detector="test", reason_field="finish_reason", reason_value="content_filter", extras={}),
    )


class TestARejectedCallCannotFreeItsSiblings:
    def test_the_ungated_sibling_is_not_dispatched_after_a_rejection(self):
        """The reported failure: reject ``bash``, and ``write_file`` still ran."""
        messages = _run_the_chain(decisions=[{"type": "reject"}])

        assert UNGATED not in _pending_calls(messages)

    def test_nothing_at_all_is_dispatched_after_a_rejection(self):
        """Provider termination suppresses the batch, not just the gated call."""
        messages = _run_the_chain(decisions=[{"type": "reject"}])

        assert _pending_calls(messages) == []

    def test_the_suppression_notice_survives_the_rejection(self):
        """The guard's rewrite must not be overwritten by the approval update."""
        messages = _run_the_chain(decisions=[{"type": "reject"}])

        terminated = next(msg for msg in messages if getattr(msg, "id", None) == "ai-1")
        assert terminated.tool_calls == []
        assert "safety_termination" in (terminated.additional_kwargs or {})


class TestSuppressionPreemptsTheReviewEntirely:
    """With the guards dispatching first, there is nothing left to review.

    This is the ordering's second benefit: a human is never asked about calls
    that a guard has already cancelled.
    """

    def test_a_suppressed_batch_never_reaches_the_human(self):
        middlewares = _dispatch_order(_chain())
        state = {"messages": [HumanMessage(content="do it", id="h-1"), _terminated_batch()]}
        runtime = SimpleNamespace(context={"thread_id": "t-1", "run_id": "r-1"})

        messages = list(state["messages"])
        asked = False
        for middleware in middlewares:
            if isinstance(middleware, SafetyFinishReasonMiddleware):
                update = middleware.after_model({"messages": messages}, runtime)
                messages = [update["messages"][0] if getattr(m, "id", None) == "ai-1" else m for m in messages]
                continue
            if type(middleware).__name__ == "DeerFlowHumanInTheLoopMiddleware":
                # Reached with tool_calls already cleared, so the approval hook
                # returns before ``interrupt()`` — no park, nothing to answer.
                asked = middleware.after_model({"messages": messages}, runtime) is not None

        assert asked is False
