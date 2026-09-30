from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


@pytest_asyncio.fixture
async def evidence(tmp_path):
    from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    events = DbRunEventStore(sf)
    runs = RunRepository(sf)
    reader = HostCompletedRunEvidenceReader(runs, events, plugin_id="test", owner_ids=frozenset({"alice"}))
    yield sf, events, runs, reader
    await engine.dispose()


async def put_run(runs, run_id="r", *, owner="alice", status="success", **kwargs):
    await runs.put(run_id, thread_id=f"t-{run_id}", user_id=owner, assistant_id="routing-alias", evidence_agent_id="stable-agent", status=status, **kwargs)


async def put_event(events, run_id="r", content="hello", owner="alice"):
    return await events.put_batch([dict(thread_id=f"t-{run_id}", run_id=run_id, user_id=owner, event_type="test", category="message", content=content)])


@pytest.mark.asyncio
async def test_source_fence_metadata_has_explicit_accessors(evidence):
    sf, _events, runs, reader = evidence
    await put_run(runs)
    snapshot = await reader.get_snapshot(thread_id="t-r", run_id="r")
    async with sf() as session:
        run = await session.scalar(select(RunRow).where(RunRow.run_id == "r"))
    assert len(reader.scope_digest) == 64
    assert reader.revision_for_run(run) == snapshot.evidence_revision


@pytest.mark.asyncio
async def test_new_giant_digest_has_constant_read_queries(evidence):
    sf, events, runs, reader = evidence
    await put_run(runs)
    content = "x" * (16 * 1024 * 1024)
    await put_event(events, content=content)
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    queries = []
    engine = sf.kw["bind"].sync_engine

    def track(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track)
    try:
        page = await reader.read_events(snapshot_ref=snap.snapshot_ref)
    finally:
        event.remove(engine, "before_cursor_execute", track)
    assert page.items[0].content_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert len(queries) <= 6


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes", [[1024 * 1024 + 1], [600 * 1024, 600 * 1024]])
async def test_legacy_digest_budget_is_cumulative_and_never_trusts_metadata(evidence, sizes):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs)
    async with sf() as session:
        session.add_all([RunEventRow(thread_id="t-r", run_id="r", user_id="alice", event_type="test", category="message", content="x" * size, event_metadata={"content_sha256": "fake"}, seq=i + 1) for i, size in enumerate(sizes)])
        await session.commit()
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    queries = []
    engine = sf.kw["bind"].sync_engine

    def track(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track)
    try:
        with pytest.raises(HostCapabilityError, match="LIMIT_EXCEEDED"):
            await reader.read_events(snapshot_ref=snap.snapshot_ref)
    finally:
        event.remove(engine, "before_cursor_execute", track)
    assert len(queries) <= 72


@pytest.mark.asyncio
async def test_legacy_digest_within_budget_is_exact(evidence):
    sf, events, runs, reader = evidence
    await put_run(runs)
    content = "中\x00" * 10000
    async with sf() as session:
        session.add(RunEventRow(thread_id="t-r", run_id="r", user_id="alice", event_type="test", category="message", content=content, seq=1))
        await session.commit()
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    from deerflow_extension_api.completed_run_evidence import EvidenceLimits

    page = await reader.read_events(snapshot_ref=snap.snapshot_ref, limits=EvidenceLimits(max_bytes=1024))
    assert page.items[0].content_sha256 == hashlib.sha256(content.encode()).hexdigest()


@pytest.mark.asyncio
async def test_legacy_digest_deadline_interrupts_query_wait(evidence, monkeypatch):
    import asyncio

    from deerflow_extension_api.host_capabilities import HostCapabilityError
    from sqlalchemy.ext.asyncio import AsyncSession

    from deerflow.extensions import completed_run_evidence as module

    sf, events, runs, reader = evidence
    await put_run(runs)
    async with sf() as session:
        session.add(RunEventRow(thread_id="t-r", run_id="r", user_id="alice", event_type="test", category="message", content="x" * 200000, seq=1))
        await session.commit()
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    clock = iter([0, 1.999])
    monkeypatch.setattr(module, "monotonic", lambda: next(clock))
    original = AsyncSession.scalar

    async def delayed(session, statement, *args, **kwargs):
        if "substr(" in str(statement):
            await asyncio.sleep(0.02)
        return await original(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", delayed)
    with pytest.raises(HostCapabilityError, match="LIMIT_EXCEEDED.*deadline"):
        await reader.read_events(snapshot_ref=snap.snapshot_ref)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
async def test_ingestion_digest_is_of_persisted_truncated_serialization(evidence, method):
    sf, events, runs, reader = evidence
    payload = dict(thread_id="t-r", run_id="r", event_type="test", category="trace", content={"text": "中" * 20000})
    if method == "put_batch":
        await events.put_batch([payload])
    else:
        await getattr(events, method)(**payload)
    async with sf() as session:
        row = await session.scalar(select(RunEventRow))
        assert getattr(row, "content_sha256", None) == hashlib.sha256(row.content.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_thread_snapshot_cleanup_locks_runs_in_prior_statement(evidence):
    sf, events, runs, reader = evidence
    await put_run(runs)
    await reader.get_snapshot(thread_id="t-r", run_id="r")
    statements = []
    engine = sf.kw["bind"].sync_engine

    def track(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", track)
    try:
        await runs.delete_by_thread("t-r", user_id="alice")
    finally:
        event.remove(engine, "before_cursor_execute", track)
    lock_indices = [i for i, statement in enumerate(statements) if statement.startswith("SELECT") and "runs.run_id" in statement]
    assert lock_indices, "run locks must be acquired in their own statement"
    cleanup_index = next(i for i, statement in enumerate(statements) if statement.startswith("DELETE FROM completed_run_snapshots"))
    assert lock_indices[0] < cleanup_index


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["run", "thread", "run_events", "thread_events"])
async def test_snapshot_cleanup_is_owner_scoped(evidence, operation):
    from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader

    sf, events, runs, reader = evidence
    await put_run(runs)
    await runs.put("b", thread_id="t-r", user_id="bob", status="success")
    bob = HostCompletedRunEvidenceReader(runs, events, plugin_id="test", owner_ids={"bob"})
    alice_snapshot = await reader.get_snapshot(thread_id="t-r", run_id="r")
    bob_snapshot = await bob.get_snapshot(thread_id="t-r", run_id="b")

    async def remove(owner):
        if operation == "run":
            await runs.delete("r", user_id=owner)
        elif operation == "thread":
            await runs.delete_by_thread("t-r", user_id=owner)
        elif operation == "run_events":
            await events.delete_by_run("t-r", "r", user_id=owner)
        else:
            await events.delete_by_thread("t-r", user_id=owner)

    await remove("mallory")
    async with sf() as session:
        assert set(await session.scalars(select(CompletedRunSnapshotRow.snapshot_ref))) == {alice_snapshot.snapshot_ref, bob_snapshot.snapshot_ref}
    await remove("alice")
    async with sf() as session:
        assert set(await session.scalars(select(CompletedRunSnapshotRow.snapshot_ref))) == {bob_snapshot.snapshot_ref}


def test_new_dtos_detach_mutable_constructor_sequences():
    from deerflow_extension_api.completed_run_evidence import CompletedRunEventPage, CompletedRunSnapshot

    notes = ["limited"]
    items = []
    snapshot = CompletedRunSnapshot(coverage_limits=notes, skill_observations=notes)
    page = CompletedRunEventPage(items=items)
    notes.append("changed")
    items.append("changed")
    assert snapshot.coverage_limits == ("limited",)
    assert snapshot.skill_observations == ("limited",)
    assert page.items == ()


@pytest.mark.asyncio
async def test_scope_filters_before_pagination_and_cursor_binds_plugin(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader

    sf, events, runs, reader = evidence
    await put_run(runs, "other", owner="bob")
    await put_run(runs, "a")
    await put_run(runs, "b")
    first = await reader.list_changed_runs(cursor=None, limit=1)
    assert [r.run_id for r in first.items] == ["a"]
    assert first.has_more
    await runs.update_model_name("a", "changed")
    second = await reader.list_changed_runs(cursor=first.next_cursor, limit=10)
    assert [r.run_id for r in second.items] == ["b", "a"]
    peer = HostCompletedRunEvidenceReader(runs, events, plugin_id="other", owner_ids={"alice"})
    with pytest.raises(HostCapabilityError, match="INVALID_CURSOR"):
        await peer.list_changed_runs(cursor=first.next_cursor, limit=1)
    with pytest.raises(HostCapabilityError, match="NOT_FOUND"):
        await reader.get_snapshot(thread_id="t-other", run_id="other")


@pytest.mark.parametrize("owners", [None, set(), {None}, {"*"}, {""}])
def test_explicit_owner_scope_is_required(owners):
    from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader

    with pytest.raises(ValueError):
        HostCompletedRunEvidenceReader(None, MemoryRunEventStore(), plugin_id="test", owner_ids=owners)


@pytest.mark.asyncio
async def test_unsupported_is_explicit():
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader

    reader = HostCompletedRunEvidenceReader(None, MemoryRunEventStore(), plugin_id="test", owner_ids={"alice"})
    with pytest.raises(HostCapabilityError, match="UNSUPPORTED"):
        await reader.list_changed_runs(cursor=None, limit=1)


@pytest.mark.asyncio
async def test_snapshot_fixed_boundaries_and_retention_invalidation(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs)
    await put_event(events, content={"text": "first"})
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    assert snap.owner_id == "alice"
    assert snap.agent_id == "stable-agent"
    assert snap.origin == "unknown"
    assert snap.status == "success"
    assert snap.seal_state == "partial"
    assert snap.coverage == "lead-journal-v1"
    assert snap.coverage_limits
    assert snap.event_count == 1
    assert (await reader.get_snapshot(thread_id="t-r", run_id="r")).snapshot_ref == snap.snapshot_ref
    await put_event(events, content="late")
    page = await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None)
    assert len(page.items) == 1
    assert not page.has_more
    assert json.loads(page.items[0].content_json) == {"text": "first"}
    with pytest.raises(FrozenInstanceError):
        snap.owner_id = "bob"
    await events.delete_by_run("t-r", "r", user_id="alice")
    await put_event(events, content="replacement")
    with pytest.raises(HostCapabilityError, match="NOT_FOUND"):
        await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None)


@pytest.mark.asyncio
async def test_every_page_reauthorizes_current_owner(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs)
    await put_event(events)
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    async with sf() as session:
        await session.execute(update(RunRow).where(RunRow.run_id == "r").values(user_id="bob"))
        await session.commit()
    with pytest.raises(HostCapabilityError, match="NOT_FOUND"):
        await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None)


@pytest.mark.asyncio
async def test_internal_resolver_rechecks_current_retention_without_reading_events(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs)
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    assert await reader.resolve_snapshot(snap.snapshot_ref) == snap
    await events.delete_by_run("t-r", "r", user_id="alice")
    with pytest.raises(HostCapabilityError, match="NOT_FOUND"):
        await reader.resolve_snapshot(snap.snapshot_ref)


@pytest.mark.asyncio
async def test_giant_event_preview_fits_envelope_and_advances(evidence):
    from deerflow_extension_api.completed_run_evidence import EvidenceLimits

    sf, events, runs, reader = evidence
    await put_run(runs)
    await put_event(events, content="巨大" * 100000)
    await put_event(events, content="last")
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    limits = EvidenceLimits(max_events=1, max_bytes=4096)
    first = await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None, limits=limits)
    assert first.has_more
    assert first.items[0].truncated
    assert first.items[0].content_bytes == 600000
    assert len(first.items[0].content_sha256) == 64
    assert len(json.dumps(asdict(first), ensure_ascii=False, separators=(",", ":")).encode()) <= 4096
    second = await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=first.next_cursor, limits=limits)
    assert json.loads(second.items[0].content_json) == "last"
    assert not second.has_more


@pytest.mark.asyncio
async def test_content_hash_and_body_preserve_embedded_null(evidence):
    import hashlib

    sf, events, runs, reader = evidence
    await put_run(runs)
    content = "before\x00after"
    await put_event(events, content=content)
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    page = await reader.read_events(snapshot_ref=snap.snapshot_ref)
    assert json.loads(page.items[0].content_json) == content
    assert page.items[0].content_sha256 == hashlib.sha256(content.encode()).hexdigest()


@pytest.mark.asyncio
async def test_seal_requires_drain_and_current_owner(evidence):
    sf, events, runs, reader = evidence
    await put_run(runs, owner_worker_id="worker", lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())
    journal = RunJournal("r", "t-r", events, user_id="alice")
    journal.record_middleware("test", name="test", hook="test", action="test", changes={})
    receipt = await journal.finish_evidence()
    assert not journal._closed
    journal.record_middleware("late", name="late", hook="late", action="late", changes={})
    assert await runs.seal_evidence("r", owner_worker_id="wrong", receipt=receipt) is False
    assert await runs.seal_evidence("r", owner_worker_id="worker", receipt=receipt) is True
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    assert snap.seal_state == "sealed"
    assert snap.event_count == 1
    assert snap.upper_event_seq == 1
    await journal.close()


@pytest.mark.asyncio
async def test_failed_flush_never_issues_seal_and_close_can_retry():
    class FailingStore(MemoryRunEventStore):
        fail = True

        async def put_batch(self, events):
            if self.fail:
                raise RuntimeError("write failed")
            return await super().put_batch(events)

    store = FailingStore()
    journal = RunJournal("r", "t", store)
    journal.record_middleware("test", name="test", hook="test", action="test", changes={})
    with pytest.raises(RuntimeError, match="write failed"):
        await journal.finish_evidence()
    assert not journal._closed
    assert journal._buffer
    store.fail = False
    await journal.close()
    assert journal._closed
    assert len(await store.list_events("t", "r")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error", "interrupted", "timeout"])
async def test_legacy_terminal_run_is_partial_even_with_delivery(evidence, status):
    sf, events, runs, reader = evidence
    await put_run(runs, status=status)
    async with sf() as session:
        await session.execute(update(RunRow).where(RunRow.run_id == "r").values(evidence_seal_state=None))
        await session.commit()
    await events.put(thread_id="t-r", run_id="r", event_type="run.delivery", category="outputs", content={})
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    assert snap.status == status
    assert snap.seal_state == "partial"


@pytest.mark.asyncio
async def test_admission_origin_survives_hydration_and_ignores_metadata(evidence):
    from deerflow.runtime.runs.manager import RunManager

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs)
    first = await manager.create_or_reject("t", "stable", user_id="alice", evidence_origin="interactive", metadata={"evidence_origin": "scheduled"})
    row = await runs.get(first.run_id, user_id="alice")
    assert row["evidence_origin"] == "interactive"
    assert manager._record_from_store(row).evidence_origin == "interactive"
    with pytest.raises(ValueError, match="origin"):
        await manager.create("bad", user_id="alice", evidence_origin="untrusted")


@pytest.mark.asyncio
async def test_expired_lease_cannot_seal(evidence):
    sf, events, runs, reader = evidence
    await put_run(runs, owner_worker_id="worker", lease_expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    journal = RunJournal("r", "t-r", events)
    receipt = await journal.finish_evidence()
    assert not await runs.seal_evidence("r", owner_worker_id="worker", receipt=receipt)
    assert (await reader.get_snapshot(thread_id="t-r", run_id="r")).seal_state != "sealed"
    await journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "error", "interrupted", "timeout"])
async def test_terminal_unsealed_crash_recovery_advances_discovery(evidence, status):
    from deerflow.runtime.runs.manager import RunManager

    sf, events, runs, reader = evidence
    expired = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await put_run(runs, "crash", status=status, owner_worker_id="dead", lease_expires_at=expired)
    await put_run(runs, "live", owner_worker_id="live", lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())
    before = await reader.list_changed_runs()
    await RunManager(store=runs).reconcile_orphaned_inflight_runs(error="owner died")
    row = await runs.get("crash", user_id="alice")
    assert row["status"] == status
    assert row["evidence_seal_state"] == "partial"
    assert row["evidence_seal_error"]
    assert (await runs.get("live", user_id="alice"))["evidence_seal_state"] == "pending"
    changes = await reader.list_changed_runs(cursor=before.next_cursor)
    assert [item.run_id for item in changes.items] == ["crash"]


@pytest.mark.asyncio
async def test_startup_recovers_more_than_one_evidence_batch(evidence):
    from deerflow.runtime.runs.manager import RunManager

    sf, events, runs, reader = evidence
    async with sf() as session:
        session.add_all([RunRow(run_id=f"crash-{i}", thread_id=f"t-{i}", user_id="alice", status="success", evidence_seal_state="pending") for i in range(201)])
        await session.commit()
    await RunManager(store=runs).reconcile_orphaned_inflight_runs(error="owner died")
    changes = await reader.list_changed_runs(limit=500)
    assert len(changes.items) == 201
    async with sf() as session:
        from sqlalchemy import func, select

        assert await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.evidence_seal_state == "pending")) == 0


@pytest.mark.asyncio
async def test_terminal_unsealed_recovery_keeps_live_local_finalization(evidence):
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.schemas import RunStatus

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs)
    record = await manager.create("t-local", user_id="alice")
    await manager.set_status(record.run_id, RunStatus.success)
    await manager.set_finalizing(record.run_id, True)
    await put_run(runs, "crashed-without-lease")
    await manager.reconcile_orphaned_inflight_runs(error="owner died")
    assert (await runs.get(record.run_id, user_id="alice"))["evidence_seal_state"] == "pending"
    assert (await runs.get("crashed-without-lease", user_id="alice"))["evidence_seal_state"] == "partial"


@pytest.mark.asyncio
async def test_thread_delete_invalidates_even_empty_snapshot(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs)
    snap = await reader.get_snapshot(thread_id="t-r", run_id="r")
    await events.delete_by_thread("t-r", user_id="alice")
    with pytest.raises(HostCapabilityError, match="NOT_FOUND"):
        await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "interrupted"])
async def test_worker_seals_after_completion_hook_before_end(evidence, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs, event_store=events)
    record = await manager.create("worker-thread", "stable-agent", user_id="alice")
    captured = []

    class Agent:
        async def astream(self, graph_input, config=None, **kwargs):
            captured.append(config["context"]["__run_journal"])
            if outcome == "error":
                raise RuntimeError("agent failure")
            if outcome == "interrupted":
                record.abort_event.set()
            yield {"messages": []}

    async def completion_hook(record):
        captured[0].record_middleware("completion", name="completion", hook="stop", action="done", changes={})

    async def end(run_id):
        snap = await reader.get_snapshot(thread_id=record.thread_id, run_id=run_id)
        assert snap.seal_state == "sealed"
        page = await reader.read_events(snapshot_ref=snap.snapshot_ref, cursor=None)
        assert "middleware:completion" in {e.event_type for e in page.items}

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=end, cleanup=AsyncMock())
    await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None, event_store=events, on_run_completed=completion_hook), agent_factory=lambda **kwargs: Agent(), graph_input={}, config={})
    assert record.status.value == outcome
    assert captured[0]._closed


@pytest.mark.asyncio
async def test_seal_failure_does_not_change_business_success(evidence, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs, event_store=events)
    record = await manager.create("worker-thread", "stable-agent", user_id="alice")
    failure = AsyncMock(side_effect=RuntimeError("seal database unavailable"))
    monkeypatch.setattr(runs, "seal_evidence", failure)

    class Agent:
        async def astream(self, *args, **kwargs):
            yield {"messages": []}

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None, event_store=events), agent_factory=lambda **kwargs: Agent(), graph_input={}, config={})
    failure.assert_awaited_once()
    assert record.status.value == "success"
    bridge.publish_end.assert_awaited_once()
    row = await runs.get(record.run_id, user_id="alice")
    assert row["evidence_seal_state"] == "partial"
    assert row["evidence_seal_error"]


@pytest.mark.asyncio
async def test_seal_cancellation_is_deferred_until_after_end(evidence, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs, event_store=events)
    record = await manager.create("cancel-seal", user_id="alice")

    class Agent:
        async def astream(self, *args, **kwargs):
            yield {"messages": []}

    monkeypatch.setattr(RunJournal, "finish_evidence", AsyncMock(side_effect=asyncio.CancelledError()))
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None, event_store=events), agent_factory=lambda **kwargs: Agent(), graph_input={}, config={})
    assert record.status.value == "success"
    assert not record.finalizing
    bridge.publish_end.assert_awaited_once()
    row = await runs.get(record.run_id, user_id="alice")
    assert row["evidence_seal_state"] == "partial"


@pytest.mark.asyncio
async def test_graph_assembly_failure_has_partial_coverage(evidence):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    sf, events, runs, reader = evidence
    manager = RunManager(store=runs, event_store=events)
    record = await manager.create("preflight", user_id="alice")

    def fail(**kwargs):
        raise RuntimeError("assembly failed")

    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None, event_store=events), agent_factory=fail, graph_input={}, config={})
    snap = await reader.get_snapshot(thread_id=record.thread_id, run_id=record.run_id)
    assert snap.status == "error"
    assert snap.seal_state == "partial"
    assert "execution" in snap.seal_error


def test_migration_is_additive_current_chain():
    from alembic.script import ScriptDirectory

    from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    rev = script.get_revision("0027_completed_run_evidence")
    assert rev.down_revision == "0026_mcp_task_lease_tokens"


@pytest.mark.asyncio
async def test_cancelled_background_flush_cannot_silently_seal_an_empty_tail(evidence):
    import asyncio

    sf, events, runs, reader = evidence
    await put_run(runs, owner_worker_id="worker")
    original = events.put_batch
    entered = asyncio.Event()

    async def blocked(batch):
        entered.set()
        await asyncio.Event().wait()

    events.put_batch = blocked
    journal = RunJournal("r", "t-r", events, user_id="alice", flush_threshold=1)
    journal.record_middleware("test", name="test", hook="test", action="test", changes={})
    await entered.wait()
    pending = tuple(journal._pending_flush_tasks)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    events.put_batch = original
    receipt = await journal.finish_evidence()
    assert receipt.event_count == 1
    await journal.close()


@pytest.mark.asyncio
async def test_cancelled_flush_before_first_execution_keeps_batch(evidence):
    import asyncio

    sf, events, runs, reader = evidence
    await put_run(runs)
    journal = RunJournal("r", "t-r", events, user_id="alice", flush_threshold=1)
    journal.record_middleware("test", name="test", hook="test", action="test", changes={})
    pending = tuple(journal._pending_flush_tasks)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    receipt = await journal.finish_evidence()
    assert receipt.event_count == 1
    await journal.close()


@pytest.mark.asyncio
async def test_already_admitted_cross_thread_callback_survives_stop(evidence):
    import threading

    sf, events, runs, reader = evidence
    await put_run(runs)
    journal = RunJournal("r", "t-r", events, user_id="alice")
    thread = threading.Thread(target=lambda: journal.record_middleware("accepted", name="accepted", hook="test", action="test", changes={}))
    thread.start()
    thread.join()
    receipt = await journal.finish_evidence()
    assert receipt.event_count == 1
    assert not journal._closed
    journal.record_middleware("rejected", name="rejected", hook="test", action="test", changes={})
    await journal.close()
    assert len(await events.list_events("t-r", "r", user_id="alice")) == 1


@pytest.mark.asyncio
async def test_lifecycle_transition_invalidates_pending_snapshot(evidence):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    sf, events, runs, reader = evidence
    await put_run(runs, status="running")
    pending = await reader.get_snapshot(thread_id="t-r", run_id="r")
    await runs.update_status("r", "error")
    terminal = await reader.get_snapshot(thread_id="t-r", run_id="r")
    assert terminal.status == "error"
    assert terminal.seal_state == "partial"
    assert terminal.evidence_revision != pending.evidence_revision
    with pytest.raises(HostCapabilityError, match="EVIDENCE_EXPIRED"):
        await reader.read_events(snapshot_ref=pending.snapshot_ref)


def test_migration_upgrades_real_sqlite_and_preserves_legacy_partial(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect, text

    from deerflow.persistence.bootstrap import _get_alembic_config

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(RunRow.__table__.insert().values(run_id="old", thread_id="thread", user_id="alice", status="success"))
        conn.execute(text("DROP TABLE completed_run_snapshots"))
        conn.execute(RunEventRow.__table__.insert().values(thread_id="thread", run_id="old", user_id="alice", event_type="test", category="message", content="legacy", seq=1))
        conn.execute(text("ALTER TABLE run_events DROP COLUMN content_sha256"))
        for name in ("evidence_origin", "evidence_agent_id", "evidence_seal_state", "evidence_seal_error", "evidence_revision", "evidence_upper_seq", "evidence_event_count", "evidence_retention_revision"):
            conn.execute(text(f"ALTER TABLE runs DROP COLUMN {name}"))
    config = _get_alembic_config(engine)
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    command.stamp(config, "0026_mcp_task_lease_tokens")
    command.upgrade(config, "0027_completed_run_evidence")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT evidence_seal_state, evidence_revision, evidence_retention_revision FROM runs WHERE run_id='old'")).one()
        assert tuple(row) == (None, None, 0)
        assert conn.scalar(text("SELECT content_sha256 FROM run_events WHERE run_id='old'")) is None
        assert "completed_run_snapshots" in inspect(conn).get_table_names()
    engine.dispose()
