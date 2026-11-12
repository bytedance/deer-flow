"""Delegations stay distinct when a provider reuses a tool-call id in a later response.

Tool-call ids are unique per response, not per conversation: some providers
number every response's calls from ``call_0``. Each ``task`` call is still its
own delegation, for the per-run delegation cap and for the durable ledger.
"""

import asyncio
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool

from deerflow.agents.middlewares.delegation_ledger import extract_delegations
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.thread_state import ThreadState, merge_delegations
from deerflow.runtime.runs.input_control import RunInputControl
from deerflow.runtime.runs.inputs import RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.subagents.status_contract import make_subagent_additional_kwargs


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _task_call(job: int, call_id: str = "call_0") -> dict:
    return {"name": "task", "id": call_id, "args": {"description": f"job {job}", "prompt": f"do job {job}", "subagent_type": "general-purpose"}}


def _dispatch(job: int, call_id: str = "call_0") -> AIMessage:
    return AIMessage(content="", id=f"ai-{job}", tool_calls=[_task_call(job, call_id)])


def _result(job: int, call_id: str = "call_0") -> ToolMessage:
    return ToolMessage(
        f"done job {job}",
        id=f"result-{job}",
        tool_call_id=call_id,
        name="task",
        additional_kwargs=make_subagent_additional_kwargs("completed", result=f"result of job {job}"),
    )


def _ledger_view(delegations: list[dict]) -> list[tuple]:
    return [(entry["id"], entry["description"], entry["status"], entry.get("result_brief")) for entry in delegations]


def test_per_run_delegation_cap_holds_when_every_response_reuses_call_0():
    executed: list[str] = []

    @tool("task")
    def task(description: str, prompt: str, subagent_type: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        """Delegate one job."""
        executed.append(description)
        job = int(description.split()[-1])
        return ToolMessage(
            f"done {description}",
            tool_call_id=tool_call_id,
            name="task",
            additional_kwargs=make_subagent_additional_kwargs("completed", result=f"result of job {job}"),
        )

    model = ScriptedModel(messages=iter([_dispatch(1), _dispatch(2), _dispatch(3), _dispatch(4), AIMessage(content="final", id="ai-final")]))
    graph = create_agent(
        model=model,
        tools=[task],
        middleware=[DurableContextMiddleware(), SubagentLimitMiddleware(max_concurrent=1, max_total=2)],
        state_schema=ThreadState,
    )

    state = graph.invoke({"messages": [HumanMessage("go", id="human-1")]}, context={"run_id": "run-1", "thread_id": "thread-1"})

    assert executed == ["job 1", "job 2"]
    assert _ledger_view(state["delegations"]) == [
        ("call_0", "job 1", "completed", "result of job 1"),
        ("call_0", "job 2", "completed", "result of job 2"),
    ]
    assert [entry["dispatch_message_id"] for entry in state["delegations"]] == ["ai-1", "ai-2"]


def test_a_reused_call_id_in_flight_never_takes_the_earlier_result():
    messages = [HumanMessage("go", id="human-1"), _dispatch(1), _result(1), _dispatch(2)]

    assert _ledger_view(extract_delegations(messages)) == [
        ("call_0", "job 1", "completed", "result of job 1"),
        ("call_0", "job 2", "in_progress", None),
    ]


def test_an_unanswered_call_keeps_its_own_entry_when_a_later_response_reuses_its_id():
    messages = [HumanMessage("go", id="human-1"), _dispatch(1), _dispatch(2), _result(2)]

    assert _ledger_view(extract_delegations(messages)) == [
        ("call_0", "job 1", "in_progress", None),
        ("call_0", "job 2", "completed", "result of job 2"),
    ]


def test_a_dispatch_scoped_entry_upgrades_a_ledger_entry_written_before_the_field_existed():
    legacy = {"id": "call_0", "run_id": "run-1", "description": "job 1", "subagent_type": "general-purpose", "status": "in_progress", "created_at": "2026-11-08T00:00:00Z"}
    first, second = ({**entry, "run_id": "run-1"} for entry in extract_delegations([_dispatch(1), _result(1), _dispatch(2)]))

    upgraded = merge_delegations([legacy], [first])
    assert _ledger_view(upgraded) == [("call_0", "job 1", "completed", "result of job 1")]
    assert upgraded[0]["created_at"] == legacy["created_at"]

    merged = merge_delegations(upgraded, [second])
    assert _ledger_view(merged) == [
        ("call_0", "job 1", "completed", "result of job 1"),
        ("call_0", "job 2", "in_progress", None),
    ]


def test_cap_counts_dispatches_not_call_ids():
    ledger = [{**entry, "run_id": "run-1"} for entry in extract_delegations([_dispatch(1), _result(1), _dispatch(2), _result(2)])]
    runtime = SimpleNamespace(context={"run_id": "run-1"})
    next_call = _dispatch(3)

    blocked = SubagentLimitMiddleware(max_concurrent=1, max_total=2).after_model({"messages": [next_call], "delegations": ledger}, runtime)

    assert blocked is not None
    assert blocked["messages"][0].tool_calls == []


@pytest.mark.asyncio
async def test_steered_result_records_the_same_delegation_the_graph_captured():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("update", "Handle this first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    release = asyncio.Event()
    history = [HumanMessage("go", id="human-1"), _dispatch(1), _result(1), _dispatch(2)]

    async def handler(request):
        await release.wait()
        return _result(2)

    try:
        pending = await control.wait_tool(SimpleNamespace(tool_call=_task_call(2), state={"messages": history}), handler)
        assert pending.additional_kwargs["subagent_pending"]
        release.set()
        await asyncio.gather(*control.tasks)
    finally:
        release.set()
        await control.close()

    captured = [{**entry, "run_id": "run"} for entry in extract_delegations([*history, pending])]
    merged = merge_delegations(merge_delegations([], captured), control.delegations)
    assert _ledger_view(merged) == [
        ("call_0", "job 1", "completed", "result of job 1"),
        ("call_0", "job 2", "completed", "result of job 2"),
    ]
    assert [entry.get("dispatch_message_id") for entry in control.delegations] == ["ai-2"]


@pytest.mark.asyncio
async def test_a_steered_call_keeps_its_dispatch_when_a_later_response_reuses_its_id_in_flight():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("update", "Handle this first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    releases = {2: asyncio.Event(), 3: asyncio.Event()}
    first_history = [HumanMessage("go", id="human-1"), _dispatch(1), _result(1), _dispatch(2)]

    def handler_for(job):
        async def handler(request):
            await releases[job].wait()
            return _result(job)

        return handler

    try:
        # job 2 is steer-paused and still running when the next response reuses call_0.
        pending = await control.wait_tool(SimpleNamespace(tool_call=_task_call(2), state={"messages": first_history}), handler_for(2))
        assert pending.additional_kwargs["subagent_pending"]
        second_history = [*first_history, pending, _dispatch(3)]
        second = asyncio.create_task(control.wait_tool(SimpleNamespace(tool_call=_task_call(3), state={"messages": second_history}), handler_for(3)))
        await asyncio.sleep(0)
        releases[3].set()
        await second
        releases[2].set()
        await asyncio.gather(*control.tasks)
    finally:
        for release in releases.values():
            release.set()
        await control.close()

    by_dispatch = {entry["dispatch_message_id"]: (entry["description"], entry["result_brief"]) for entry in control.delegations}
    assert by_dispatch["ai-2"] == ("job 2", "result of job 2")
    assert by_dispatch.get("ai-3", ("job 3", "result of job 3")) == ("job 3", "result of job 3")


def test_a_new_turn_settles_a_reply_checkpointed_before_its_capture():
    # Run 1's worker crashed after the tools checkpoint stored job 1's reply but
    # before the next capture recorded it, so the entry is still in_progress.
    run_1 = [HumanMessage("go", id="human-1", additional_kwargs={"run_id": "run-1"}), _dispatch(1), _result(1)]
    ledger = merge_delegations([], [{**entry, "run_id": "run-1"} for entry in extract_delegations(run_1[:2])])
    messages = [*run_1, HumanMessage("next", id="human-2", additional_kwargs={"run_id": "run-2"})]

    update = DurableContextMiddleware().before_model({"messages": messages, "delegations": ledger}, SimpleNamespace(context={"run_id": "run-2"}))

    merged = merge_delegations(ledger, update["delegations"] if update else [])
    assert _ledger_view(merged) == [("call_0", "job 1", "completed", "result of job 1")]
    assert [(entry["run_id"], entry["dispatch_message_id"]) for entry in merged] == [("run-1", "ai-1")]


def test_a_new_turn_cancels_the_dangling_dispatch_of_a_reused_call_id():
    # Run 1 dispatched call_0 twice and stopped while the second subagent ran.
    run_1 = [HumanMessage("go", id="human-1", additional_kwargs={"run_id": "run-1"}), _dispatch(1), _result(1), _dispatch(2)]
    ledger = merge_delegations([], [{**entry, "run_id": "run-1"} for entry in extract_delegations(run_1)])
    messages = [*run_1, HumanMessage("next", id="human-2", additional_kwargs={"run_id": "run-2"})]

    update = DurableContextMiddleware().before_model({"messages": messages, "delegations": ledger}, SimpleNamespace(context={"run_id": "run-2"}))

    # job 1's reply answers its own response only; job 2 is closed, not left in_progress.
    merged = merge_delegations(ledger, update["delegations"] if update else [])
    assert _ledger_view(merged) == [
        ("call_0", "job 1", "completed", "result of job 1"),
        ("call_0", "job 2", "cancelled", None),
    ]


def test_runs_reusing_a_call_id_keep_separate_delegations():
    first = {"id": "call_0", "run_id": "run-1", "dispatch_message_id": "ai-1", "description": "job 1", "subagent_type": "general-purpose", "status": "completed", "created_at": "2026-11-08T00:00:00Z"}
    second = {**first, "run_id": "run-2", "dispatch_message_id": "ai-2", "description": "job 2", "status": "in_progress"}

    merged = merge_delegations([first], [second])

    assert [(entry["run_id"], entry["description"], entry["status"]) for entry in merged] == [("run-1", "job 1", "completed"), ("run-2", "job 2", "in_progress")]
