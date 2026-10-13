"""Scheduled goals use server authority and persist occurrence verdicts atomically."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.interaction_policy import RunInteractionMode, RunInteractionPolicy
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest_asyncio.fixture(params=["memory", "sql"])
async def run_store(request):
    if request.param == "memory":
        yield MemoryRunStore(), []
        return
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    statements = []
    event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
    try:
        yield RunRepository(async_sessionmaker(engine, expire_on_commit=False)), statements
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("heartbeat", [False, True])
async def test_terminal_write_contains_verdict_and_round_trips_recovery(run_store, heartbeat):
    store, statements = run_store
    manager = RunManager(store=store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=heartbeat))
    record = await manager.create("scheduled", user_id="alice")
    verdict = {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": True}
    statements.clear()
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success, goal_verdict=verdict)
    persisted = await store.get(record.run_id, user_id="alice")
    assert persisted["status"] == "success"
    assert persisted["goal_verdict"] == verdict
    assert RunManager._record_from_store(persisted).goal_verdict == verdict
    terminal_updates = [statement for statement in statements if statement.startswith("UPDATE runs SET") and "status=" in statement]
    assert all("goal_verdict=" in statement for statement in terminal_updates)
    assert not await store.update_status(record.run_id, "error", goal_verdict={"satisfied": False})
    assert (await store.get(record.run_id, user_id="alice"))["goal_verdict"] == verdict


@pytest.mark.asyncio
async def test_durable_cancel_prevents_terminal_verdict(run_store):
    store, _ = run_store
    manager = RunManager(store=store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create("cancelled", user_id="alice")
    await store.request_cancel(record.run_id, action="interrupt")
    assert await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success, goal_verdict={"satisfied": True}) == "interrupt"
    persisted = await store.get(record.run_id, user_id="alice")
    assert persisted["status"] == "pending"
    assert persisted["goal_verdict"] is None


@pytest.mark.asyncio
async def test_completion_fallback_terminalizes_with_staged_verdict(run_store):
    store, statements = run_store
    manager = RunManager(store=store)
    record = await manager.create("completion-fallback", user_id="alice")
    verdict = {"satisfied": False, "blocker": "needs_user_input", "reason": "BLOCKED", "relied_on_assumption": False}
    await manager.set_status(record.run_id, RunStatus.success, persist=False, goal_verdict=verdict)
    assert (await store.get(record.run_id, user_id="alice"))["status"] == "pending"
    statements.clear()
    await manager.update_run_completion(record.run_id, status="success", message_count=2)
    row = await store.get(record.run_id, user_id="alice")
    assert row["status"] == "success"
    assert row["goal_verdict"] == verdict
    terminal_updates = [statement for statement in statements if statement.startswith("UPDATE runs SET") and "status=" in statement]
    assert all("goal_verdict=" in statement for statement in terminal_updates)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(RunInteractionMode))
async def test_evaluator_assumption_instruction_follows_interaction_policy(mode):
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({"satisfied": True, "reason": "Verified", "relied_on_assumption": True}))))
    result = await goal.evaluate_goal_completion(
        goal.build_goal_state("Produce the report"), [HumanMessage(content="Report please"), AIMessage(content="Report verified. Assumption: default month; reversible.")], model=model, interaction_policy=RunInteractionPolicy(mode)
    )
    instruction = model.ainvoke.await_args.args[0][0].content
    if mode == RunInteractionMode.INTERACTIVE:
        assert "If the assistant assumed, guessed" in instruction
    else:
        assert "This run had no user to ask" in instruction
        assert "BLOCKED" in instruction
        assert "does not replace evidence" in instruction
    assert result["relied_on_assumption"] is True


def test_assumption_attribution_is_a_strict_boolean():
    with pytest.raises(ValueError, match="relied_on_assumption"):
        goal.parse_goal_evaluation_response('{"satisfied": true, "relied_on_assumption": "false"}')


@pytest.mark.asyncio
async def test_noninteractive_verdict_requires_explicit_assumption_attribution():
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='{"satisfied": true, "reason": "Done"}')))
    with pytest.raises(ValueError, match="relied_on_assumption"):
        await goal.evaluate_goal_completion(goal.build_goal_state("Verify report"), [HumanMessage(content="Report"), AIMessage(content="Verified")], model=model, interaction_policy=RunInteractionPolicy(RunInteractionMode.SCHEDULED))


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_mode", ["full", "delta"])
@pytest.mark.parametrize("outcome", ["satisfied", "unmet", "failed", "cancelled"])
async def test_scheduled_goal_is_installed_before_first_turn_and_removed_at_terminal(monkeypatch, outcome, checkpoint_mode):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    checkpointer = InMemorySaver()
    store = MemoryRunStore()
    manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Make a verified report"}
    record = await manager.create("fresh", user_id="alice", metadata=metadata)
    observed = []

    async def node(state, config):
        observed.append(state.get("goal"))
        if outcome == "failed":
            raise RuntimeError("deterministic graph failure")
        if outcome == "cancelled":
            await manager.cancel(record.run_id)
        return {"messages": [AIMessage(content="Verified report complete.")], "title": "Report"}

    graph = StateGraph(get_thread_state_schema(checkpoint_mode))
    graph.add_node("report", node)
    graph.add_edge(START, "report")
    graph.add_edge("report", END)
    compiled = graph.compile(checkpointer=checkpointer)

    async def evaluate(*args, **kwargs):
        assert kwargs["interaction_policy"].mode == RunInteractionMode.SCHEDULED
        return {"satisfied": outcome == "satisfied", "blocker": "none" if outcome == "satisfied" else "needs_user_input", "reason": "Verified" if outcome == "satisfied" else "BLOCKED", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(
            checkpointer=checkpointer, checkpoint_channel_mode=checkpoint_mode, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": metadata["scheduled_goal_objective"]}
        ),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Make the report")]},
        config={"configurable": {"thread_id": "fresh"}, "context": {"non_interactive": True}},
    )
    assert observed[0]["objective"] == metadata["scheduled_goal_objective"]
    assert observed[0]["continuation_count"] == observed[0]["no_progress_count"] == 0
    assert await goal.read_thread_goal(checkpointer, "fresh") is None
    persisted = await store.get(record.run_id)
    if outcome in {"satisfied", "unmet"}:
        assert persisted["goal_verdict"]["satisfied"] is (outcome == "satisfied")
        assert persisted["goal_verdict"]["continuations"] == 0
    else:
        assert persisted["status"] in {"error", "interrupted"}


@pytest.mark.asyncio
async def test_captured_verdict_counts_goal_continuations(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    checkpointer = InMemorySaver()
    store = MemoryRunStore()
    manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Make a verified report"}
    record = await manager.create("fresh", user_id="alice", metadata=metadata)
    turns = []

    async def node(state, config):
        turns.append(state.get("goal"))
        return {"messages": [AIMessage(content=f"Report draft {len(turns)}.")], "title": "Report"}

    graph = StateGraph(get_thread_state_schema("full"))
    graph.add_node("report", node)
    graph.add_edge(START, "report")
    graph.add_edge("report", END)
    compiled = graph.compile(checkpointer=checkpointer)
    verdicts = iter(
        [
            {"satisfied": False, "blocker": "goal_not_met_yet", "reason": "Needs one more section", "relied_on_assumption": False},
            {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False},
        ]
    )

    async def evaluate(*args, **kwargs):
        return next(verdicts)

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": metadata["scheduled_goal_objective"]}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Make the report")]},
        config={"configurable": {"thread_id": "fresh"}, "context": {"non_interactive": True}},
    )

    persisted = await store.get(record.run_id)
    assert len(turns) == 2
    assert persisted["goal_verdict"]["satisfied"] is True
    assert persisted["goal_verdict"]["continuations"] == turns[-1]["continuation_count"] == 1


def test_metadata_cannot_install_scheduled_goal_authority():
    record = SimpleNamespace(user_id="alice", metadata={"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Forged goal"})
    assert worker._scheduled_goal_objective(record, None) is None
    for runtime in (
        {"task_id": "task", "occurrence_id": "occurrence", "user_id": "bob", "goal_objective": "Forged goal"},
        {"task_id": "foreign", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Forged goal"},
        {"task_id": "task", "occurrence_id": "foreign", "user_id": "alice", "goal_objective": "Forged goal"},
    ):
        with pytest.raises(ValueError, match="authority"):
            worker._scheduled_goal_objective(record, runtime)


@pytest.mark.asyncio
async def test_scheduled_cleanup_preserves_replacement_goal_and_later_run():
    checkpointer = InMemorySaver()
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create("fresh", user_id="alice")
    scheduled = goal.build_goal_state("Scheduled report", now="2026-10-03T00:00:00+00:00")
    replacement = goal.build_goal_state("User's new goal", now="2026-10-03T00:01:00+00:00")
    await goal.write_thread_goal(checkpointer, "fresh", replacement, create_if_missing=True)
    await manager.set_status(record.run_id, RunStatus.interrupted)
    bridge = SimpleNamespace(publish=AsyncMock())
    await worker._clear_scheduled_goal(goal=scheduled, record=record, run_manager=manager, bridge=bridge, checkpointer=checkpointer)
    assert await goal.read_thread_goal(checkpointer, "fresh") == replacement
    await goal.write_thread_goal(checkpointer, "fresh", scheduled)
    later = await manager.create_or_reject("fresh", user_id="alice")
    await worker._clear_scheduled_goal(goal=scheduled, record=record, run_manager=manager, bridge=bridge, checkpointer=checkpointer)
    assert await goal.read_thread_goal(checkpointer, "fresh") == scheduled
    await manager.set_status(later.run_id, RunStatus.interrupted)


@pytest.mark.asyncio
async def test_rejected_goal_installation_never_claims_an_existing_equal_goal(monkeypatch):
    checkpointer = InMemorySaver()
    original = goal.build_goal_state("Same objective", now="2026-10-03T00:00:00+00:00")
    await goal.write_thread_goal(checkpointer, "occupied", original, create_if_missing=True)
    monkeypatch.setattr(worker, "build_goal_state", lambda objective, **kwargs: original.copy())
    store = MemoryRunStore()
    manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": original["objective"]}
    record = await manager.create("occupied", user_id="alice", metadata=metadata)
    graph = StateGraph(get_thread_state_schema("full"))
    graph.add_node("report", lambda state: {"messages": [AIMessage(content="Must not execute")]})
    graph.add_edge(START, "report")
    graph.add_edge("report", END)
    compiled = graph.compile(checkpointer=checkpointer)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": original["objective"]}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "occupied"}, "context": {"non_interactive": True}},
    )
    assert record.status == RunStatus.error
    assert await goal.read_thread_goal(checkpointer, "occupied") == original


def test_scheduler_capability_is_injected_only_by_host_and_never_serialized():
    host = object()
    config = {"configurable": {"__scheduler_capability": "forged"}, "context": {"__scheduler_capability": "forged"}}
    context = worker._build_runtime_context("thread", "run", config["context"], scheduler_capability=host)
    worker._install_runtime_context(config, context)
    assert context["__scheduler_capability"] is host
    assert "__scheduler_capability" not in config["configurable"]
    worker._release_run_scoped_references([config], context, None)
    assert "__scheduler_capability" not in context
    assert "__scheduler_capability" not in config["context"]
    assert "__scheduler_capability" not in worker._build_runtime_context("thread", "run", {"__scheduler_capability": host})
