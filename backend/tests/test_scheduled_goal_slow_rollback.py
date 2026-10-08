"""Scheduled rollback keeps ownership until its saver and terminal CAS settle."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args, dsn_with_search_path
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import CancelOutcome, ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.base import LeaseRenewal


def _asyncpg_fixture_url(uri: str) -> URL:
    url = make_url(uri)
    query = dict(url.query)
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    return url.set(drivername="postgresql+asyncpg", query=query)


@pytest.mark.parametrize("sslmode", [None, "disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
def test_asyncpg_fixture_url_preserves_sslmode_and_other_connect_options(sslmode):
    uri = "postgresql://user:password@localhost:5432/deerflow?target_session_attrs=read-write"
    if sslmode is not None:
        uri += f"&sslmode={sslmode}"
    url = _asyncpg_fixture_url(uri)
    _args, kwargs = url.get_dialect()().create_connect_args(url)
    assert url.drivername == "postgresql+asyncpg"
    assert kwargs["target_session_attrs"] == "read-write"
    assert "sslmode" not in kwargs
    if sslmode is None:
        assert "ssl" not in kwargs
    else:
        assert kwargs["ssl"] == sslmode
    assert make_url(dsn_with_search_path(uri, "fixture_schema")).query.get("sslmode") == sslmode


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def database_runtime(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("TEST_POSTGRES_URI is not set")
        postgres = pytest.importorskip("langgraph.checkpoint.postgres.aio")
        schema = "scheduled_rollback_" + uuid4().hex
        engine = create_async_engine(_asyncpg_fixture_url(uri), connect_args=build_asyncpg_connect_args(schema))
        saver_context = postgres.AsyncPostgresSaver.from_conn_string(dsn_with_search_path(uri, schema))
    else:
        path = tmp_path / "shared.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 2})
        saver_context = AsyncSqliteSaver.from_conn_string(str(path))
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        async with saver_context as saver:
            await saver.setup()
            yield RunRepository(async_sessionmaker(engine, expire_on_commit=False)), saver
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def _bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


def _graph(checkpointer, mode, answer):
    graph = StateGraph(get_thread_state_schema(mode))
    graph.add_node("answer", lambda state: {"messages": [AIMessage(content=answer)], "title": "Report"})
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("origin", ["remote", "local"])
async def test_slow_late_rollback_renews_slot_and_cannot_erase_peer_turn(database_runtime, monkeypatch, mode, origin):
    store, checkpointer = database_runtime
    ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0)
    owner = RunManager(store=store, worker_id="owner", run_ownership_config=ownership)
    peer = RunManager(store=store, worker_id="peer", run_ownership_config=ownership)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await owner.create_or_reject("result", user_id="alice", metadata=metadata)
    entered, release = asyncio.Event(), asyncio.Event()
    original_rollback, original_write = worker._rollback_to_pre_run_checkpoint, worker.write_thread_goal
    accepted = []

    async def late_cancel(*args, **kwargs):
        if args[2] is None and not accepted:
            if origin == "remote":
                accepted.append(await store.request_cancel(record.run_id, action="rollback"))
                await owner._renew_leases()
            else:
                accepted.append(await owner.cancel(record.run_id, action="rollback"))
        return await original_write(*args, **kwargs)

    async def slow_rollback(*args, **kwargs):
        if kwargs["run_id"] == record.run_id:
            entered.set()
            await release.wait()
        return await original_rollback(*args, **kwargs)

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "write_thread_goal", late_cancel)
    monkeypatch.setattr(worker, "_rollback_to_pre_run_checkpoint", slow_rollback)
    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(checkpointer, mode, "Cancelled scheduled answer")
    await owner.start_heartbeat()
    record.task = asyncio.create_task(
        worker.run_agent(
            _bridge(),
            owner,
            record,
            ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
            agent_factory=lambda config: compiled,
            graph_input={"messages": [HumanMessage(content="Report")]},
            config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
        )
    )
    try:
        async with asyncio.timeout(20):
            await entered.wait()
            initial_deadline = datetime.fromisoformat(record.lease_expires_at)
            pending_during_rollback = record.scheduled_goal_cleanup_pending
            # Events place the operation at the rollback boundary. Time is used
            # only to pass its original lease deadline; assertions concern the
            # durable ownership/admission state, never a timing performance SLA.
            await asyncio.sleep(max(0, (initial_deadline - datetime.now(UTC)).total_seconds()) + 0.3)
            row = await store.get(record.run_id, user_id="alice")
            recovered = await peer.reconcile_orphaned_inflight_runs(error="Peer recovery during a live rollback")
            early = None
            try:
                early = await peer.create_or_reject("result", user_id="alice")
            except ConflictError:
                pass
            peer_graph = _graph(checkpointer, mode, "New authoritative peer answer")
            if early is not None:
                await worker.run_agent(
                    _bridge(),
                    peer,
                    early,
                    ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode),
                    agent_factory=lambda config: peer_graph,
                    graph_input={"messages": [HumanMessage(content="New request")]},
                    config={"configurable": {"thread_id": "result"}},
                )
            release.set()
            await record.task
            assert pending_during_rollback
            assert row["status"] == "running"
            assert datetime.fromisoformat(row["lease_expires_at"]) > initial_deadline
            assert not recovered
            assert early is None
            assert not record.ownership_lost
            assert (await store.get(record.run_id, user_id="alice"))["status"] == "error"
            assert not record.scheduled_goal_cleanup_pending
            later = await peer.create_or_reject("result", user_id="alice")
            await worker.run_agent(
                _bridge(),
                peer,
                later,
                ctx=worker.RunContext(checkpointer=checkpointer, checkpoint_channel_mode=mode),
                agent_factory=lambda config: peer_graph,
                graph_input={"messages": [HumanMessage(content="New request after rollback")]},
                config={"configurable": {"thread_id": "result"}},
            )
            snapshot = await peer_graph.aget_state({"configurable": {"thread_id": "result"}})
            answers = [message.content for message in snapshot.values.get("messages", []) if isinstance(message, AIMessage)]
            assert "New authoritative peer answer" in answers
            assert "Cancelled scheduled answer" not in answers
    finally:
        release.set()
        await record.task
        await owner.stop_heartbeat()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error"])
@pytest.mark.parametrize("writer", ["owner", "peer"])
async def test_terminal_commit_heartbeat_distinguishes_owner_outcome_from_takeover(database_runtime, status, writer):
    store, _ = database_runtime
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("result", user_id="alice")
    record.scheduled_goal_cleanup_pending = True
    verdict = {"satisfied": status == "success", "relied_on_assumption": False}
    error = "Rolled back by user" if status == "error" else None
    await manager.set_status(record.run_id, RunStatus(status), error=error, goal_verdict=verdict, persist=False)
    if writer == "owner":
        # The owner's own deferred CAS commits through the manager so the
        # acknowledgement is attributable to this process. A store row that
        # merely matches is not by itself proof that this worker wrote it.
        assert (
            await manager.set_status_if_not_cancelled(
                record.run_id,
                RunStatus(status),
                error=error,
                goal_verdict=verdict,
            )
            is None
        )
        assert record.terminal_committed is True
    else:
        assert await store.update_status(record.run_id, "error", error="Peer reclaimed this run", stop_reason="orphan_recovered")
    # The durable terminal write has completed while the worker is still
    # receiving its acknowledgement; the local finalization barrier is held.
    await manager._renew_leases()
    assert record.ownership_lost is (writer == "peer")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error"])
async def test_peer_writing_identical_terminal_fields_is_not_adopted(database_runtime, status):
    """A peer write with identical fields must never release this worker's barrier.

    The removed ``_terminal_write_confirmed`` compared durable fields to accept a
    commit. A peer takeover can write the same ``status``, keep our
    ``owner_worker_id`` and copy the same ``goal_verdict``, so a field match is
    not proof that this worker wrote the terminal row. The barrier must stay
    closed and the local run must be fenced.
    """
    store, _ = database_runtime
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("result", user_id="alice")
    record.scheduled_goal_cleanup_pending = True
    verdict = {"satisfied": status == "success", "relied_on_assumption": False}
    error = "Rolled back by user" if status == "error" else None
    await manager.set_status(record.run_id, RunStatus(status), error=error, goal_verdict=verdict, persist=False)
    # A peer writes the *same* terminal fields, including our owner id.
    outcome = await store.finalize_if_not_cancelled(record.run_id, status=status, error=error, goal_verdict=verdict)
    assert outcome.finalized

    await manager._renew_leases()

    assert record.ownership_lost is True
    assert record.terminal_committed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error"])
@pytest.mark.parametrize("path", ["renew_rejected", "expired_after_read"])
async def test_terminal_commit_after_detached_precheck_is_reconfirmed_before_fencing(database_runtime, monkeypatch, status, path):
    store, _ = database_runtime
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("result", user_id="alice")
    await manager.set_status(record.run_id, RunStatus.running)
    record.scheduled_goal_cleanup_pending = True
    verdict = {"satisfied": status == "success", "relied_on_assumption": False}
    error = "Rolled back by user" if status == "error" else None
    await manager.set_status(record.run_id, RunStatus(status), error=error, goal_verdict=verdict, persist=False)

    observed: list[str] = []
    committed = asyncio.Event()
    release_ack = asyncio.Event()
    cas: asyncio.Task | None = None
    deadline = datetime.fromisoformat(record.lease_expires_at)
    clock_advanced = False

    if path == "expired_after_read":
        from deerflow.runtime.runs import manager as manager_module

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return deadline + timedelta(seconds=1) if clock_advanced else datetime.now(tz)

        monkeypatch.setattr(manager_module, "datetime", Clock)

    original_finalize = store.finalize_if_not_cancelled

    async def commit_then_delay_ack(run_id, *, status=None, error=None, stop_reason=None, **fields):
        result = await original_finalize(run_id, status=status, error=error, stop_reason=stop_reason, **fields)
        committed.set()
        await release_ack.wait()
        return result

    async def detach_precheck(run_id, **kwargs):
        nonlocal clock_advanced, cas
        snapshot = await store.get(run_id, user_id="alice")
        if not observed:
            # The renewal detached its precheck while the row still read
            # ``running``; the owner's own CAS then commits. Releasing the
            # barrier may only come from that attributable proof.
            observed.append(snapshot["status"])
            cas = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus(status), error=error, goal_verdict=verdict))
            await asyncio.wait_for(committed.wait(), timeout=5)
            clock_advanced = True
            if path == "renew_rejected":
                return LeaseRenewal(renewed=False)
        return LeaseRenewal(renewed=True)

    monkeypatch.setattr(store, "finalize_if_not_cancelled", commit_then_delay_ack)
    monkeypatch.setattr(store, "renew_lease", detach_precheck)

    renewal = asyncio.create_task(manager._renew_leases())
    await asyncio.wait_for(committed.wait(), timeout=5)
    release_ack.set()
    await asyncio.wait_for(renewal, timeout=5)
    if cas is not None:
        await asyncio.wait_for(cas, timeout=5)

    assert observed == ["running"]
    assert not record.ownership_lost
    assert record.status.value == status
    assert not record.scheduled_goal_cleanup_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error"])
async def test_detached_precheck_commit_race_preserves_worker_hook_and_stream_end(database_runtime, monkeypatch, status):
    """A detached renewal precheck must not fence this worker's own commit.

    The worker's terminal write starts a heartbeat renewal; the renewal reads the
    pre-commit row and is then rejected. Only this worker's own attributable
    commit proof may keep it from fencing, and the completion hook and end frame
    must still fire exactly once. Coordination is event-driven, never sleep-based.
    """
    store, checkpointer = database_runtime
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    read_done, committed = asyncio.Event(), asyncio.Event()
    get, renew, finalize, update_status, write_goal = store.get, store.renew_lease, store.finalize_if_not_cancelled, store.update_status, worker.write_thread_goal
    renewal_tasks = []
    intercepted, cancelled = [], []

    async def detach_and_reject(run_id, **kwargs):
        # Only the renewal started by this worker's own terminal write detaches
        # its precheck; the late scheduled-goal cancellation renewal stays real.
        if renewal_tasks and not intercepted:
            snapshot = await get(run_id, user_id="alice")
            intercepted.append(snapshot["status"])
            read_done.set()
            await committed.wait()
            return LeaseRenewal(renewed=False)
        return await renew(run_id, **kwargs)

    async def commit_with_delayed_ack(operation, run_id, **kwargs):
        if run_id != record.run_id or kwargs["status"] != status or renewal_tasks:
            return await operation(run_id, **kwargs)
        renewal_tasks.append(asyncio.create_task(manager._renew_leases()))
        await asyncio.wait_for(read_done.wait(), timeout=5)
        result = await operation(run_id, **kwargs)
        committed.set()
        return result

    async def finalize_with_ack(run_id, **kwargs):
        return await commit_with_delayed_ack(finalize, run_id, **kwargs)

    async def update_with_ack(run_id, value, **kwargs):
        async def operation(selected_id, *, status, **fields):
            return await update_status(selected_id, status, **fields)

        return await commit_with_delayed_ack(operation, run_id, status=value, **kwargs)

    async def cancel_for_error(*args, **kwargs):
        if status == "error" and args[2] is None and not cancelled:
            cancelled.append(await store.request_cancel(record.run_id, action="rollback"))
            await manager._renew_leases()
        return await write_goal(*args, **kwargs)

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(store, "renew_lease", detach_and_reject)
    monkeypatch.setattr(store, "finalize_if_not_cancelled", finalize_with_ack)
    monkeypatch.setattr(store, "update_status", update_with_ack)
    monkeypatch.setattr(worker, "write_thread_goal", cancel_for_error)
    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(checkpointer, "full", "Report verified")
    bridge, completed = _bridge(), AsyncMock()
    record.task = asyncio.create_task(
        worker.run_agent(
            bridge,
            manager,
            record,
            ctx=worker.RunContext(checkpointer=checkpointer, on_run_completed=completed, scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"}),
            agent_factory=lambda config: compiled,
            graph_input={"messages": [HumanMessage(content="Report")]},
            config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
        )
    )
    async with asyncio.timeout(10):
        await asyncio.gather(record.task, return_exceptions=True)
    if renewal_tasks:
        await asyncio.gather(*renewal_tasks, return_exceptions=True)
    assert intercepted == ["running"]
    assert not record.ownership_lost
    assert record.status.value == status
    completed.assert_awaited_once_with(record)
    bridge.publish_end.assert_awaited_once_with(record.run_id)


async def _wait_for_flag(event: asyncio.Event, *, timeout: float = 5.0) -> None:
    """Yield until an observable flag flips (deterministic, no fixed sleeps)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not event.is_set():
        if loop.time() >= deadline:
            raise AssertionError("timed out waiting for the expected state change")
        await asyncio.sleep(0)


async def _run_scheduled_goal_blocked_in_cleanup(database_runtime, monkeypatch, mode, *, on_entered):
    """Start a scheduled-goal run that parks inside its goal cleanup.

    Returns the pieces a shutdown test needs. ``on_entered`` runs once the
    worker is parked mid-cleanup, before the write is released.
    """
    store, checkpointer = database_runtime
    manager = RunManager(
        store=store,
        worker_id="owner",
        run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=0),
    )
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report"}
    record = await manager.create_or_reject("result", user_id="alice", metadata=metadata)
    entered, release = asyncio.Event(), asyncio.Event()
    restore_calls: list[str] = []
    publish_calls: list[str] = []
    original_rollback = worker._rollback_to_pre_run_checkpoint
    original_publish = worker._publish_restored_checkpoint_values
    original_write = worker.write_thread_goal

    async def blocking_write(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_write(*args, **kwargs)

    async def counting_rollback(*args, **kwargs):
        restore_calls.append(kwargs["run_id"])
        return await original_rollback(*args, **kwargs)

    async def counting_publish(*args, **kwargs):
        publish_calls.append(kwargs["run_id"])
        return await original_publish(*args, **kwargs)

    async def evaluate(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "Verified", "relied_on_assumption": False}

    monkeypatch.setattr(worker, "write_thread_goal", blocking_write)
    monkeypatch.setattr(worker, "_rollback_to_pre_run_checkpoint", counting_rollback)
    monkeypatch.setattr(worker, "_publish_restored_checkpoint_values", counting_publish)
    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    compiled = _graph(checkpointer, mode, "Cancelled scheduled answer")
    bridge = _bridge()
    record.task = asyncio.create_task(
        worker.run_agent(
            bridge,
            manager,
            record,
            ctx=worker.RunContext(
                checkpointer=checkpointer,
                checkpoint_channel_mode=mode,
                scheduled_task_runtime={"task_id": "task", "occurrence_id": "occurrence", "user_id": "alice", "goal_objective": "Report"},
            ),
            agent_factory=lambda config: compiled,
            graph_input={"messages": [HumanMessage(content="Report")]},
            config={"configurable": {"thread_id": "result"}, "context": {"non_interactive": True}},
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=10)
    await on_entered(manager, record, store)
    release.set()
    return manager, record, store, bridge, release, restore_calls, publish_calls


async def _shutdown_and_settle(manager, record, *, timeout: float = 5.0) -> None:
    shutdown = asyncio.create_task(manager.shutdown(timeout=timeout))
    await _wait_for_flag(record.abort_event)
    await asyncio.wait_for(shutdown, timeout=timeout + 5)
    await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_shutdown_preserves_remote_rollback_accepted_before_observation(database_runtime, monkeypatch, mode):
    """An accepted remote rollback must not be downgraded to interrupted on shutdown.

    A peer/remote writer accepts ``rollback`` and this worker has not observed it
    when process shutdown begins. Shutdown's provisional ``interrupt`` must not
    win: the terminal commit is arbitrated by the durable cancel CAS, the
    checkpoint is restored exactly once, and the run must not be left as a plain
    ``interrupted`` success-substitute.
    """

    async def on_entered(manager, record, store):
        # Remote rollback accepted; this worker has not observed it yet.
        assert await store.request_cancel(record.run_id, action="rollback") == "rollback"
        assert not record.abort_event.is_set()

    manager, record, store, bridge, release, restore_calls, publish_calls = await _run_scheduled_goal_blocked_in_cleanup(database_runtime, monkeypatch, mode, on_entered=on_entered)
    try:
        await _shutdown_and_settle(manager, record)
        row = await store.get(record.run_id, user_id="alice")
        assert row["status"] == "error", row
        assert row["error"] == "Rolled back by user"
        # The checkpoint is restored exactly once (this is the scheduled-goal
        # rollback path, not the edit-replay values-publish path).
        assert restore_calls == [record.run_id]
        bridge.publish_end.assert_awaited_once_with(record.run_id)
    finally:
        release.set()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_shutdown_keeps_locally_observed_rollback(database_runtime, monkeypatch, mode):
    """A rollback already observed locally must survive shutdown.

    The owning worker observes the rollback (via its local cancel path) before
    shutdown. Shutdown must not downgrade the decided action to ``interrupt``,
    and the checkpoint must be restored exactly once.
    """

    async def on_entered(manager, record, store):
        outcome = await manager.cancel(record.run_id, action="rollback")
        assert outcome is CancelOutcome.cancelled
        assert record.abort_action == "rollback"
        assert record.abort_event.is_set()

    manager, record, store, bridge, release, restore_calls, publish_calls = await _run_scheduled_goal_blocked_in_cleanup(database_runtime, monkeypatch, mode, on_entered=on_entered)
    try:
        await _shutdown_and_settle(manager, record)
        row = await store.get(record.run_id, user_id="alice")
        assert record.abort_action == "rollback", "shutdown must not downgrade an observed rollback"
        assert row["status"] == "error", row
        assert row["error"] == "Rolled back by user"
        # The checkpoint is restored exactly once (this is the scheduled-goal
        # rollback path, not the edit-replay values-publish path).
        assert restore_calls == [record.run_id]
        bridge.publish_end.assert_awaited_once_with(record.run_id)
    finally:
        release.set()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_shutdown_without_durable_cancel_does_not_commit_staged_success(database_runtime, monkeypatch, mode):
    """A bare shutdown interrupt must not commit the staged success.

    With no durable cancel, shutdown interrupts a scheduled-goal run whose
    terminal status is only staged. The worker must first resolve the local
    terminal to ``interrupted`` and then let the CAS commit it; committing the
    earlier staged ``success`` would be wrong.
    """

    async def on_entered(manager, record, store):
        # No durable cancel is recorded: the durable row is still running.
        row = await store.get(record.run_id, user_id="alice")
        assert row["status"] == "running"
        assert row.get("cancel_action") is None

    manager, record, store, bridge, release, restore_calls, publish_calls = await _run_scheduled_goal_blocked_in_cleanup(database_runtime, monkeypatch, mode, on_entered=on_entered)
    try:
        await _shutdown_and_settle(manager, record)
        row = await store.get(record.run_id, user_id="alice")
        assert row["status"] == "interrupted", row
        assert restore_calls == []
        bridge.publish_end.assert_awaited_once_with(record.run_id)
    finally:
        release.set()
        await asyncio.gather(record.task, return_exceptions=True)
