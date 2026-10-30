"""Strict producer permissions survive the actual Worker and publisher paths."""

import asyncio

import pytest
from test_run_producer_cutover import cutover_db as cutover_db


@pytest.mark.asyncio
async def test_strict_worker_keeps_terminal_hook_open_then_closes_after_drain(cutover_db):
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.producer import activate_producer_fencing
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.events.producer import current_producer
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, _SubagentEventBuffer, run_agent
    from deerflow.runtime.stream_bridge import MemoryStreamBridge

    _, sf, _ = cutover_db
    await activate_producer_fencing(sf, cutover_id="worker-test")
    events = DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="worker-test")
    runs = RunRepository(sf)
    manager = RunManager(store=runs, event_store=events, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=300))
    record = await manager.create_or_reject("thread", user_id="alice")
    holder = {}

    class RootAgent:
        async def astream(self, graph_input, config=None, **kwargs):
            holder["journal"] = config["context"]["__run_journal"]
            yield {"messages": []}

    async def hook(completed):
        row = await runs.get(completed.run_id, user_id="alice")
        assert row["status"] == "success"
        assert row["producer_state"] == "open"
        assert current_producer().run_incarnation == record.run_incarnation
        assert await asyncio.to_thread(lambda: current_producer().producer_epoch) == record.producer_epoch
        holder["journal"].record_middleware("completion", name="hook", hook="completion", action="accepted", changes={})
        # Same production buffer used by the Worker for delegated task events.
        buffer = _SubagentEventBuffer(events, record.thread_id, record.run_id)
        await buffer.add({"type": "task_completed", "task_id": "subtask", "result": "done"})
        await buffer.flush()

    task = asyncio.create_task(
        run_agent(
            MemoryStreamBridge(), manager, record, ctx=RunContext(checkpointer=None, event_store=events, on_run_completed=hook), agent_factory=lambda **kwargs: RootAgent(), graph_input={}, config={"configurable": {"thread_id": "thread"}}
        )
    )
    record.task = task
    await asyncio.wait_for(task, 15)
    row = await runs.get(record.run_id, user_id="alice")
    written = await events.list_events("thread", record.run_id, user_id="alice")
    types = [event["event_type"] for event in written]
    assert "middleware:completion" in types
    assert "subagent.end" in types
    assert types.count("run.delivery") == types.count("run.terminal") == 1
    terminal_seq = next(event["seq"] for event in written if event["event_type"] == "run.terminal")
    assert all(event["seq"] < terminal_seq for event in written if event["event_type"] in {"middleware:completion", "subagent.end"})
    assert row["producer_state"] == "closed"
    assert row["evidence_seal_state"] == "sealed"
    assert current_producer() is None


@pytest.mark.asyncio
async def test_strict_takeover_publisher_has_separate_retention_bound_authority(cutover_db):
    from datetime import UTC, datetime, timedelta

    from deerflow.persistence.run.producer import activate_producer_fencing
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.terminal import RecoveryTerminalPublisher

    _, sf, _ = cutover_db
    await activate_producer_fencing(sf, cutover_id="takeover-test")
    runs = RunRepository(sf)
    events = DbRunEventStore(sf, producer_fencing="strict")
    await runs.put("run", thread_id="thread", user_id="alice", status="running", owner_worker_id="old", lease_expires_at=(datetime.now(UTC) - timedelta(seconds=60)).isoformat())
    old = await runs.get("run", user_id="alice")
    claimed = await runs.claim_for_takeover("run", grace_seconds=0, error="orphan")
    publisher = RecoveryTerminalPublisher(events, runs)
    target = publisher.authorize_takeover(claimed=claimed, thread_id="thread", run_id="run", user_id="alice", operation_kind="run", run_incarnation=old["run_incarnation"], retention_revision=old["evidence_retention_revision"])
    assert (await publisher.publish(target)).confirmed
    assert [event["event_type"] for event in await events.list_events("thread", "run", user_id="alice")] == ["run.delivery", "run.terminal"]


@pytest.mark.asyncio
async def test_strict_journal_keeps_host_identity_across_contextless_callback(cutover_db):
    import threading
    from types import SimpleNamespace

    from deerflow.runtime.events.producer import producer_authority, producer_scope
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.journal import RunJournal

    _, sf, _ = cutover_db
    from deerflow.persistence.run.sql import RunRepository

    row = await RunRepository(sf).put("run", thread_id="thread", user_id="alice", owner_worker_id="owner")
    events = DbRunEventStore(sf, producer_fencing="strict")
    with producer_scope(producer_authority(SimpleNamespace(**row))):
        journal = RunJournal("run", "thread", events, user_id="alice", flush_threshold=1)

    def callback():
        journal.record_middleware("thread", name="raw-thread", hook="tool", action="accepted", changes={})

    thread = threading.Thread(target=callback)
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive()
    try:
        await journal.flush()
        assert [event["event_type"] for event in await events.list_events("thread", "run", user_id="alice")] == ["middleware:thread"]
    finally:
        await journal.close(flush=False)


@pytest.mark.asyncio
async def test_detached_idempotent_handle_cannot_publish_owner_receipt(cutover_db):
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.events.producer import producer_authority
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.runs.manager import RunManager, RunStartupError
    from deerflow.runtime.runs.worker import RunContext, run_agent
    from deerflow.runtime.stream_bridge import MemoryStreamBridge

    _, sf, _ = cutover_db
    runs = RunRepository(sf)
    owner = RunManager(store=runs, worker_id="owner")
    admitted = await owner.create_or_reject("thread", user_id="alice", idempotency_key="same-request")
    peer = RunManager(store=runs, worker_id="peer")
    handle = await peer.create_or_reject("thread", user_id="alice", idempotency_key="same-request")
    assert handle.store_only and handle.idempotency_reused
    assert producer_authority(handle) is None
    events = DbRunEventStore(sf, producer_fencing="strict")
    with pytest.raises(RunStartupError):
        await run_agent(MemoryStreamBridge(), peer, handle, ctx=RunContext(checkpointer=None, event_store=events), agent_factory=lambda **kwargs: pytest.fail("Detached handle executed the agent"), graph_input={}, config={})
    assert (await runs.get(admitted.run_id, user_id="alice"))["status"] == "pending"
    assert await events.list_events("thread", admitted.run_id, user_id="alice") == []


@pytest.mark.asyncio
async def test_workspace_recorder_preserves_producer_grant(cutover_db, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.events.producer import producer_authority, producer_scope
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.workspace_changes import WorkspaceRoot, record_workspace_changes, scan_workspace_roots

    _, sf, _ = cutover_db
    row = await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="success", owner_worker_id="owner")
    roots = [WorkspaceRoot(name="workspace", host_path=tmp_path, virtual_prefix="/mnt/user-data/workspace")]
    monkeypatch.setattr("deerflow.workspace_changes.recorder.build_thread_workspace_roots", lambda *args, **kwargs: roots)
    before = scan_workspace_roots(roots)
    (tmp_path / "report.txt").write_text("completed", encoding="utf-8")
    with producer_scope(producer_authority(SimpleNamespace(**row))):
        event = await record_workspace_changes(DbRunEventStore(sf, producer_fencing="strict"), "thread", "run", before, user_id="alice")
    assert event["event_type"] == "workspace_changes"
    assert event["user_id"] == "alice"
