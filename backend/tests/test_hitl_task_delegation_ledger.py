"""An approval-gated ``task`` call reaches a terminal entry in the delegation ledger.

With ``task`` in ``hitl_approval.tools`` the dispatch and its result belong to
two Runs: the paused Run issues the call and records it ``in_progress``, and the
resume Run executes it. The resume Run opens with no HumanMessage, so its
capture window starts after the pre-existing messages and does not contain the
dispatching AIMessage. Its result must still settle that entry, or the ledger
reports the delegation as running forever and compaction loses its result.
A rejected or denied call never executes and must settle as cancelled.
"""

from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.approvals.middleware import ToolApprovalMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.hitl_approval_config import HitlApprovalConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.subagents.status_contract import make_subagent_additional_kwargs


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _dispatch(job: int, call_id: str = "call_0") -> AIMessage:
    args = {"description": f"job {job}", "prompt": f"do job {job}", "subagent_type": "general-purpose"}
    return AIMessage(content="", id=f"ai-{job}", tool_calls=[{"name": "task", "id": call_id, "args": args}])


def _build_graph(responses: list[AIMessage], executed: list[str]):
    @tool("task")
    def task(description: str, prompt: str, subagent_type: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        """Delegate one job."""
        executed.append(description)
        return ToolMessage(
            f"Task Succeeded. Result: result of {description}",
            tool_call_id=tool_call_id,
            name="task",
            additional_kwargs=make_subagent_additional_kwargs("completed", result=f"result of {description}"),
        )

    # Production order: approval gates the tool call before execution, so the
    # ledger has already captured the dispatch by the time the interrupt lands.
    policy = HitlApprovalConfig(enabled=True, tools=["task"])
    app_config = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy)
    return create_agent(
        model=ScriptedModel(messages=iter(responses)),
        tools=[task],
        middleware=[ToolApprovalMiddleware(policy, app_config=app_config), DurableContextMiddleware()],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )


def _ledger(state) -> list[tuple]:
    return [(entry.get("run_id"), entry["id"], entry.get("dispatch_message_id"), entry["status"], entry.get("result_brief")) for entry in state["delegations"]]


def _pause(graph, config) -> dict:
    opening = HumanMessage("delegate job 1", id="human-1", additional_kwargs={"run_id": "run-A"})
    out = graph.invoke({"messages": [opening]}, config, context={"run_id": "run-A", "thread_id": "thread-1"})
    assert "__interrupt__" in out
    assert _ledger(out) == [("run-A", "call_0", "ai-1", "in_progress", None)]
    return out


def _resume(graph, config, paused, option_id: str, **extra) -> dict:
    action = paused["__interrupt__"][0].value["actions"][0]
    response = {"option_id": option_id, "tool_call_id": action["tool_call_id"], "request_id": action["request_id"], **extra}
    # The worker hands the resume Run the ids of the messages that predate it.
    pre_existing = frozenset(message.id for message in graph.get_state(config).values["messages"])
    context = {"run_id": "run-B", "thread_id": "thread-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: pre_existing}
    return graph.invoke(Command(resume={"responses": [response]}), config, context=context)


def test_approved_task_settles_the_paused_runs_delegation():
    executed: list[str] = []
    graph = _build_graph([_dispatch(1), AIMessage(content="final", id="ai-final")], executed)
    config = {"configurable": {"thread_id": "thread-1"}}

    state = _resume(graph, config, _pause(graph, config), "approve")

    assert executed == ["job 1"]
    # The result settles the entry the paused Run recorded; it is not re-tagged
    # as a delegation of the resume Run.
    assert _ledger(state) == [("run-A", "call_0", "ai-1", "completed", "result of job 1")]


def test_rejected_task_settles_as_cancelled():
    executed: list[str] = []
    graph = _build_graph([_dispatch(1), AIMessage(content="final", id="ai-final")], executed)
    config = {"configurable": {"thread_id": "thread-1"}}

    state = _resume(graph, config, _pause(graph, config), "reject", value="not now")

    assert executed == []
    [(run_id, call_id, dispatch_id, status, _)] = _ledger(state)
    assert (run_id, call_id, dispatch_id, status) == ("run-A", "call_0", "ai-1", "cancelled")
    [rejection] = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert "not now" in rejection.content


@pytest.mark.parametrize("context", [{"is_subagent": True}, {"non_interactive": True}], ids=["subagent", "non_interactive"])
def test_denied_task_settles_as_cancelled_in_the_same_run(context):
    executed: list[str] = []
    graph = _build_graph([_dispatch(1), AIMessage(content="final", id="ai-final")], executed)
    config = {"configurable": {"thread_id": "thread-1"}}
    opening = HumanMessage("delegate job 1", id="human-1", additional_kwargs={"run_id": "run-A"})

    state = graph.invoke({"messages": [opening]}, config, context={"run_id": "run-A", "thread_id": "thread-1", **context})

    assert "__interrupt__" not in state
    assert executed == []
    assert [(entry["id"], entry["status"]) for entry in state["delegations"]] == [("call_0", "cancelled")]


def test_resumed_result_leaves_other_dispatches_reusing_the_call_id_alone():
    """Only the response the resume Run answered is settled, even when an earlier one reused its id."""
    executed: list[str] = []
    graph = _build_graph([_dispatch(1), _dispatch(2), AIMessage(content="final", id="ai-final")], executed)
    config = {"configurable": {"thread_id": "thread-1"}}

    first = _resume(graph, config, _pause(graph, config), "approve")
    assert "__interrupt__" in first
    assert _ledger(first) == [
        ("run-A", "call_0", "ai-1", "completed", "result of job 1"),
        ("run-B", "call_0", "ai-2", "in_progress", None),
    ]

    action = first["__interrupt__"][0].value["actions"][0]
    response = {"option_id": "approve", "tool_call_id": action["tool_call_id"], "request_id": action["request_id"]}
    pre_existing = frozenset(message.id for message in graph.get_state(config).values["messages"])
    context = {"run_id": "run-C", "thread_id": "thread-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: pre_existing}
    state = graph.invoke(Command(resume={"responses": [response]}), config, context=context)

    assert executed == ["job 1", "job 2"]
    assert _ledger(state) == [
        ("run-A", "call_0", "ai-1", "completed", "result of job 1"),
        ("run-B", "call_0", "ai-2", "completed", "result of job 2"),
    ]
