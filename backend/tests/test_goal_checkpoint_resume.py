"""Checkpoint replay replaces messages, not the owner's current goal."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.types import Command, Overwrite, interrupt

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.goal import build_goal_outcome, build_goal_state, write_thread_goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus

pytestmark = pytest.mark.asyncio


async def _replay(monkeypatch, *, mode, current_kind, explicit_goal=False, select_head=False, rollback=False, late_goal_update=None):
    saver = InMemorySaver()
    thread_id = "goal-checkpoint-resume"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    schema = get_thread_state_schema(mode)
    accessor = CheckpointStateAccessor.bind(build_state_mutation_graph("seed", mode, schema), saver, mode=mode)
    previous_goal = build_goal_state("Finish the previous objective", now="2026-10-01T00:00:00Z")
    selected_outcome = None
    if current_kind == "previous-achievement":
        selected_outcome = build_goal_outcome(previous_goal, {"satisfied": True, "blocker": "none", "reason": "The earlier answer met its goal"}, reply_message_id="earlier-answer")
    await accessor.aupdate(
        config,
        {
            "messages": [HumanMessage(id="earlier", content="Earlier request"), AIMessage(id="earlier-answer", content="Earlier answer")],
            "goal": previous_goal if selected_outcome is None else Overwrite(None),
            "goal_outcome": selected_outcome,
        },
        as_node="seed",
    )
    selected = await accessor.aget(config)
    current_goal = copy.deepcopy(previous_goal)
    current_goal.update(continuation_count=3, no_progress_count=1, max_continuations=5)
    if current_kind == "changed":
        current_goal.update(objective="Finish the revised objective", created_at="2026-10-02T00:00:00Z")
    if current_kind == "recovered-scheduled":
        current_goal["created_at"] = "2026-10-02T00:00:00.123456+00:00"
    outcome = None
    if current_kind in ("cleared", "achieved"):
        current_goal = None
    if current_kind == "achieved":
        outcome = build_goal_outcome(previous_goal, {"satisfied": True, "blocker": "none", "reason": "Previous answer met the goal"}, reply_message_id="superseded")
    await accessor.aupdate(
        config,
        {
            "messages": [HumanMessage(id="redo", content="Regenerate this answer"), AIMessage(id="superseded", content="Answer to replace")],
            "goal": Overwrite(current_goal),
            "goal_outcome": outcome,
        },
        as_node="seed",
    )
    head = await accessor.aget(config)
    prepared_config = {"configurable": {**config["configurable"], "checkpoint_id": (head if select_head else selected).config["configurable"]["checkpoint_id"]}}
    graph_input = {"messages": [HumanMessage(id="redo", content="Regenerate this answer")]}
    if explicit_goal:
        current_goal = build_goal_state("The explicit new request goal", now="2026-10-03T00:00:00Z")
        graph_input["goal"] = current_goal
    captured_states = []
    factory_ready = asyncio.Event()
    manager = RunManager()
    record = await manager.create(thread_id)
    if current_kind == "recovered-scheduled":
        monkeypatch.setattr(manager, "scheduled_goal_source", AsyncMock(return_value={"run_id": "terminal-scheduled-run"}))

    async def answer(state):
        captured_states.append(copy.deepcopy(state))
        if rollback:
            record.abort_action = "rollback"
            record.abort_event.set()
        return {"messages": [AIMessage(id="replacement", content="Replacement answer")]}

    def factory(*, config):
        del config
        builder = StateGraph(schema)
        builder.add_node("answer", answer)
        builder.set_entry_point("answer")
        builder.set_finish_point("answer")
        factory_ready.set()
        return builder.compile(checkpointer=saver)

    # These tests exercise state selection and the real worker/graph, without
    # asking a provider to judge a deterministic checkpoint regression.
    monkeypatch.setattr(worker, "_prepare_goal_continuation_input", AsyncMock(return_value=None))
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())

    async def execute():
        await worker.run_agent(
            bridge,
            manager,
            record,
            ctx=worker.RunContext(checkpointer=saver, checkpoint_channel_mode=mode),
            agent_factory=factory,
            graph_input=graph_input,
            config=prepared_config,
            stream_modes=["values"],
        )

    if late_goal_update:
        # A user clears the goal after the replay selector was prepared but
        # before the worker acquires the existing checkpoint-write lock.
        async with worker._checkpoint_thread_lock(thread_id):
            task = asyncio.create_task(execute())
            try:
                await asyncio.wait_for(factory_ready.wait(), timeout=5)
                if late_goal_update == "change":
                    current_goal = {**current_goal, "objective": "The latest user revision", "created_at": "2026-10-04T00:00:00Z"}
                else:
                    current_goal = None
                await write_thread_goal(saver, thread_id, current_goal)
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
        await asyncio.wait_for(task, timeout=5)
    else:
        await execute()
    final = await accessor.aget(config)
    return record, captured_states, final, current_goal, head, outcome


@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("current_kind", ["cleared", "achieved", "active", "changed", "previous-achievement"])
async def test_checkpoint_replay_preserves_current_goal_and_budget(monkeypatch, mode, current_kind):
    record, states, final, current_goal, _head, _outcome = await _replay(monkeypatch, mode=mode, current_kind=current_kind)

    assert record.status == RunStatus.success
    assert len(states) == 1
    assert states[0].get("goal") == current_goal
    assert final.values.get("goal") == current_goal
    assert states[0].get("goal_outcome") is None
    assert final.values.get("goal_outcome") is None
    assert [message.id for message in final.values["messages"]] == ["earlier", "earlier-answer", "redo", "replacement"]


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_checkpoint_replay_honors_an_explicit_new_goal(monkeypatch, mode):
    record, states, final, explicit_goal, _head, _outcome = await _replay(monkeypatch, mode=mode, current_kind="active", explicit_goal=True)

    assert record.status == RunStatus.success
    assert states[0]["goal"] == explicit_goal
    assert final.values["goal"] == explicit_goal


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_checkpoint_replay_reads_goal_at_execution_not_preparation(monkeypatch, mode):
    record, states, final, _goal, _head, _outcome = await _replay(monkeypatch, mode=mode, current_kind="active", late_goal_update="clear")

    assert record.status == RunStatus.success
    assert states[0].get("goal") is None
    assert final.values.get("goal") is None


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_checkpoint_replay_uses_a_goal_edited_after_preparation(monkeypatch, mode):
    record, states, final, current_goal, _head, _outcome = await _replay(monkeypatch, mode=mode, current_kind="active", late_goal_update="change")

    assert record.status == RunStatus.success
    assert states[0]["goal"] == current_goal
    assert final.values["goal"] == current_goal


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_current_head_resume_retains_existing_goal_outcome(monkeypatch, mode):
    record, states, final, _goal, _head, outcome = await _replay(monkeypatch, mode=mode, current_kind="achieved", select_head=True)

    assert record.status == RunStatus.success
    assert states[0]["goal_outcome"] == outcome
    assert final.values["goal_outcome"] == outcome


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_cancelled_checkpoint_replay_restores_pre_run_goal_and_outcome(monkeypatch, mode):
    record, _states, final, _goal, head, _outcome = await _replay(monkeypatch, mode=mode, current_kind="achieved", rollback=True)

    assert record.status == RunStatus.error
    assert final.values.get("goal") == head.values.get("goal")
    assert final.values.get("goal_outcome") == head.values.get("goal_outcome")
    assert [message.id for message in final.values["messages"]] == [message.id for message in head.values["messages"]]


@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_checkpoint_replay_does_not_restore_a_cleaned_scheduled_goal(monkeypatch, mode):
    record, states, final, _goal, _head, _outcome = await _replay(monkeypatch, mode=mode, current_kind="recovered-scheduled")

    assert record.status == RunStatus.success
    assert states[0].get("goal") is None
    assert final.values.get("goal") is None


async def test_historical_full_checkpoint_command_keeps_interrupt_resume_protocol(monkeypatch):
    saver = InMemorySaver()
    thread_id = "goal-interrupt-command"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    original_goal = build_goal_state("Finish after approval", now="2026-10-01T00:00:00Z")
    resumed_answers = []

    async def answer(_state):
        approved = interrupt("Please approve this step")
        resumed_answers.append(approved)
        return {"messages": [AIMessage(id="approved-answer", content=f"Approval: {approved}")]}

    builder = StateGraph(get_thread_state_schema("full"))
    builder.add_node("answer", answer)
    builder.set_entry_point("answer")
    builder.set_finish_point("answer")
    graph = builder.compile(checkpointer=saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="full")
    await graph.ainvoke({"messages": [HumanMessage(id="approval-request", content="Do the approved step")], "goal": original_goal}, config)
    paused = await accessor.aget(config)
    assert paused.next == ("answer",)
    assert paused.tasks[0].interrupts

    # A legitimate goal write advances the head while the graph is paused.
    # Resume still targets the addressable checkpoint with its interrupt.
    await write_thread_goal(saver, thread_id, {**original_goal, "continuation_count": 2})
    head = await accessor.aget(config)
    assert head.config["configurable"]["checkpoint_id"] != paused.config["configurable"]["checkpoint_id"]
    stream = Mock(wraps=graph.astream)
    monkeypatch.setattr(graph, "astream", stream)
    monkeypatch.setattr(worker, "_prepare_goal_continuation_input", AsyncMock(return_value=None))
    manager = RunManager()
    record = await manager.create(thread_id)
    command = Command(resume="approved")
    await worker.run_agent(
        SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock()),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=saver, checkpoint_channel_mode="full"),
        agent_factory=lambda config: graph,
        graph_input=command,
        config=paused.config,
        stream_modes=["values"],
    )

    assert record.status == RunStatus.success
    assert stream.call_args.args[0] is command
    assert resumed_answers == ["approved"]
    final = await accessor.aget(config)
    assert final.next == ()
    assert final.values["messages"][-1].content == "Approval: approved"
