"""Behavioral regressions for authoritative Run terminal evidence.

Pinned baseline: fee0cd0c180874325305e995197db99f03fa6a6f. These tests
exercise owner-side run.terminal publication through actual finalization and
confirmed recovery takeover publication.
See backend/docs/RUN_EVENT_STREAM.md for the protocol.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, TypedDict
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.runtime.events.terminal as terminal_module
import deerflow.runtime.runs.worker as worker_module
from deerflow.config.paths import Paths
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.manager import CancelOutcome, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.runtime.stream_bridge import MemoryStreamBridge
from deerflow.runtime.user_context import get_effective_user_id


class RootAgent:
    """Offline graph boundary; lifecycle callbacks and Worker remain real."""

    def __init__(self, *, completions=1, after_graph=None):
        self.completions = completions
        self.after_graph = after_graph

    async def astream(self, graph_input, config=None, **kwargs):
        journal = config["context"]["__run_journal"]
        for invocation in range(self.completions):
            graph_id = uuid4()
            journal.on_chain_start({"name": "offline-graph"}, {}, run_id=graph_id)
            journal.on_chain_end({"invocation": invocation}, run_id=graph_id)
        if self.after_graph is not None:
            await self.after_graph(journal)
        yield {"messages": []}


class RollbackState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def settled(task, *, allow_cancelled=False):
    # Shield the Worker: timeout must not cancel its owned finalizer before
    # the test's finally block has released every storage/producer gate.
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=5)
    except asyncio.CancelledError:
        if not allow_cancelled or not task.cancelled():
            raise


async def terminal_events(runtime, record):
    return await runtime.events.list_events(record.thread_id, record.run_id, event_types=["run.terminal"], user_id=None)


def confirmed_terminal(events, record, status, *, recovered=False):
    assert len(events) == 1, f"expected one authoritative run.terminal({status}), got {events!r}"
    terminal = events[0]
    assert (terminal["thread_id"], terminal["run_id"], terminal["event_type"]) == (record.thread_id, record.run_id, "run.terminal")
    assert terminal["category"] == "trace"
    assert terminal["content"] == {"status": status}
    assert terminal["metadata"]["protocol_version"] == 1
    assert terminal["metadata"]["recovered"] is recovered
    return terminal


async def put_expired_run(runtime, *, operation_kind="run", user_id="alice"):
    run_id = f"recovery-run-{uuid4()}"
    thread_id = f"recovery-thread-{uuid4()}"
    await runtime.runs.put(
        run_id,
        thread_id=thread_id,
        user_id=user_id,
        status="running",
        operation_kind=operation_kind,
        owner_worker_id="dead-owner",
        lease_expires_at=(datetime.now(UTC) - timedelta(seconds=60)).isoformat(),
    )
    return SimpleNamespace(run_id=run_id, thread_id=thread_id, user_id=user_id)


def recovery_manager(runtime, *, worker_id=None):
    return RunManager(
        store=runtime.runs,
        event_store=runtime.events,
        worker_id=worker_id or f"recovery-{uuid4()}",
        run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=300, grace_seconds=0),
    )


@pytest_asyncio.fixture
async def runtime(tmp_path, monkeypatch):
    """Real shared SQLite run/event stores, with bounded owned-task cleanup."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'terminal-protocol.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    events, runs = DbRunEventStore(sf), RunRepository(sf)
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    workers, housekeeping = [], []
    original_create = worker_module._create_contextless_task

    def track_housekeeping(coro):
        task = original_create(coro)
        housekeeping.append(task)
        return task

    monkeypatch.setattr(worker_module, "_create_contextless_task", track_housekeeping)

    async def start(*, agent=None, completion_hook=None, checkpointer=None, before_start=None, graph_input=None, heartbeat_enabled=True, user_id=None, event_store=None):
        selected_events = event_store if event_store is not None else events
        manager = RunManager(
            store=runs,
            event_store=selected_events,
            worker_id=f"terminal-owner-{uuid4()}",
            run_ownership_config=RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled, lease_seconds=300, grace_seconds=0),
        )
        record = await manager.create_or_reject(f"terminal-thread-{uuid4()}", user_id=user_id)
        if before_start is not None:
            await before_start(record)
        bridge = MemoryStreamBridge()
        graph = agent if agent is not None else RootAgent()
        task = asyncio.create_task(
            run_agent(
                bridge,
                manager,
                record,
                ctx=RunContext(checkpointer=checkpointer, event_store=selected_events, on_run_completed=completion_hook),
                agent_factory=lambda **kwargs: graph,
                graph_input=graph_input or {},
                config={"configurable": {"thread_id": record.thread_id}},
            )
        )
        record.task = task
        workers.append(task)
        return SimpleNamespace(task=task, manager=manager, record=record, bridge=bridge)

    try:
        yield SimpleNamespace(sf=sf, events=events, runs=runs, paths=paths, start=start)
    finally:
        # Individual tests release their gates before this fallback cleanup.
        for task in workers:
            if not task.done():
                task.cancel()
        if workers:
            await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), timeout=5)
        for task in housekeeping:
            task.cancel()
        await asyncio.gather(*housekeeping, return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_root_completions_keep_legacy_outputs_and_one_terminal(runtime):
    """Catches graph completion being substituted for the final Run result."""
    run = await runtime.start(agent=RootAgent(completions=2))
    await settled(run.task)
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    events = await runtime.events.list_events(run.record.thread_id, run.record.run_id)
    assert row["status"] == "success"
    assert run.manager._has_final_terminal_ack(run.record)
    assert len([event for event in events if event["event_type"] == "run.start"]) == 2
    legacy = [event for event in events if event["event_type"] == "run.end"]
    assert [event["content"] for event in legacy] == [{"invocation": 0}, {"invocation": 1}]
    assert all(event["category"] == "outputs" and event["metadata"]["status"] == "success" for event in legacy)
    confirmed_terminal(await terminal_events(runtime, run.record), run.record, "success")


@pytest.mark.asyncio
async def test_graph_success_before_failed_artifact_delivery_has_error_terminal(runtime, monkeypatch):
    """Catches terminal success published before real output verification."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = worker_module._produced_output_paths
    output_dir = None

    async def prepare(record):
        nonlocal output_dir
        output_dir = runtime.paths.sandbox_outputs_dir(record.thread_id, user_id=get_effective_user_id())
        output_dir.mkdir(parents=True)

    async def produce(journal):
        await journal.flush()
        await asyncio.to_thread((output_dir / "report.md").write_text, "report\n", encoding="utf-8")

    async def verify(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(worker_module, "_produced_output_paths", verify)
    run = await runtime.start(agent=RootAgent(after_graph=produce), before_start=prepare)
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        legacy = await runtime.events.list_events(run.record.thread_id, run.record.run_id, event_types=["run.end"])
        assert len(legacy) == 1 and legacy[0]["metadata"]["status"] == "success"
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["status"] == "running"
        assert not await terminal_events(runtime, run.record)
    finally:
        release.set()
        await settled(run.task)
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["status"] == "error"
    assert row["error"] == "Artifact delivery incomplete: no produced output artifact was presented"
    delivery = await runtime.events.list_events(run.record.thread_id, run.record.run_id, event_types=["run.delivery"])
    assert delivery[0]["content"]["produced_paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery[0]["content"]["satisfied"] is False
    confirmed_terminal(await terminal_events(runtime, run.record), run.record, "error")


@pytest.mark.asyncio
async def test_peer_takeover_rejects_old_owner_and_healthy_owner_publishes(runtime, monkeypatch):
    """Catches publication on rejected CAS; healthy control prevents vacuity."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.runs.finalize_if_not_cancelled

    async def gated_cas(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.runs, "finalize_if_not_cancelled", gated_cas)
    run = await runtime.start()
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["status"] == "running"
        assert run.record.terminal_commit_proof is None
        expired = datetime.now(UTC) - timedelta(seconds=60)
        async with runtime.sf() as session:
            await session.execute(update(RunRow).where(RunRow.run_id == run.record.run_id).values(lease_expires_at=expired))
            await session.commit()
        run.record.lease_expires_at = expired.isoformat()
        assert await runtime.runs.claim_for_takeover(run.record.run_id, grace_seconds=0, error="peer takeover", stop_reason="orphan_recovered")
    finally:
        release.set()
        await settled(run.task, allow_cancelled=True)
    assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["error"] == "peer takeover"
    assert run.record.ownership_lost
    assert run.record.terminal_commit_proof is None
    assert not await terminal_events(runtime, run.record)
    healthy = await runtime.start()
    await settled(healthy.task)
    assert healthy.manager._has_final_terminal_ack(healthy.record)
    confirmed_terminal(await terminal_events(runtime, healthy.record), healthy.record, "success")


@pytest.mark.asyncio
async def test_rollback_intermediate_ack_waits_for_restoration_and_final_error(runtime, monkeypatch):
    """Catches interrupted ACK being published while rollback is unfinished."""
    executing, restoring, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    saver = InMemorySaver()
    restored = []

    async def work(_state):
        executing.set()
        await asyncio.Event().wait()
        return {"messages": []}

    builder = StateGraph(RollbackState)
    builder.add_node("work", work)
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    graph = builder.compile(checkpointer=saver)
    original = worker_module._rollback_to_pre_run_checkpoint

    async def gated_restore(**kwargs):
        restoring.set()
        await release.wait()
        result = await original(**kwargs)
        restored.append(result)
        return result

    async def seed(record):
        await graph.aupdate_state({"configurable": {"thread_id": record.thread_id}}, {"messages": [HumanMessage(content="original", id="before")]}, as_node="work")

    monkeypatch.setattr(worker_module, "_rollback_to_pre_run_checkpoint", gated_restore)
    run = await runtime.start(agent=graph, checkpointer=saver, before_start=seed, graph_input={"messages": [HumanMessage(content="abandoned", id="during")]})
    try:
        await asyncio.wait_for(executing.wait(), timeout=5)
        assert await run.manager.cancel(run.record.run_id, action="rollback") == CancelOutcome.cancelled
        await asyncio.wait_for(restoring.wait(), timeout=5)
        assert run.record.terminal_commit_proof.status == RunStatus.interrupted
        assert run.record.rollback_finalization_pending
        assert not run.manager._has_final_terminal_ack(run.record)
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["status"] == "interrupted"
        assert not await terminal_events(runtime, run.record)
    finally:
        release.set()
        await settled(run.task)
    assert restored == [True]
    snapshot = await graph.aget_state({"configurable": {"thread_id": run.record.thread_id}})
    assert [(message.id, message.content) for message in snapshot.values["messages"]] == [("before", "original")]
    assert run.manager._has_final_terminal_ack(run.record)
    assert run.record.terminal_commit_proof.status == RunStatus.error
    assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["status"] == "error"
    confirmed_terminal(await terminal_events(runtime, run.record), run.record, "error")


@pytest.mark.asyncio
async def test_unknown_journal_write_blocks_complete_tail_with_healthy_control(runtime, monkeypatch):
    """Catches a terminal/complete seal overtaking an UNKNOWN predecessor."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.events.put_batch
    attempts = []

    async def commit_then_lose_ack(batch):
        result = await original(batch)
        if any(event["event_type"] == "middleware:unknown" for event in batch):
            attempts.append(batch)
            entered.set()
            await release.wait()
            raise OSError("Journal commit acknowledgement lost")
        return result

    async def unknown_callback(journal):
        journal.record_middleware("unknown", name="unknown", hook="test", action="accepted", changes={})

    monkeypatch.setattr(runtime.events, "put_batch", commit_then_lose_ack)
    run = await runtime.start(agent=RootAgent(after_graph=unknown_callback))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        persisted = await runtime.events.list_events(run.record.thread_id, run.record.run_id)
        assert any(event["event_type"] == "middleware:unknown" for event in persisted)
        assert not await terminal_events(runtime, run.record)
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["evidence_seal_state"] != "sealed"
    finally:
        release.set()
        await settled(run.task)
    assert len(attempts) == 1, "an ambiguously committed batch must never be replayed"
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["status"] == "success", "evidence failure must not rewrite business success"
    assert row["evidence_seal_state"] == "partial"
    assert not await terminal_events(runtime, run.record)
    healthy = await runtime.start()
    await settled(healthy.task)
    confirmed_terminal(await terminal_events(runtime, healthy.record), healthy.record, "success")


@pytest.mark.asyncio
async def test_admitted_cross_thread_callback_precedes_terminal_after_freeze(runtime, monkeypatch):
    """Catches terminal publication overtaking an admitted queued callback."""
    freezing = asyncio.Event()
    loop = asyncio.get_running_loop()
    original_schedule = loop.call_soon_threadsafe
    original_stop = RunJournal._stop_evidence_producers
    held, journals, threads = [], [], []
    holding = True
    held_lock = threading.Lock()

    def hold_callback(callback, *args, context=None):
        method = getattr(callback, "func", None)
        with held_lock:
            if holding and journals and getattr(method, "__self__", None) is journals[0] and getattr(method, "__name__", None) == "_record_admitted_middleware":
                held.append((callback, args, context))
                return None
        return original_schedule(callback, *args, context=context)

    async def stop(journal):
        if journals and journal is journals[0]:
            freezing.set()
        await original_stop(journal)

    async def completion(_record):
        # The hook itself is a legitimate evidence producer before freeze.
        journal = journals[0]
        thread = threading.Thread(target=lambda: journal.record_middleware("accepted", name="accepted", hook="stop", action="done", changes={}))
        threads.append(thread)
        thread.start()
        await asyncio.to_thread(thread.join, 2)

    async def capture(journal):
        journals.append(journal)

    def release_callback():
        nonlocal holding
        with held_lock:
            holding = False
            callbacks = held[:]
            held.clear()
        for callback, args, context in callbacks:
            original_schedule(callback, *args, context=context)

    monkeypatch.setattr(loop, "call_soon_threadsafe", hold_callback)
    monkeypatch.setattr(RunJournal, "_stop_evidence_producers", stop)
    run = await runtime.start(agent=RootAgent(after_graph=capture), completion_hook=completion)
    try:
        await asyncio.wait_for(freezing.wait(), timeout=5)
        assert not threads[0].is_alive()
        assert len(held) == 1
        assert journals[0]._pending_producer_callbacks == 1
        assert not journals[0]._accepting_evidence
        assert not await terminal_events(runtime, run.record)
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["evidence_seal_state"] == "pending"
    finally:
        release_callback()
        await settled(run.task)
        for thread in threads:
            await asyncio.to_thread(thread.join, 2)
    events = await runtime.events.list_events(run.record.thread_id, run.record.run_id)
    accepted = [event for event in events if event["event_type"] == "middleware:accepted"]
    assert len(accepted) == 1
    terminal = confirmed_terminal(await terminal_events(runtime, run.record), run.record, "success")
    assert accepted[0]["seq"] < terminal["seq"]


@pytest.mark.asyncio
async def test_confirmed_terminal_is_inside_original_receipt_and_seal(runtime, monkeypatch):
    """Catches Receipt before terminal ACK or terminal append after Receipt."""
    entered, release = asyncio.Event(), asyncio.Event()
    terminal_written, acknowledge = asyncio.Event(), asyncio.Event()
    receipt_started = asyncio.Event()
    original = runtime.events.evidence_receipt
    original_put = runtime.events.put_if_absent
    receipts, boundary_events, terminal_results = [], [], []

    async def hold_terminal_ack(**kwargs):
        result = await original_put(**kwargs)
        if kwargs["event_type"] == "run.terminal":
            terminal_results.append(result)
            terminal_written.set()
            await acknowledge.wait()
        return result

    async def capture_receipt(thread_id, run_id):
        receipt_started.set()
        receipt = await original(thread_id, run_id)
        receipts.append(receipt)
        boundary_events.extend(await runtime.events.list_events(thread_id, run_id))
        entered.set()
        await release.wait()
        return receipt

    monkeypatch.setattr(runtime.events, "evidence_receipt", capture_receipt)
    monkeypatch.setattr(runtime.events, "put_if_absent", hold_terminal_ack)
    run = await runtime.start()
    ack_boundary = asyncio.create_task(terminal_written.wait())
    receipt_boundary = asyncio.create_task(entered.wait())
    try:
        # Upstream has no publisher, so it reaches Receipt directly. Observe
        # that boundary too instead of timing out waiting for a nonexistent API.
        done, _ = await asyncio.wait({ack_boundary, receipt_boundary, run.task}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert done, "Worker never reached either terminal write or Receipt"
        if terminal_written.is_set():
            assert not receipt_started.is_set(), "Receipt started while terminal write ACK was still withheld"
            assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["evidence_seal_state"] == "pending"
            assert not receipt_started.is_set(), "Receipt started while terminal write ACK was still withheld"
            acknowledge.set()
        await asyncio.wait_for(asyncio.shield(receipt_boundary), timeout=5)
        assert run.manager._has_final_terminal_ack(run.record)
        assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["evidence_seal_state"] == "pending"
    finally:
        acknowledge.set()
        release.set()
        try:
            await settled(run.task)
        finally:
            ack_boundary.cancel()
            receipt_boundary.cancel()
            await asyncio.gather(ack_boundary, receipt_boundary, return_exceptions=True)
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["evidence_seal_state"] == "sealed"
    assert len(receipts) == 1
    receipt = receipts[0]
    assert row["evidence_upper_seq"] == receipt.upper_event_seq
    assert row["evidence_event_count"] == receipt.event_count == len(boundary_events)
    terminal = confirmed_terminal([event for event in boundary_events if event["event_type"] == "run.terminal"], run.record, "success")
    assert len(terminal_results) == 1, "terminal evidence must use the run-scoped singleton confirmation"
    assert terminal_results[0][0] == terminal
    assert terminal["seq"] <= receipt.upper_event_seq
    assert terminal == (await terminal_events(runtime, run.record))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "jsonl", "sqlite"])
@pytest.mark.parametrize("heartbeat_enabled", [False, True])
async def test_terminal_publication_supports_default_and_owned_workers(runtime, tmp_path, backend, heartbeat_enabled):
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    stores = {"memory": MemoryRunEventStore(), "jsonl": JsonlRunEventStore(base_dir=tmp_path / "events"), "sqlite": runtime.events}
    store = stores[backend]
    run = await runtime.start(event_store=store, heartbeat_enabled=heartbeat_enabled, user_id="alice")
    await settled(run.task)
    events = await store.list_events(run.record.thread_id, run.record.run_id, event_types=["run.terminal"], user_id="alice")
    terminal = confirmed_terminal(events, run.record, "success")
    if backend == "sqlite":
        assert terminal["user_id"] == "alice"
        assert not await store.list_events(run.record.thread_id, run.record.run_id, event_types=["run.terminal"], user_id="bob")


@pytest.mark.asyncio
async def test_terminal_ack_loss_confirms_existing_without_duplicate(runtime, monkeypatch):
    original = runtime.events.put_if_absent
    results = []

    async def lose_first_ack(**kwargs):
        result = await original(**kwargs)
        if kwargs["event_type"] == "run.terminal":
            results.append(result)
            if len(results) == 1:
                raise OSError("Terminal commit acknowledgement lost")
        return result

    monkeypatch.setattr(runtime.events, "put_if_absent", lose_first_ack)
    run = await runtime.start()
    await settled(run.task)
    terminal = confirmed_terminal(await terminal_events(runtime, run.record), run.record, "success")
    assert len(results) == 2
    assert results[0] == (terminal, True)
    assert results[1] == (terminal, False)
    assert (await runtime.runs.get(run.record.run_id, user_id=run.record.user_id))["evidence_seal_state"] == "sealed"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("status", "error"), ("protocol_version", 2), ("protocol_version", True), ("category", "outputs"), ("recovered", "false"), ("user_id", "bob")])
async def test_conflicting_terminal_preserves_record_and_business_status(runtime, field, value):
    existing = []

    async def seed(record):
        event = dict(thread_id=record.thread_id, run_id=record.run_id, event_type="run.terminal", category="trace", content={"status": "success"}, metadata={"protocol_version": 1, "recovered": False}, user_id="alice")
        if field == "status":
            event["content"][field] = value
        elif field in ("protocol_version", "recovered"):
            event["metadata"][field] = value
        else:
            event[field] = value
        existing.extend(await runtime.events.put_batch([event]))

    run = await runtime.start(before_start=seed, user_id="alice")
    await settled(run.task)
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["status"] == "success"
    assert row["evidence_seal_state"] == "partial"
    assert "CONFLICT" in row["evidence_seal_error"]
    assert await terminal_events(runtime, run.record) == existing
    assert run.bridge._streams[run.record.run_id].ended
    replacement = await run.manager.create_or_reject(run.record.thread_id, user_id="alice")
    assert replacement.run_id != run.record.run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "cancelled", "malformed"])
async def test_unconfirmed_terminal_does_not_seal_or_block_stream_end(runtime, monkeypatch, failure):
    original = runtime.events.put_if_absent
    attempts = []

    async def fail_terminal(**kwargs):
        if kwargs["event_type"] == "run.terminal":
            attempts.append(kwargs)
            if failure == "unknown":
                raise OSError("Terminal write unavailable")
            if failure == "cancelled":
                raise asyncio.CancelledError()
            return None
        return await original(**kwargs)

    monkeypatch.setattr(runtime.events, "put_if_absent", fail_terminal)
    run = await runtime.start()
    try:
        await settled(run.task, allow_cancelled=True)
    finally:
        assert run.task.done()
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["status"] == "success"
    assert row["evidence_seal_state"] == "partial"
    assert row["evidence_seal_error"]
    assert not await terminal_events(runtime, run.record)
    assert run.bridge._streams[run.record.run_id].ended
    assert len(attempts) == (2 if failure == "unknown" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", [False, None])
async def test_matching_terminal_row_without_commit_ack_cannot_authorize_event(runtime, monkeypatch, ack):
    original = runtime.runs.update_status

    async def lose_terminal_ack(run_id, status, **kwargs):
        result = await original(run_id, status, **kwargs)
        return ack if status in ("success", "error", "interrupted", "timeout") else result

    monkeypatch.setattr(runtime.runs, "update_status", lose_terminal_ack)
    run = await runtime.start(heartbeat_enabled=False)
    await settled(run.task)
    row = await runtime.runs.get(run.record.run_id, user_id=run.record.user_id)
    assert row["status"] == "success"
    assert not run.manager._has_final_terminal_ack(run.record)
    assert not await terminal_events(runtime, run.record)
    assert row["evidence_seal_state"] == "partial"
    assert row["evidence_seal_error"] == "Terminal event lacks an attributable final commit ACK"


@pytest.mark.asyncio
@pytest.mark.parametrize("heartbeat_enabled", [False, True])
@pytest.mark.parametrize("status", [RunStatus.error, RunStatus.interrupted, RunStatus.timeout])
async def test_process_local_terminal_proof_allows_later_staged_outcome(heartbeat_enabled, status):
    manager = RunManager(run_ownership_config=RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled))
    record = await manager.create_or_reject("local-terminal")
    await manager.set_status(record.run_id, RunStatus.success)
    assert manager.terminal_event_status(record) == "success"

    await manager.set_status(record.run_id, status, error="Later terminal outcome", persist=False)
    assert record.status == status
    assert record.error == "Later terminal outcome"
    assert manager.terminal_event_status(record) is None

    assert await manager.persist_current_status(record.run_id)
    assert record.status == status
    assert manager.terminal_event_status(record) == status.value


@pytest.mark.asyncio
@pytest.mark.no_auto_user
async def test_orphan_recovery_claim_backfills_error_terminal(runtime):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    confirmed_terminal(await terminal_events(runtime, record), record, "error", recovered=True)


@pytest.mark.asyncio
async def test_losing_orphan_recovery_claim_does_not_publish_terminal(runtime, monkeypatch):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)
    original_scan = runtime.runs.list_inflight_with_expired_lease

    async def stale_scan_then_owner_renews(**kwargs):
        rows = await original_scan(**kwargs)
        async with runtime.sf() as session:
            await session.execute(update(RunRow).where(RunRow.run_id == record.run_id).values(lease_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat()))
            await session.commit()
        return rows

    monkeypatch.setattr(runtime.runs, "list_inflight_with_expired_lease", stale_scan_then_owner_renews)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="must not win",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert recovered == []
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "running"
    assert await terminal_events(runtime, record) == []


@pytest.mark.asyncio
async def test_non_local_cancel_takeover_backfills_error_terminal(runtime):
    record = await put_expired_run(runtime, user_id=get_effective_user_id())
    manager = recovery_manager(runtime)

    outcome = await manager.cancel(record.run_id)

    assert outcome == CancelOutcome.taken_over
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    delivery = await runtime.events.list_events(record.thread_id, record.run_id, event_types=["run.delivery"], user_id=None)
    terminal = await terminal_events(runtime, record)
    assert len(delivery) == 1
    confirmed_terminal(terminal, record, "error", recovered=True)
    assert delivery[0]["seq"] < terminal[0]["seq"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["event_store", "unexpected"])
async def test_non_local_cancel_returns_taken_over_when_terminal_publish_fails(runtime, monkeypatch, failure):
    record = await put_expired_run(runtime, user_id=get_effective_user_id())
    manager = recovery_manager(runtime)
    attempts = []
    if failure == "event_store":
        original = runtime.events.put_if_absent

        async def fail_terminal(**kwargs):
            if kwargs["event_type"] == "run.terminal":
                attempts.append(kwargs)
                raise OSError("terminal event unavailable")
            return await original(**kwargs)

        monkeypatch.setattr(runtime.events, "put_if_absent", fail_terminal)
    else:

        async def fail_confirmation(*args, **kwargs):
            raise RuntimeError("unexpected confirmation failure")

        monkeypatch.setattr(terminal_module, "confirm_terminal_event", fail_confirmation)

    outcome = await manager.cancel(record.run_id)

    assert outcome == CancelOutcome.taken_over
    assert len(attempts) == (2 if failure == "event_store" else 0)
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    assert row["evidence_seal_state"] == "partial"
    assert await terminal_events(runtime, record) == []


@pytest.mark.asyncio
async def test_non_run_takeover_claim_does_not_publish_terminal(runtime):
    record = await put_expired_run(runtime, operation_kind="checkpoint_write")
    manager = recovery_manager(runtime)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="checkpoint write recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert recovered == []
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    assert await terminal_events(runtime, record) == []


@pytest.mark.asyncio
async def test_concurrent_orphan_recovery_only_winner_publishes_terminal(runtime):
    record = await put_expired_run(runtime)
    managers = [recovery_manager(runtime), recovery_manager(runtime)]

    results = await asyncio.gather(
        *(
            manager.reconcile_orphaned_inflight_runs(
                error="orphan recovered",
                before=datetime.now(UTC).isoformat(),
                stop_reason="orphan_recovered",
            )
            for manager in managers
        )
    )

    assert sum(len(recovered) for recovered in results) == 1
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    confirmed_terminal(await terminal_events(runtime, record), record, "error", recovered=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "conflict", "lost_ack"])
async def test_recovery_terminal_failure_never_changes_committed_takeover(runtime, monkeypatch, failure):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)
    attempts = []
    existing = None
    if failure == "conflict":
        existing = await runtime.events.put(
            thread_id=record.thread_id,
            run_id=record.run_id,
            event_type="run.terminal",
            category="trace",
            content={"status": "success"},
            metadata={"protocol_version": 1, "recovered": False},
        )
    original = runtime.events.put_if_absent

    async def fail_terminal(**kwargs):
        nonlocal existing
        if kwargs["event_type"] != "run.terminal":
            return await original(**kwargs)
        if failure == "unknown":
            attempts.append(kwargs)
            raise OSError("terminal store unavailable")
        if failure == "lost_ack":
            result = await original(**kwargs)
            attempts.append(result)
            if len(attempts) == 1:
                raise OSError("terminal ACK lost after commit")
            return result
        return await original(**kwargs)

    monkeypatch.setattr(runtime.events, "put_if_absent", fail_terminal)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None
    assert row["status"] == "error"
    assert row["evidence_seal_state"] == "partial"
    terminal = await terminal_events(runtime, record)
    if failure == "unknown":
        assert len(attempts) == 2
        assert terminal == []
    elif failure == "conflict":
        assert terminal == [existing]
    else:
        assert len(attempts) == 2
        confirmed_terminal(terminal, record, "error", recovered=True)


@pytest.mark.asyncio
async def test_orphan_recovery_unexpected_publisher_error_preserves_recovery_flow(runtime, monkeypatch):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)

    async def fail_confirmation(*args, **kwargs):
        raise RuntimeError("unexpected confirmation failure")

    monkeypatch.setattr(terminal_module, "confirm_terminal_event", fail_confirmation)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    row = await runtime.runs.get(record.run_id, user_id=record.user_id)
    assert row is not None and row["status"] == "error"
    assert row["evidence_seal_state"] == "partial"
    assert await terminal_events(runtime, record) == []
    delivery = await runtime.events.list_events(record.thread_id, record.run_id, event_types=["run.delivery"], user_id=None)
    assert len(delivery) == 1


@pytest.mark.asyncio
async def test_recovery_publication_cannot_resurrect_deleted_thread(runtime, monkeypatch):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)
    publishing, release = asyncio.Event(), asyncio.Event()
    original_confirm = terminal_module.confirm_terminal_event

    async def pause_before_event_write(*args, **kwargs):
        publishing.set()
        await release.wait()
        return await original_confirm(*args, **kwargs)

    monkeypatch.setattr(terminal_module, "confirm_terminal_event", pause_before_event_write)
    recovery = asyncio.create_task(
        manager.reconcile_orphaned_inflight_runs(
            error="orphan recovered",
            before=datetime.now(UTC).isoformat(),
            stop_reason="orphan_recovered",
        )
    )
    try:
        await asyncio.wait_for(publishing.wait(), timeout=5)
        await runtime.runs.delete_by_thread(record.thread_id, user_id=record.user_id)
        await runtime.events.delete_by_thread(record.thread_id, user_id=record.user_id)
    finally:
        release.set()
    recovered = await asyncio.wait_for(recovery, timeout=5)

    assert [run.run_id for run in recovered] == [record.run_id]
    assert await runtime.runs.get(record.run_id, user_id=record.user_id) is None
    assert await runtime.events.list_events(record.thread_id, record.run_id, user_id=None) == []
    assert await runtime.events.list_messages(record.thread_id, user_id=None) == []


@pytest.mark.asyncio
async def test_recovery_delivery_receipt_precedes_terminal(runtime):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    delivery = await runtime.events.list_events(record.thread_id, record.run_id, event_types=["run.delivery"], user_id=None)
    terminal = await terminal_events(runtime, record)
    assert len(delivery) == 1
    assert delivery[0]["user_id"] == record.user_id
    confirmed_terminal(terminal, record, "error", recovered=True)
    assert delivery[0]["seq"] < terminal[0]["seq"]


@pytest.mark.asyncio
async def test_recovery_delivery_receipt_failure_does_not_block_terminal(runtime, monkeypatch):
    record = await put_expired_run(runtime)
    manager = recovery_manager(runtime)
    original = runtime.events.put_if_absent

    async def fail_delivery(**kwargs):
        if kwargs["event_type"] == "run.delivery":
            raise OSError("delivery receipt unavailable")
        return await original(**kwargs)

    monkeypatch.setattr(runtime.events, "put_if_absent", fail_delivery)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    assert await runtime.events.list_events(record.thread_id, record.run_id, event_types=["run.delivery"], user_id=None) == []
    confirmed_terminal(await terminal_events(runtime, record), record, "error", recovered=True)


@pytest.mark.asyncio
async def test_recovery_accepts_existing_owner_terminal_without_rewriting_source(runtime):
    record = await put_expired_run(runtime)
    owner_event, created = await runtime.events.put_if_absent(
        thread_id=record.thread_id,
        run_id=record.run_id,
        event_type="run.terminal",
        category="trace",
        content={"status": "error"},
        metadata={"protocol_version": 1, "recovered": False},
        user_id=record.user_id,
    )
    assert created is True
    manager = recovery_manager(runtime)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="orphan recovered",
        before=datetime.now(UTC).isoformat(),
        stop_reason="orphan_recovered",
    )

    assert [run.run_id for run in recovered] == [record.run_id]
    terminal = await terminal_events(runtime, record)
    assert terminal == [owner_event]
    assert terminal[0]["metadata"]["recovered"] is False
