"""Exercise goal completion and artifact delivery through the real worker."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.paths import Paths
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.goal import build_goal_state, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tools.builtins.present_file_tool import present_file_tool

OUTPUT_PATH = "/mnt/user-data/outputs/report.md"


async def _run_goal_delivery(
    tmp_path,
    monkeypatch,
    *,
    produce=True,
    present_on_turn=None,
    verdicts=(True,),
    fail_receipt=False,
    during_evaluation=None,
    during_receipt=None,
    stop_reason=None,
    heartbeat_enabled=False,
    fail_terminal_status=None,
    completion_recovers=False,
    checkpoint_mode="full",
    after_terminal_completion=None,
):
    """Keep graphs, checkpoints, output scanning and delivery verification real.

    The graph writes a real file and calls the real present_files body. Its
    deterministic node emits the tool callbacks normally supplied by the agent;
    only the evaluator model response is fixed, without provider/network access.
    """
    checkpointer = InMemorySaver()
    failed_terminal_writes = []

    class RunStore(MemoryRunStore):
        async def update_status(self, run_id, status, **kwargs):
            if status == "success" and fail_terminal_status is not None:
                failed_terminal_writes.append(status)
                if fail_terminal_status == "raise":
                    raise RuntimeError("terminal run store unavailable")
                return False
            return await super().update_status(run_id, status, **kwargs)

        async def update_run_completion(self, run_id, *, status, **kwargs):
            if status == "success" and fail_terminal_status is not None and not completion_recovers:
                if fail_terminal_status == "raise":
                    raise RuntimeError("terminal run store unavailable")
                return False
            updated = await super().update_run_completion(run_id, status=status, **kwargs)
            if after_terminal_completion is not None and status == "success":
                await after_terminal_completion(self, record)
            return updated

    run_store = RunStore()
    manager = RunManager(store=run_store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled))
    record = await manager.create("goal-delivery-thread")
    thread_id = record.thread_id
    paths = Paths(base_dir=tmp_path)
    output_dir = paths.sandbox_outputs_dir(thread_id, user_id=get_effective_user_id())
    output_dir.mkdir(parents=True)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    monkeypatch.setattr(importlib.import_module("deerflow.tools.builtins.present_file_tool"), "get_paths", lambda: paths)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    turns = []
    model_calls = []
    goals_at_receipt = []

    class EventStore(MemoryRunEventStore):
        async def put_if_absent(self, **event):
            if event["event_type"] == "run.delivery":
                goals_at_receipt.append(await read_thread_goal(checkpointer, thread_id))
                if during_receipt is not None:
                    await during_receipt(checkpointer, manager, record)
                if fail_receipt:
                    raise RuntimeError("delivery receipt store unavailable")
            return await super().put_if_absent(**event)

    event_store = EventStore()
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())

    class EvaluatorModel:
        async def ainvoke(self, messages, config=None):
            satisfied = verdicts[min(len(model_calls), len(verdicts) - 1)]
            model_calls.append(satisfied)
            if during_evaluation is not None:
                await during_evaluation(checkpointer, manager, record)
            return AIMessage(
                content=json.dumps(
                    {
                        "satisfied": satisfied,
                        "blocker": "none" if satisfied else "goal_not_met_yet",
                        "reason": "Fixed evaluator response for the worker regression.",
                        "evidence_summary": "The assistant reports that the report is complete.",
                    }
                )
            )

    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: EvaluatorModel())

    async def agent_node(state, config):
        turn = len(turns) + 1
        turns.append(turn)
        if produce:
            (output_dir / "report.md").write_text("# Finished report\n", encoding="utf-8")
        context = config["configurable"]["__pregel_runtime"].context
        updates = {}
        messages = []
        if present_on_turn == turn:
            tool_id = f"present-{turn}"
            ai = AIMessage(content="", tool_calls=[{"id": tool_id, "name": "present_files", "args": {"filepaths": [OUTPUT_PATH]}}])
            runtime = SimpleNamespace(state={**state, "thread_data": {"outputs_path": str(output_dir)}}, context=context, config=config)
            command = present_file_tool.func(runtime=runtime, filepaths=[OUTPUT_PATH], tool_call_id=tool_id)
            journal = context["__run_journal"]
            journal._remember_current_run_tool_calls(ai, caller="lead_agent")
            journal.on_tool_end(command, run_id=uuid4())
            messages = [ai, *command.update["messages"]]
            updates["artifacts"] = command.update.get("artifacts", [])
        if stop_reason is not None:
            context["stop_reason"] = stop_reason
        updates["messages"] = [*messages, AIMessage(content="The report is complete and ready for delivery.")]
        return updates

    graph = StateGraph(get_thread_state_schema(checkpoint_mode))
    graph.add_node("report", agent_node)
    graph.add_edge(START, "report")
    graph.add_edge("report", END)
    compiled = graph.compile(checkpointer=checkpointer)
    accessor = CheckpointStateAccessor.bind(compiled, checkpointer, mode=checkpoint_mode)
    await accessor.aupdate(
        {"configurable": {"thread_id": thread_id}},
        {"messages": [HumanMessage(content="Create and present report.md.")], "title": "Report"},
        as_node="report",
    )
    goal = build_goal_state("Create and present report.md.", max_continuations=2)
    await write_thread_goal(checkpointer, thread_id, goal)

    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, event_store=event_store, checkpoint_channel_mode=checkpoint_mode),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Finish the report now.")]},
        config={"configurable": {"thread_id": thread_id}},
        stream_modes=["values"],
    )

    events = await event_store.list_events(thread_id, record.run_id)
    return SimpleNamespace(
        record=record,
        durable_run=await run_store.get(record.run_id),
        original_goal=goal,
        goal=await read_thread_goal(checkpointer, thread_id),
        model_calls=model_calls,
        turns=turns,
        delivery=[event["content"] for event in events if event["event_type"] == "run.delivery"],
        goals_at_receipt=goals_at_receipt,
        failed_terminal_writes=failed_terminal_writes,
        bridge=bridge,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", [None, "token_capped"])
async def test_delivery_failure_preserves_satisfied_goal_without_continuing(tmp_path, monkeypatch, stop_reason):
    result = await _run_goal_delivery(tmp_path, monkeypatch, stop_reason=stop_reason)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.error
    assert result.durable_run["status"] == "error"
    assert result.record.error == worker._DELIVERY_INCOMPLETE_ERROR
    assert result.delivery[0]["produced_paths"] == [OUTPUT_PATH]
    assert result.delivery[0]["satisfied"] is False
    assert result.goal is not None
    assert result.goal["objective"] == result.original_goal["objective"]
    assert result.goal["continuation_count"] == 0
    assert all(call.args[2].get("goal") is not None for call in result.bridge.publish.call_args_list if call.args[1] == "values" and "goal" in call.args[2])


@pytest.mark.asyncio
@pytest.mark.parametrize("produce,present_on_turn", [(True, 1), (False, None)])
async def test_successful_delivery_clears_satisfied_goal(tmp_path, monkeypatch, produce, present_on_turn):
    result = await _run_goal_delivery(tmp_path, monkeypatch, produce=produce, present_on_turn=present_on_turn)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.success
    assert result.durable_run["status"] == "success"
    assert result.goal is None
    assert len(result.goals_at_receipt) == 1
    assert result.goals_at_receipt[0] is not None
    assert result.goals_at_receipt[0]["objective"] == result.original_goal["objective"]
    assert len(result.delivery) == 1
    if produce:
        assert result.delivery[0]["satisfied"] is True
        assert result.delivery[0]["matched_paths"] == [OUTPUT_PATH]
    else:
        assert result.delivery[0] == {"presented": 0, "paths": [], "by_tool": {}}


@pytest.mark.asyncio
async def test_goal_completion_waits_for_durable_delivery_receipt(tmp_path, monkeypatch):
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, fail_receipt=True)

    assert result.record.status == RunStatus.error
    assert result.durable_run["status"] == "error"
    assert result.record.error == worker._DELIVERY_RECEIPT_FAILED_ERROR
    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.delivery == []
    assert result.goal is not None
    assert result.goal["objective"] == result.original_goal["objective"]


@pytest.mark.asyncio
async def test_unmet_goal_can_still_continue_and_deliver(tmp_path, monkeypatch):
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=2, verdicts=(False, True))

    assert result.model_calls == [False, True]
    assert result.turns == [1, 2]
    assert result.record.status == RunStatus.success
    assert result.durable_run["status"] == "success"
    assert result.delivery[0]["satisfied"] is True
    assert result.goal is None
    assert result.goals_at_receipt[0]["continuation_count"] == 1


@pytest.mark.asyncio
async def test_cancellation_during_evaluation_preserves_goal(tmp_path, monkeypatch):
    async def cancel(_checkpointer, manager, record):
        await manager.cancel(record.run_id)

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, during_evaluation=cancel)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.interrupted
    assert result.durable_run["status"] == "interrupted"
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_new_goal_during_delivery_receipt_is_not_cleared(tmp_path, monkeypatch):
    replacement = build_goal_state("Prepare the next report.")

    async def replace_goal(checkpointer, _manager, record):
        await write_thread_goal(checkpointer, record.thread_id, replacement)

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, during_receipt=replace_goal)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.success
    assert result.goal == replacement


@pytest.mark.asyncio
async def test_ownership_loss_during_delivery_receipt_preserves_goal(tmp_path, monkeypatch):
    async def lose_ownership(_checkpointer, manager, record):
        await manager._mark_ownership_lost(record, reason="Test lease takeover", require_active=False)

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, during_receipt=lose_ownership)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.ownership_lost is True
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_durable_cancellation_during_delivery_receipt_preserves_goal(tmp_path, monkeypatch):
    async def cancel(_checkpointer, manager, record):
        assert await manager._store.request_cancel(record.run_id, action="interrupt") == "interrupt"

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, heartbeat_enabled=True, during_receipt=cancel)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.interrupted
    assert result.durable_run["status"] == "interrupted"
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_changed_goal_evaluation_during_delivery_receipt_is_preserved(tmp_path, monkeypatch):
    changed_goals = []

    async def update_goal(checkpointer, _manager, record):
        goal = await read_thread_goal(checkpointer, record.thread_id)
        assert goal is not None
        changed = {
            **goal,
            "continuation_count": 1,
            "last_evaluation": {"satisfied": False, "blocker": "needs_user_input", "reason": "New evidence needs confirmation.", "evidence_summary": "Waiting for the user."},
        }
        changed_goals.append(changed)
        await write_thread_goal(checkpointer, record.thread_id, changed)

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, during_receipt=update_goal)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.success
    assert len(changed_goals) == 1
    assert result.goal == changed_goals[0]


@pytest.mark.asyncio
async def test_new_user_message_during_delivery_receipt_preserves_goal(tmp_path, monkeypatch):
    async def add_message(checkpointer, _manager, record):
        graph = build_state_mutation_graph("new_user", "full")
        accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="full")
        await accessor.aupdate(
            {"configurable": {"thread_id": record.thread_id}},
            {"messages": [HumanMessage(content="Also include the appendix.")]},
            as_node="new_user",
        )

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, during_receipt=add_message)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.success
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_user_clear_during_delivery_receipt_is_not_restored(tmp_path, monkeypatch):
    async def clear_goal(checkpointer, _manager, record):
        await write_thread_goal(checkpointer, record.thread_id, None)

    result = await _run_goal_delivery(tmp_path, monkeypatch, during_receipt=clear_goal)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.record.status == RunStatus.error
    assert result.goal is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["return_false", "raise"])
async def test_unconfirmed_terminal_status_preserves_goal(tmp_path, monkeypatch, failure):
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, fail_terminal_status=failure)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.delivery[0]["satisfied"] is True
    assert result.failed_terminal_writes
    assert result.durable_run["status"] == "running"
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_recovered_terminal_status_can_clear_satisfied_goal(tmp_path, monkeypatch):
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, fail_terminal_status="return_false", completion_recovers=True)

    assert result.model_calls == [True]
    assert result.turns == [1]
    assert result.failed_terminal_writes
    assert result.delivery[0]["satisfied"] is True
    assert result.durable_run["status"] == "success"
    assert result.goal is None


@pytest.mark.asyncio
@pytest.mark.parametrize("present_on_turn", [None, 1])
async def test_delta_checkpoint_goal_follows_delivery_outcome(tmp_path, monkeypatch, present_on_turn):
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=present_on_turn, checkpoint_mode="delta")

    assert result.model_calls == [True]
    assert result.turns == [1]
    if present_on_turn is None:
        assert result.record.status == RunStatus.error
        assert result.goal == result.original_goal
    else:
        assert result.record.status == RunStatus.success
        assert result.goal is None


@pytest.mark.asyncio
async def test_peer_admitted_before_goal_clear_preserves_goal(tmp_path, monkeypatch):
    peer_runs = []

    async def admit_peer(run_store, record):
        peer = RunManager(store=run_store, worker_id="peer")
        peer_runs.append(await peer.create_or_reject(record.thread_id))

    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, after_terminal_completion=admit_peer)

    assert len(peer_runs) == 1
    assert result.record.status == RunStatus.success
    assert result.durable_run["status"] == "success"
    assert result.goal == result.original_goal


@pytest.mark.asyncio
async def test_goal_clear_reservation_rejects_peer_admission(tmp_path, monkeypatch):
    peers = []
    blocked_admissions = []
    original_write_goal = worker.write_thread_goal

    async def capture_peer(run_store, _record):
        peers.append(RunManager(store=run_store, worker_id="peer"))

    async def write_goal(checkpointer, thread_id, goal, **kwargs):
        if goal is None:
            assert peers, "A goal must not be cleared before terminal completion"
            with pytest.raises(ConflictError):
                await peers[0].create_or_reject(thread_id)
            blocked_admissions.append(thread_id)
        return await original_write_goal(checkpointer, thread_id, goal, **kwargs)

    monkeypatch.setattr(worker, "write_thread_goal", write_goal)
    result = await _run_goal_delivery(tmp_path, monkeypatch, present_on_turn=1, after_terminal_completion=capture_peer)

    assert blocked_admissions == [result.record.thread_id]
    assert result.record.status == RunStatus.success
    assert result.durable_run["status"] == "success"
    assert result.goal is None
