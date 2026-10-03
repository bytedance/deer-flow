"""Real worker handoff must not carry an occurrence's goal into a user turn."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import goal
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import ConflictError, RunManager, RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.store.base import canonical_run_created_at
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def infrastructure(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore(), InMemorySaver()
        return
    path = tmp_path / "shared.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 2})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        # Separate ORM/saver connections to the same file expose writer-lock
        # deadlocks that an in-memory checkpoint double cannot reveal.
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            yield RunRepository(async_sessionmaker(engine, expire_on_commit=False)), saver
    finally:
        await engine.dispose()


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


def _graph(node, checkpointer, mode):
    graph = StateGraph(get_thread_state_schema(mode))
    graph.add_node("answer", node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("failure", ["ambiguous", "invalid_objective", "unsupported_store"])
async def test_preflight_resolution_failure_blocks_execution_and_preserves_existing_goal(infrastructure, monkeypatch, mode, failure):
    store, checkpointer = infrastructure
    timestamp = "2026-10-03T00:00:00.123456+00:00"
    existing = goal.build_goal_state("User goal", now=timestamp)
    await goal.write_thread_goal(checkpointer, "result", existing, create_if_missing=True)
    if failure == "unsupported_store":
        monkeypatch.setattr(store, "list_by_thread_created_at", AsyncMock(side_effect=NotImplementedError))
    else:
        # Matching history is not proof that this goal belongs to one occurrence:
        # duplicate identities and malformed candidates must preserve the goal.
        metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": existing["objective"] if failure == "ambiguous" else " "}
        for index in range(2 if failure == "ambiguous" else 1):
            await store.put(f"source-{index}", thread_id="result", user_id="alice", status="error", created_at=timestamp, metadata=metadata)
    manager = RunManager(store=store)
    record = await manager.create_or_reject("result", user_id="alice")
    observed = []

    async def node(state):
        observed.append(state.get("goal"))
        return {"messages": [AIMessage(content="New answer")], "title": "New request"}

    evaluate = AsyncMock()
    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    compiled = _graph(node, checkpointer, mode)
    stream = Mock(wraps=compiled.astream)
    monkeypatch.setattr(compiled, "astream", stream)
    bridge = _bridge()
    await worker.run_agent(
        bridge,
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="An unrelated user request")]},
        config={"configurable": {"thread_id": "result"}},
    )
    expected_error = "Scheduled goal recovery could not verify the existing goal's ownership. Agent execution did not start; the goal was preserved."
    assert record.status == RunStatus.error
    assert record.error == expected_error
    assert observed == []
    stream.assert_not_called()
    evaluate.assert_not_awaited()
    assert await goal.read_thread_goal(checkpointer, "result") == existing
    row = await store.get(record.run_id, user_id="alice")
    assert row["status"] == "error"
    assert row["error"] == expected_error
    assert row.get("goal_verdict") is None
    bridge.publish.assert_any_await(record.run_id, "error", {"message": expected_error, "name": "RuntimeError"})


@pytest.mark.asyncio
async def test_preflight_resolution_does_not_convert_cancellation_to_failure(infrastructure, monkeypatch):
    store, checkpointer = infrastructure
    existing = goal.build_goal_state("User goal", now="2026-10-03T00:00:00.123456+00:00")
    await goal.write_thread_goal(checkpointer, "result", existing, create_if_missing=True)
    manager = RunManager(store=store)
    record = await manager.create_or_reject("result", user_id="alice")
    cancellation = asyncio.CancelledError()
    monkeypatch.setattr(manager, "scheduled_goal_source", AsyncMock(side_effect=cancellation))
    with pytest.raises(asyncio.CancelledError) as caught:
        await worker._clear_stale_scheduled_goal(record=record, run_manager=manager, bridge=_bridge(), checkpointer=checkpointer)
    assert caught.value is cancellation
    assert record.status == RunStatus.pending
    assert await goal.read_thread_goal(checkpointer, "result") == existing


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("satisfied", [False, True])
async def test_two_worker_terminal_handoff_cannot_inherit_scheduled_goal(infrastructure, monkeypatch, mode, satisfied):
    store, checkpointer = infrastructure
    scheduler = RunManager(store=store, worker_id="scheduler")
    peer = RunManager(store=store, worker_id="peer")
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Scheduled report"}
    scheduled = await scheduler.create_or_reject("result", user_id="alice", metadata=metadata)
    entered = asyncio.Event()
    inherited, peer_tasks = [], []

    async def scheduled_node(state):
        return {"messages": [AIMessage(content="Report complete" if satisfied else "BLOCKED: missing source")], "title": "Report"}

    async def ordinary_node(state):
        inherited.append(state.get("goal"))
        entered.set()
        return {"messages": [AIMessage(content="Ordinary follow-up complete")], "title": "Follow-up"}

    graph_a, graph_b = _graph(scheduled_node, checkpointer, mode), _graph(ordinary_node, checkpointer, mode)

    async def evaluate(*args, **kwargs):
        return {"satisfied": satisfied, "blocker": "none" if satisfied else "needs_user_input", "reason": "Verified" if satisfied else "BLOCKED", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    update_status = store.update_status
    handed_off = False

    async def admit_after_terminal_commit(run_id, status, **kwargs):
        nonlocal handed_off
        updated = await update_status(run_id, status, **kwargs)
        if updated and run_id == scheduled.run_id and status == "success" and not handed_off:
            handed_off = True
            ordinary = await peer.create_or_reject("result", user_id="alice")
            peer_tasks.append(
                asyncio.create_task(
                    worker.run_agent(
                        _bridge(),
                        peer,
                        ordinary,
                        ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode),
                        agent_factory=lambda config: graph_b,
                        graph_input={"messages": [HumanMessage(content="Different ordinary request")]},
                        config={"configurable": {"thread_id": "result"}},
                    )
                )
            )
            await entered.wait()
        return updated

    monkeypatch.setattr(store, "update_status", admit_after_terminal_commit)
    try:
        async with asyncio.timeout(10):
            await worker.run_agent(
                _bridge(),
                scheduler,
                scheduled,
                ctx=worker.RunContext(
                    checkpointer=checkpointer, checkpoint_channel_mode=mode, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": metadata["scheduled_goal_objective"]}
                ),
                agent_factory=lambda config: graph_a,
                graph_input={"messages": [HumanMessage(content="Scheduled report request")]},
                config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
            )
        assert handed_off
        assert inherited == [None]
        assert await goal.read_thread_goal(checkpointer, "result") is None
    finally:
        if peer_tasks:
            await asyncio.gather(*peer_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["interrupt", "rollback"])
async def test_scheduled_local_cancel_retains_admission_until_worker_cleans_goal(infrastructure, monkeypatch, action):
    store, checkpointer = infrastructure
    manager = RunManager(store=store, worker_id="scheduler")
    peer = RunManager(store=store, worker_id="peer")
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Scheduled report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    cleanup_write_statuses = []
    write_goal = worker.write_thread_goal

    async def inspect_cleanup(*args, **kwargs):
        if args[2] is None:
            row = await store.get(record.run_id, user_id="alice")
            cleanup_write_statuses.append(row["status"])
        return await write_goal(*args, **kwargs)

    monkeypatch.setattr(worker, "write_thread_goal", inspect_cleanup)

    async def node(state):
        await manager.cancel(record.run_id, action=action)
        assert (await store.get(record.run_id, user_id="alice"))["status"] == "running"
        for strategies in ((manager, "interrupt"), (manager, "rollback"), (peer, "reject")):
            with pytest.raises(ConflictError):
                await strategies[0].create_or_reject("result", user_id="alice", multitask_strategy=strategies[1])
        return {"messages": [AIMessage(content="Stopped")], "title": "Stopped"}

    compiled = _graph(node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": metadata["scheduled_goal_objective"]}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    assert record.status == (RunStatus.error if action == "rollback" else RunStatus.interrupted)
    assert await goal.read_thread_goal(checkpointer, "result") is None
    assert all(status in {"pending", "running"} for status in cleanup_write_statuses)
    assert record.scheduled_goal_cleanup_pending is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_restart_worker_clears_exact_terminal_scheduled_goal_before_ordinary_turn(infrastructure, monkeypatch, mode):
    store, checkpointer = infrastructure
    crashed = RunManager(store=store, worker_id="crashed")
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Scheduled report"}
    original = await crashed.create_or_reject("result", user_id="alice", metadata=metadata)
    installed = goal.build_goal_state(metadata["scheduled_goal_objective"], now=canonical_run_created_at(original.created_at))
    await goal.write_thread_goal(checkpointer, "result", installed, create_if_missing=True)
    await store.update_status(original.run_id, "error", error="Recovered after process loss")
    # A restart loses every process-local goal flag; exact durable matching must
    # still work after this occurrence falls out of a 100-row history page.
    for index in range(105):
        timestamp = (datetime.fromisoformat(original.created_at) + timedelta(seconds=index + 1)).isoformat()
        await store.put(f"ordinary-{index}", thread_id="result", user_id="alice", status="success", created_at=timestamp)
    restarted = RunManager(store=store, worker_id="restarted")
    record = await restarted.create_or_reject("result", user_id="alice")
    observed = []

    async def node(state):
        observed.append(state.get("goal"))
        return {"messages": [AIMessage(content="Ordinary turn")], "title": "Follow-up"}

    monkeypatch.setattr(store, "list_by_thread", AsyncMock(side_effect=AssertionError("bounded history must not establish goal ownership")))
    compiled = _graph(node, checkpointer, mode)
    await worker.run_agent(
        _bridge(),
        restarted,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="A new user request")]},
        config={"configurable": {"thread_id": "result"}},
    )
    assert record.status == RunStatus.success
    assert observed == [None]
    assert await goal.read_thread_goal(checkpointer, "result") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_time", ["later", "equivalent_offset"])
async def test_restart_matching_preserves_new_user_goal_even_with_same_objective(infrastructure, monkeypatch, replacement_time):
    store, checkpointer = infrastructure
    old_manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    old = await old_manager.create_or_reject("result", user_id="alice", metadata=metadata)
    await old_manager.set_status(old.run_id, RunStatus.error)
    timestamp = "2099-01-01T00:00:00.000001+00:00" if replacement_time == "later" else datetime.fromisoformat(old.created_at).astimezone(timezone(timedelta(hours=8))).isoformat()
    replacement = goal.build_goal_state("Report", now=timestamp)
    await goal.write_thread_goal(checkpointer, "result", replacement, create_if_missing=True)
    restarted = RunManager(store=store)
    record = await restarted.create_or_reject("result", user_id="alice")
    observed = []

    async def node(state):
        observed.append(state["goal"])
        return {"messages": [AIMessage(content="BLOCKED")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        return {"satisfied": False, "blocker": "needs_user_input", "reason": "BLOCKED"}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, "full")
    await worker.run_agent(
        _bridge(), restarted, record, ctx=worker.RunContext(checkpointer=checkpointer), agent_factory=lambda config: compiled, graph_input={"messages": [HumanMessage(content="New request")]}, config={"configurable": {"thread_id": "result"}}
    )
    assert observed[0]["created_at"] == replacement["created_at"]
    assert (await goal.read_thread_goal(checkpointer, "result"))["created_at"] == replacement["created_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["terminal_write", "goal_cleanup"])
async def test_scheduled_cleanup_survives_persistence_failure_and_restart(infrastructure, monkeypatch, failure):
    store, checkpointer = infrastructure
    manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    update_status, write_goal = store.update_status, worker.write_thread_goal
    failures = []

    async def fail_terminal(run_id, status, **kwargs):
        if run_id == record.run_id and status == "success" and not failures:
            failures.append(failure)
            assert await goal.read_thread_goal(checkpointer, "result") is None
            raise RuntimeError("terminal write failed once")
        return await update_status(run_id, status, **kwargs)

    async def fail_cleanup(*args, **kwargs):
        if args[2] is None and not failures:
            failures.append(failure)
            raise RuntimeError("goal cleanup failed once")
        return await write_goal(*args, **kwargs)

    if failure == "terminal_write":
        monkeypatch.setattr(store, "update_status", fail_terminal)
    else:
        monkeypatch.setattr(worker, "write_thread_goal", fail_cleanup)

    async def node(state):
        return {"messages": [AIMessage(content="Report verified")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    assert failures == [failure]
    row = await store.get(record.run_id, user_id="alice")
    assert row["status"] == ("success" if failure == "terminal_write" else "error")
    assert row["goal_verdict"]["satisfied"] is True
    restarted = RunManager(store=store)
    next_record = await restarted.create_or_reject("result", user_id="alice")
    observed = []

    async def ordinary_node(state):
        observed.append(state.get("goal"))
        return {"messages": [AIMessage(content="Follow-up")], "title": "Follow-up"}

    ordinary = _graph(ordinary_node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        restarted,
        next_record,
        ctx=worker.RunContext(checkpointer=checkpointer),
        agent_factory=lambda config: ordinary,
        graph_input={"messages": [HumanMessage(content="New request")]},
        config={"configurable": {"thread_id": "result"}},
    )
    assert observed == [None]


@pytest.mark.asyncio
async def test_expired_lease_fences_cleanup_until_recovery_reuses_the_thread(infrastructure, monkeypatch):
    store, checkpointer = infrastructure
    ownership = RunOwnershipConfig(heartbeat_enabled=True, grace_seconds=0)
    manager = RunManager(store=store, worker_id="expired", run_ownership_config=ownership)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)

    async def node(state):
        return {"messages": [AIMessage(content="Report")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        expiry = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        assert await store.update_lease(record.run_id, owner_worker_id="expired", lease_expires_at=expiry)
        record.lease_expires_at = expiry
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    assert record.ownership_lost
    assert await goal.read_thread_goal(checkpointer, "result") is not None
    restarted = RunManager(store=store, worker_id="restarted", run_ownership_config=ownership)
    recovered = await restarted.reconcile_orphaned_inflight_runs(error="Recovered expired scheduled run")
    assert [row.run_id for row in recovered] == [record.run_id]
    assert (await store.get(record.run_id, user_id="alice"))["status"] == "error"
    next_record = await restarted.create_or_reject("result", user_id="alice")
    observed = []

    async def ordinary_node(state):
        observed.append(state.get("goal"))
        return {"messages": [AIMessage(content="New result")], "title": "Follow-up"}

    ordinary = _graph(ordinary_node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        restarted,
        next_record,
        ctx=worker.RunContext(checkpointer=checkpointer),
        agent_factory=lambda config: ordinary,
        graph_input={"messages": [HumanMessage(content="New request")]},
        config={"configurable": {"thread_id": "result"}},
    )
    assert observed == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["owned", "foreign", "shared", "other_thread", "replacement", "busy"])
async def test_idle_recovery_reserves_thread_and_preserves_unowned_or_new_goal(infrastructure, case):
    store, checkpointer = infrastructure
    timestamp = "2026-10-03T00:00:00.123456+00:00"
    owner = "bob" if case == "foreign" else None if case == "shared" else "alice"
    source_thread = "different" if case == "other_thread" else "result"
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    await store.put("source", thread_id=source_thread, user_id=owner, status="error", created_at=timestamp, metadata=metadata)
    old = RunRecord(run_id="source", thread_id=source_thread, user_id="alice", status=RunStatus.error, assistant_id="lead-agent", on_disconnect=DisconnectMode.continue_, created_at=timestamp, metadata=metadata, store_only=True)
    installed = goal.build_goal_state("Report", now="2027-01-01T00:00:00.000000+00:00" if case == "replacement" else timestamp)
    await goal.write_thread_goal(checkpointer, "result", installed, create_if_missing=True)
    recovery = RunManager(store=store)
    active = await recovery.create_or_reject("result", user_id="alice") if case == "busy" else None
    async with asyncio.timeout(5):
        await worker.clear_recovered_scheduled_goal(old, run_manager=recovery, checkpointer=checkpointer)
    remaining = await goal.read_thread_goal(checkpointer, "result")
    assert remaining == (None if case == "owned" else installed)
    if active is not None:
        await recovery.set_status(active.run_id, RunStatus.interrupted)


@pytest.mark.asyncio
async def test_scheduled_cleanup_barrier_keeps_lease_renewal_and_remote_cancel_active(infrastructure):
    store, _ = infrastructure
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("result", user_id="alice")
    record.scheduled_goal_cleanup_pending = True
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    original_deadline = record.lease_expires_at
    await store.request_cancel(record.run_id, action="rollback")
    await manager._renew_leases()
    assert record.lease_expires_at > original_deadline
    assert record.abort_event.is_set()
    assert record.abort_action == "rollback"
    assert (await store.get(record.run_id, user_id="alice"))["status"] == "pending"


@pytest.mark.asyncio
async def test_user_goal_replacement_wins_when_scheduled_evaluation_is_cancelled(infrastructure, monkeypatch):
    store, checkpointer = infrastructure
    manager = RunManager(store=store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    replacement = goal.build_goal_state("Report", now="2099-01-01T00:00:00.000001+00:00")

    async def node(state):
        return {"messages": [AIMessage(content="Report verified")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        await goal.write_thread_goal(checkpointer, "result", replacement)
        await manager.cancel(record.run_id)
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, "full")
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    assert record.status == RunStatus.interrupted
    assert await goal.read_thread_goal(checkpointer, "result") == replacement


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("origin", ["local", "remote"])
@pytest.mark.parametrize("action", ["interrupt", "rollback"])
async def test_cancel_accepted_during_cleanup_wins_staged_success(infrastructure, monkeypatch, mode, origin, action):
    store, checkpointer = infrastructure
    manager = RunManager(store=store, worker_id="scheduler", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    write_goal = worker.write_thread_goal
    accepted = []

    async def cancel_in_cleanup(*args, **kwargs):
        if args[2] is None and not accepted:
            assert record.status == RunStatus.success
            if origin == "remote":
                accepted.append(await store.request_cancel(record.run_id, action=action))
                await manager._renew_leases()
            else:
                accepted.append(await manager.cancel(record.run_id, action=action))
            assert record.abort_event.is_set()
            assert (await store.get(record.run_id, user_id="alice"))["status"] == "running"
        return await write_goal(*args, **kwargs)

    monkeypatch.setattr(worker, "write_thread_goal", cancel_in_cleanup)

    async def node(state):
        return {"messages": [AIMessage(content="Report verified")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, mode)
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    row = await store.get(record.run_id, user_id="alice")
    assert accepted
    assert row["status"] == ("error" if action == "rollback" else "interrupted")
    assert await goal.read_thread_goal(checkpointer, "result") is None
    snapshot = await CheckpointStateAccessor.bind(compiled, checkpointer, mode=mode).aget({"configurable": {"thread_id": "result"}})
    answers = [message.content for message in snapshot.values.get("messages", []) if isinstance(message, AIMessage)]
    assert ("Report verified" in answers) is (action == "interrupt")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("origin", ["local", "remote"])
@pytest.mark.parametrize("action", ["interrupt", "rollback"])
async def test_cancel_accepted_at_terminal_cas_wins_after_worker_abort_check(infrastructure, monkeypatch, mode, origin, action):
    store, checkpointer = infrastructure
    manager = RunManager(store=store, worker_id="scheduler", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    finalize = store.finalize_if_not_cancelled
    accepted = []

    async def cancel_before_status_cas(run_id, **kwargs):
        if run_id == record.run_id and kwargs["status"] == "success" and not accepted:
            # This is beyond the worker's abort_event branch, directly before
            # the actual database compare-and-set. Moving a Python check
            # earlier cannot satisfy this contract.
            assert not record.abort_event.is_set()
            assert await goal.read_thread_goal(checkpointer, "result") is None
            if origin == "remote":
                accepted.append(await store.request_cancel(run_id, action=action))
            else:
                accepted.append(await manager.cancel(run_id, action=action))
        return await finalize(run_id, **kwargs)

    monkeypatch.setattr(store, "finalize_if_not_cancelled", cancel_before_status_cas)

    async def node(state):
        return {"messages": [AIMessage(content="Report verified")], "title": "Report"}

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(node, checkpointer, mode)
    await worker.run_agent(
        _bridge(),
        manager,
        record,
        ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Report")]},
        config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
    )
    assert accepted
    row = await store.get(record.run_id, user_id="alice")
    assert row["status"] == ("error" if action == "rollback" else "interrupted")
    snapshot = await CheckpointStateAccessor.bind(compiled, checkpointer, mode=mode).aget({"configurable": {"thread_id": "result"}})
    answers = [message.content for message in snapshot.values.get("messages", []) if isinstance(message, AIMessage)]
    assert ("Report verified" in answers) is (action == "interrupt")
