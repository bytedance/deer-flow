"""Tests for multi-worker run ownership (work items 2–3).

Coverage:
- create_or_reject with reject strategy blocks duplicate active runs
- create_or_reject with interrupt strategy claims and cancels old runs
- create_thread_operation_atomic refuses to interrupt a run owned by another live worker
- reconcile_orphaned_inflight_runs uses lease-based detection
- periodic reconciliation notifies Gateway recovery orchestration
- Worker reconciliation skips runs with unexpired leases
- Lease heartbeat renews active run leases
- GATEWAY_WORKERS=1 + heartbeat_enabled=false behaviour unchanged
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import LOCAL_FINALIZER_PENDING_STOP_REASON, ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus, ThreadOperationKind
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import CancelOutcome, ConflictError, _generate_worker_id
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.runtime.user_context import get_current_user, reset_current_user, set_current_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lease_config(**kwargs) -> RunOwnershipConfig:
    return RunOwnershipConfig(
        lease_seconds=kwargs.get("lease_seconds", 30),
        grace_seconds=kwargs.get("grace_seconds", 10),
        heartbeat_enabled=kwargs.get("heartbeat_enabled", False),
    )


def _make_manager(store=None, **kwargs) -> RunManager:
    return RunManager(
        store=store or MemoryRunStore(),
        run_ownership_config=kwargs.pop("run_ownership_config", _lease_config()),
        **kwargs,
    )


class _OwnerCapturingEventStore(MemoryRunEventStore):
    def __init__(self, run_store: MemoryRunStore, *, require_terminal_row: bool = True):
        super().__init__()
        self._run_store = run_store
        self._require_terminal_row = require_terminal_row
        self.writes: list[tuple[str, str, str | None]] = []

    async def put_if_absent(self, **kwargs):
        row = await self._run_store.get(kwargs["run_id"])
        assert row is not None
        if self._require_terminal_row:
            assert row["status"] not in {"pending", "running"}
        user = get_current_user()
        self.writes.append((kwargs["run_id"], kwargs["event_type"], user.id if user is not None else None))
        return await super().put_if_absent(**kwargs)


class _TerminalOutputAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        journal = config["context"]["__run_journal"]
        journal._remember_current_run_tool_calls(
            AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}]),
            caller="lead_agent",
        )
        journal.on_tool_end(
            Command(
                update={
                    "artifacts": ["/mnt/user-data/outputs/report.md"],
                    "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                }
            ),
            run_id=uuid4(),
        )
        journal.on_chain_end(
            {"messages": [AIMessage(content="real worker output")]},
            run_id=uuid4(),
            parent_run_id=None,
        )
        yield {"messages": []}


def _start_output_worker(
    manager: RunManager,
    record,
    events: MemoryRunEventStore,
) -> asyncio.Task:
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    worker_user_token = set_current_user(SimpleNamespace(id=record.user_id))
    try:
        task = asyncio.create_task(
            run_agent(
                bridge,
                manager,
                record,
                ctx=RunContext(checkpointer=None, event_store=events),
                agent_factory=lambda *, config: _TerminalOutputAgent(),
                graph_input={},
                config={},
            )
        )
    finally:
        reset_current_user(worker_user_token)
    record.task = task
    return task


# ---------------------------------------------------------------------------
# create_or_reject — reject strategy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reject_blocks_when_active_run_exists():
    """reject strategy must raise ConflictError when thread has an active run."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    await manager.create("thread-1")
    await manager.set_status((await manager.list_by_thread("thread-1"))[0].run_id, RunStatus.running)

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="reject")


@pytest.mark.anyio
async def test_reject_succeeds_when_no_active_run():
    """reject strategy must succeed when the thread has no active run."""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1", multitask_strategy="reject")
    assert record is not None
    assert record.status == RunStatus.pending
    assert record.owner_worker_id is not None
    assert record.lease_expires_at is not None


@pytest.mark.anyio
async def test_checkpoint_write_reservation_rejects_nonowning_worker_while_run_is_active():
    """A durable run owned by worker A must block worker B's checkpoint writer."""
    store = MemoryRunStore()
    owner = _make_manager(store=store, worker_id="worker-a")
    non_owner = _make_manager(store=store, worker_id="worker-b")
    active = await owner.create_or_reject("thread-1")
    await owner.set_status(active.run_id, RunStatus.running)

    with pytest.raises(ConflictError, match="already has an active run"):
        async with non_owner.reserve_thread_operation("thread-1", kind=ThreadOperationKind.checkpoint_write):
            pytest.fail("the checkpoint mutation guard must not be acquired")

    stored = await store.get(active.run_id)
    assert stored is not None
    assert stored["status"] == "running"


@pytest.mark.anyio
async def test_checkpoint_write_reservation_blocks_new_runs_until_mutation_finishes():
    """The durable guard closes the check-then-write window in both directions."""
    store = MemoryRunStore()
    compaction_worker = _make_manager(store=store, worker_id="worker-a")
    run_worker = _make_manager(store=store, worker_id="worker-b")

    async with compaction_worker.reserve_thread_operation("thread-1", kind=ThreadOperationKind.checkpoint_write):
        inflight = await store.list_inflight()
        assert len(inflight) == 1
        assert inflight[0]["operation_kind"] == ThreadOperationKind.checkpoint_write
        assert inflight[0]["metadata"] == {}

        with pytest.raises(ConflictError, match="checkpoint write"):
            await run_worker.create_or_reject("thread-1", multitask_strategy="interrupt")

    assert await store.list_inflight() == []
    assert await store.list_by_thread("thread-1") == []

    admitted = await run_worker.create_or_reject("thread-1")
    assert admitted.status == RunStatus.pending


@pytest.mark.anyio
async def test_interrupt_reclaims_expired_checkpoint_write_reservation():
    """A dead checkpoint writer must not wait for periodic reconciliation."""
    store = MemoryRunStore()
    expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    await store.put(
        "checkpoint-write-1",
        thread_id="thread-1",
        status="pending",
        operation_kind=ThreadOperationKind.checkpoint_write,
        owner_worker_id="dead-worker",
        lease_expires_at=expired,
        created_at=expired,
    )
    manager = _make_manager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=_lease_config(grace_seconds=10),
    )

    admitted = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")

    assert admitted.status == RunStatus.pending
    stale = await store.get("checkpoint-write-1")
    assert stale is not None
    assert stale["status"] == "interrupted"
    assert stale["owner_worker_id"] == "worker-b"


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_cross_worker_admission_backfills_terminal_events_for_every_claimed_run(strategy):
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    on_recovered = AsyncMock(return_value=False)
    expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    for run_id, owner_id in (("old-run-a", "owner-a"), ("old-run-b", "owner-b")):
        await store.put(
            run_id,
            thread_id="thread-1",
            status="running",
            operation_kind=ThreadOperationKind.run,
            user_id=owner_id,
            owner_worker_id=f"dead-{owner_id}",
            lease_expires_at=expired,
            created_at=expired,
        )
    await store.put(
        "expired-checkpoint-write",
        thread_id="thread-1",
        status="pending",
        operation_kind=ThreadOperationKind.checkpoint_write,
        user_id="reservation-owner",
        owner_worker_id="dead-reservation-owner",
        lease_expires_at=expired,
        created_at=expired,
    )
    manager = _make_manager(
        store=store,
        event_store=events,
        on_orphans_recovered=on_recovered,
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10),
    )

    admitted = await manager.create_or_reject(
        "thread-1",
        multitask_strategy=strategy,
        user_id="new-owner",
    )

    assert admitted.status == RunStatus.pending
    for run_id in ("old-run-a", "old-run-b"):
        claimed = await store.get(run_id)
        assert claimed is not None
        assert claimed["status"] == "interrupted"
        assert claimed["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
        delivery = await events.list_events("thread-1", run_id, event_types=["run.delivery"])
        terminal = await events.list_events("thread-1", run_id, event_types=["run.end"])
        assert len(delivery) == 1
        assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
        assert len(terminal) == 1
        assert terminal[0]["metadata"] == {
            "status": "interrupted",
            "recovered": True,
            "authoritative": True,
        }

    assert await events.list_events("thread-1", "expired-checkpoint-write") == []
    assert set(events.writes) == {
        ("old-run-a", "run.delivery", "owner-a"),
        ("old-run-a", "run.end", "owner-a"),
        ("old-run-b", "run.delivery", "owner-b"),
        ("old-run-b", "run.end", "owner-b"),
    }
    on_recovered.assert_awaited_once()
    recovered_records = on_recovered.await_args.args[0]
    assert {record.run_id for record in recovered_records} == {"old-run-a", "old-run-b"}
    assert all(record.stop_reason == ORPHAN_RECOVERY_STOP_REASON for record in recovered_records)


@pytest.mark.anyio
async def test_atomic_admission_marks_local_task_until_its_lease_expires():
    """A cancelled wrapper cannot be recovered while its finalizer lease is live."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-live-local")
    await manager.set_status(old.run_id, RunStatus.running)
    old.task = asyncio.create_task(asyncio.Event().wait())

    replacement = await manager.create_or_reject(
        "thread-live-local",
        multitask_strategy="interrupt",
    )
    await asyncio.gather(old.task, return_exceptions=True)

    stored = await store.get(old.run_id)
    assert replacement.status == RunStatus.pending
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["stop_reason"] == LOCAL_FINALIZER_PENDING_STOP_REASON
    assert stored["lease_expires_at"] is not None
    assert await manager.recover_expired_local_finalizer(manager._record_from_store(stored)) is False

    store._runs[old.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    assert await manager.recover_expired_local_finalizer(manager._record_from_store(stored)) is True
    assert (await store.get(old.run_id))["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_atomic_admission_marks_a_same_owner_run_after_local_ownership_loss():
    """A fenced local record has no authoritative publisher despite owner equality."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-fenced-local")
    await manager.set_status(old.run_id, RunStatus.running)
    old.status = RunStatus.error
    old.ownership_lost = True

    replacement = await manager.create_or_reject(
        "thread-fenced-local",
        multitask_strategy="interrupt",
    )

    stored = await store.get(old.run_id)
    assert replacement.status == RunStatus.pending
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_admission_cancels_only_rows_returned_by_atomic_claim():
    """A worker that finishes during the DB await must not be cancelled later."""

    class PausedAtomicStore(MemoryRunStore):
        supports_atomic_recovery_markers = True

        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.pause = False

        async def create_thread_operation_atomic(self, run_id, **kwargs):
            if self.pause:
                self.entered.set()
                await self.release.wait()
            return await super().create_thread_operation_atomic(run_id, **kwargs)

    store = PausedAtomicStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-finish-during-admission")
    await manager.set_status(old.run_id, RunStatus.running)
    old.task = asyncio.create_task(asyncio.Event().wait())
    store.pause = True

    admission = asyncio.create_task(
        manager.create_or_reject(
            old.thread_id,
            multitask_strategy="interrupt",
        )
    )
    await asyncio.wait_for(store.entered.wait(), timeout=1)
    store._runs[old.run_id]["status"] = RunStatus.success.value
    old.status = RunStatus.success
    store.release.set()

    replacement = await asyncio.wait_for(admission, timeout=1)
    assert replacement.status == RunStatus.pending
    assert old.abort_event.is_set() is False
    assert old.task.done() is False
    assert (await store.get(old.run_id))["cancel_action"] is None

    old.task.cancel()
    await asyncio.gather(old.task, return_exceptions=True)


@pytest.mark.anyio
async def test_strict_legacy_store_rejects_live_local_interrupt_before_mutation():
    class StrictLegacyStore(MemoryRunStore):
        def __init__(self) -> None:
            super().__init__()
            self.atomic_calls = 0

        async def create_thread_operation_atomic(self, run_id, **kwargs):
            self.atomic_calls += 1
            return await super().create_thread_operation_atomic(run_id, **kwargs)

    store = StrictLegacyStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-strict-store")
    await manager.set_status(old.run_id, RunStatus.running)
    old.task = asyncio.create_task(asyncio.Event().wait())
    store.atomic_calls = 0

    with pytest.raises(ConflictError, match="cannot atomically fence"):
        await manager.create_or_reject(
            old.thread_id,
            multitask_strategy="interrupt",
        )

    assert store.atomic_calls == 0
    assert old.abort_event.is_set() is False
    assert old.task.done() is False
    assert (await store.get(old.run_id))["status"] == RunStatus.running.value
    old.task.cancel()
    await asyncio.gather(old.task, return_exceptions=True)


@pytest.mark.anyio
async def test_atomic_admission_preserves_first_cancel_action_winner():
    """A prior durable interrupt wins over a racing rollback admission."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-first-action")
    await manager.set_status(old.run_id, RunStatus.running)
    old.task = asyncio.create_task(asyncio.Event().wait())
    assert await store.request_cancel(old.run_id, action="interrupt") == "interrupt"

    await manager.create_or_reject(
        old.thread_id,
        multitask_strategy="rollback",
    )
    await asyncio.gather(old.task, return_exceptions=True)

    claimed = await store.get(old.run_id)
    assert claimed is not None
    assert claimed["cancel_action"] == "interrupt"
    assert old.abort_action == "interrupt"


@pytest.mark.anyio
async def test_delayed_atomic_commit_refreshes_predecessor_and_replacement_leases():
    class DelayedStore(MemoryRunStore):
        supports_atomic_recovery_markers = True

        def __init__(self) -> None:
            super().__init__()
            self.pause = False
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def create_thread_operation_atomic(self, run_id, **kwargs):
            if self.pause:
                self.entered.set()
                await self.release.wait()
            return await super().create_thread_operation_atomic(run_id, **kwargs)

    store = DelayedStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(
            heartbeat_enabled=True,
            lease_seconds=30,
        ),
    )
    old = await manager.create_or_reject("thread-delayed-commit")
    await manager.set_status(old.run_id, RunStatus.running)
    old.task = asyncio.create_task(asyncio.Event().wait())
    stale = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    manager._compute_lease_expires_at = lambda: stale
    store.pause = True

    admission = asyncio.create_task(
        manager.create_or_reject(
            old.thread_id,
            multitask_strategy="interrupt",
        )
    )
    await asyncio.wait_for(store.entered.wait(), timeout=1)
    store.release.set()
    replacement = await asyncio.wait_for(admission, timeout=1)
    await asyncio.gather(old.task, return_exceptions=True)

    old_row = await store.get(old.run_id)
    replacement_row = await store.get(replacement.run_id)
    fresh_boundary = datetime.now(UTC) + timedelta(seconds=20)
    assert datetime.fromisoformat(old_row["lease_expires_at"]) > fresh_boundary
    assert datetime.fromisoformat(replacement_row["lease_expires_at"]) > fresh_boundary
    assert replacement.lease_expires_at == replacement_row["lease_expires_at"]


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_admission_preserves_active_terminal_staged_workers_authoritative_events(
    monkeypatch,
    strategy,
):
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store, require_terminal_row=False)
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-1", user_id="run-owner")

    staged_success = asyncio.Event()
    release_staged_success = asyncio.Event()
    original_set_status = manager.set_status_if_not_cancelled

    async def pause_after_staging_success(run_id, status, **kwargs):
        outcome = await original_set_status(run_id, status, **kwargs)
        if status == RunStatus.success and kwargs.get("persist") is False and not staged_success.is_set():
            staged_success.set()
            await release_staged_success.wait()
        return outcome

    monkeypatch.setattr(manager, "set_status_if_not_cancelled", pause_after_staging_success)
    worker_task = _start_output_worker(manager, old, events)
    await asyncio.wait_for(staged_success.wait(), timeout=1)

    admission_task = asyncio.create_task(
        manager.create_or_reject(
            "thread-1",
            multitask_strategy=strategy,
            user_id="new-owner",
        )
    )
    await asyncio.sleep(0)
    admission_waited = not admission_task.done()
    status_while_waiting = (await store.get(old.run_id))["status"]
    events_while_waiting = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.delivery", "run.end"],
    )
    finalizing_while_waiting = old.finalizing
    release_staged_success.set()
    await asyncio.wait_for(worker_task, timeout=1)
    admitted = await asyncio.wait_for(admission_task, timeout=1)

    assert admission_waited is True
    assert status_while_waiting == RunStatus.running.value
    assert events_while_waiting == []
    assert finalizing_while_waiting is True
    assert admitted.status == RunStatus.pending
    claimed = await store.get(old.run_id)
    assert claimed is not None
    assert claimed["status"] == RunStatus.success.value
    delivery = await events.list_events("thread-1", old.run_id, event_types=["run.delivery"])
    terminal = await events.list_events("thread-1", old.run_id, event_types=["run.end"])
    assert len(delivery) == 1
    assert delivery[0]["content"] == {
        "presented": 1,
        "paths": ["/mnt/user-data/outputs/report.md"],
        "by_tool": {"present_files": ["/mnt/user-data/outputs/report.md"]},
    }
    assert len(terminal) == 1
    assert terminal[0]["content"]["messages"][0].content == "real worker output"
    assert terminal[0]["metadata"] == {
        "status": RunStatus.success.value,
        "authoritative": True,
    }
    assert events.writes == [
        (old.run_id, "run.delivery", "run-owner"),
        (old.run_id, "run.end", "run-owner"),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_admission_commits_local_finalizer_marker_before_worker_receipt(
    monkeypatch,
    strategy,
):
    """Admission stays atomic while a live worker retains its authoritative tail."""
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store, require_terminal_row=False)
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-admission-cancel", user_id="run-owner")
    worker_streaming = asyncio.Event()

    class BlockingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal.on_chain_end(
                {"messages": [AIMessage(content="output before cancellation")]},
                run_id=uuid4(),
                parent_run_id=None,
            )
            worker_streaming.set()
            await asyncio.Event().wait()
            yield {"messages": []}

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    worker_user_token = set_current_user(SimpleNamespace(id=old.user_id))
    try:
        worker_task = asyncio.create_task(
            run_agent(
                bridge,
                manager,
                old,
                ctx=RunContext(checkpointer=None, event_store=events),
                agent_factory=lambda *, config: BlockingAgent(),
                graph_input={},
                config={},
            )
        )
    finally:
        reset_current_user(worker_user_token)
    old.task = worker_task
    await asyncio.wait_for(worker_streaming.wait(), timeout=1)

    receipt_started = asyncio.Event()
    release_receipt = asyncio.Event()
    from deerflow.runtime.runs import worker as worker_module

    original_persist_delivery = worker_module._persist_delivery_receipt

    async def pause_delivery_receipt(*args, **kwargs):
        receipt_started.set()
        await release_receipt.wait()
        return await original_persist_delivery(*args, **kwargs)

    monkeypatch.setattr(worker_module, "_persist_delivery_receipt", pause_delivery_receipt)
    store.create_thread_operation_atomic = AsyncMock(
        wraps=store.create_thread_operation_atomic,
    )

    admission_task = asyncio.create_task(
        manager.create_or_reject(
            old.thread_id,
            multitask_strategy=strategy,
            user_id="new-owner",
        )
    )
    await asyncio.wait_for(receipt_started.wait(), timeout=1)

    durable_before_receipt = await store.get(old.run_id)
    admitted = await asyncio.wait_for(admission_task, timeout=1)
    assert admitted.status == RunStatus.pending
    store.create_thread_operation_atomic.assert_awaited_once()
    assert durable_before_receipt is not None
    assert durable_before_receipt["status"] == RunStatus.interrupted.value
    assert durable_before_receipt["cancel_action"] == strategy
    assert durable_before_receipt["stop_reason"] == LOCAL_FINALIZER_PENDING_STOP_REASON
    assert old.abort_action == strategy
    assert old.abort_event.is_set()
    assert old.finalizing is True
    assert old.terminal_status_staged is True
    assert (
        await events.list_events(
            old.thread_id,
            old.run_id,
            event_types=["run.delivery", "run.end"],
        )
        == []
    )

    release_receipt.set()
    await asyncio.wait_for(worker_task, timeout=1)

    durable = await store.get(old.run_id)
    assert durable is not None
    assert durable["status"] == (RunStatus.interrupted.value if strategy == "interrupt" else RunStatus.error.value)
    assert durable.get("stop_reason") == LOCAL_FINALIZER_PENDING_STOP_REASON
    delivery = await events.list_events(
        old.thread_id,
        old.run_id,
        event_types=["run.delivery"],
    )
    terminal = await events.list_events(
        old.thread_id,
        old.run_id,
        event_types=["run.end"],
    )
    assert len(delivery) == 1
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": durable["status"],
        "authoritative": True,
    }
    bridge.publish_end.assert_awaited_once_with(old.run_id)


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_direct_cancel_fences_admission_before_durable_terminal_write(
    monkeypatch,
    strategy,
):
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store, require_terminal_row=False)
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-1", user_id="run-owner")

    worker_streaming = asyncio.Event()

    class BlockingOutputAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal.on_chain_end(
                {"messages": [AIMessage(content="real rollback output")]},
                run_id=uuid4(),
                parent_run_id=None,
            )
            worker_streaming.set()
            await asyncio.Event().wait()
            yield {"messages": []}

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    worker_user_token = set_current_user(SimpleNamespace(id=old.user_id))
    try:
        worker_task = asyncio.create_task(
            run_agent(
                bridge,
                manager,
                old,
                ctx=RunContext(checkpointer=None, event_store=events),
                agent_factory=lambda *, config: BlockingOutputAgent(),
                graph_input={},
                config={},
            )
        )
    finally:
        reset_current_user(worker_user_token)
    old.task = worker_task
    await asyncio.wait_for(worker_streaming.wait(), timeout=1)

    worker_terminal_staged = asyncio.Event()
    release_worker_terminal = asyncio.Event()
    original_set_status = manager.set_status

    async def pause_worker_terminal_status(run_id, status, **kwargs):
        if run_id == old.run_id and status == RunStatus.error and kwargs.get("stage_terminal") is True:
            worker_terminal_staged.set()
            await release_worker_terminal.wait()
        return await original_set_status(run_id, status, **kwargs)

    monkeypatch.setattr(manager, "set_status", pause_worker_terminal_status)

    cancel_task = asyncio.create_task(manager.cancel(old.run_id, action="rollback"))
    assert await asyncio.wait_for(cancel_task, timeout=1) == CancelOutcome.cancelled
    await asyncio.wait_for(worker_terminal_staged.wait(), timeout=1)

    store.create_thread_operation_atomic = AsyncMock(
        wraps=store.create_thread_operation_atomic,
    )
    admission_attempt_finished = asyncio.Event()
    original_admit = manager._admit_thread_operation

    async def observe_admission_attempt(*args, **kwargs):
        try:
            return await original_admit(*args, **kwargs)
        finally:
            admission_attempt_finished.set()

    monkeypatch.setattr(manager, "_admit_thread_operation", observe_admission_attempt)
    admission_task = asyncio.create_task(
        manager.create_or_reject(
            "thread-1",
            multitask_strategy=strategy,
            user_id="new-owner",
        )
    )
    await asyncio.wait_for(admission_attempt_finished.wait(), timeout=1)

    admission_waited = not admission_task.done()
    terminal_before_durable_cancel = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.end"],
    )
    durable_before_tail = await store.get(old.run_id)
    assert durable_before_tail is not None
    durable_status_before_cancel = durable_before_tail["status"]
    durable_cancel_action = durable_before_tail["cancel_action"]
    cancel_staged_terminal = old.terminal_status_staged
    atomic_calls_before_cancel = store.create_thread_operation_atomic.await_count

    release_worker_terminal.set()
    await asyncio.wait_for(worker_task, timeout=1)
    admitted = await asyncio.wait_for(admission_task, timeout=1)

    assert admission_waited is True
    assert cancel_staged_terminal is True
    assert atomic_calls_before_cancel == 0
    assert durable_status_before_cancel == RunStatus.running.value
    assert durable_cancel_action == "rollback"
    assert terminal_before_durable_cancel == []
    assert admitted.status == RunStatus.pending
    stored = await store.get(old.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "Rolled back by user"
    terminal = await events.list_events("thread-1", old.run_id, event_types=["run.end"])
    assert len(terminal) == 1
    assert terminal[0]["content"]["messages"][0].content == "real rollback output"
    assert terminal[0]["metadata"] == {
        "status": RunStatus.error.value,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_pending_direct_cancel_signals_wrapper_before_atomic_recovery(
    monkeypatch,
):
    """A pending metadata wrapper must observe abort without skipping cleanup."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-pending-wrapper")
    wrapper_started = asyncio.Event()
    wrapper_aborted = asyncio.Event()

    async def metadata_wrapper():
        wrapper_started.set()
        await old.abort_event.wait()
        wrapper_aborted.set()

    wrapper_task = asyncio.create_task(metadata_wrapper())
    old.task = wrapper_task
    await asyncio.wait_for(wrapper_started.wait(), timeout=1)

    async def accept_durable_cancel(_run_id, *, action):
        return CancelOutcome.requested, action

    monkeypatch.setattr(manager, "_request_durable_cancel", accept_durable_cancel)
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    old.lease_expires_at = expired
    store._runs[old.run_id]["lease_expires_at"] = expired

    outcome = await manager.cancel(old.run_id, action="interrupt")
    await asyncio.wait_for(wrapper_aborted.wait(), timeout=1)
    await wrapper_task
    for _ in range(10):
        if not old.finalizing:
            break
        await asyncio.sleep(0)

    assert outcome == CancelOutcome.cancelled
    assert old.ownership_lost is False
    assert old.finalizing is False
    assert old.terminal_status_persistence_inflight == 0

    replacement = await manager.create_or_reject(
        "thread-pending-wrapper",
        multitask_strategy="interrupt",
    )
    await asyncio.wait_for(
        manager.wait_for_prior_finalizing(
            replacement.thread_id,
            replacement.run_id,
        ),
        timeout=1,
    )
    stored = await store.get(old.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_admission_waits_for_terminal_worker_paused_inside_finalization(monkeypatch):
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store, require_terminal_row=False)
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-1", user_id="run-owner")

    receipt_started = asyncio.Event()
    release_receipt = asyncio.Event()
    from deerflow.runtime.runs import worker as worker_module

    original_persist_delivery = worker_module._persist_delivery_receipt

    async def pause_delivery_receipt(*args, **kwargs):
        receipt_started.set()
        await release_receipt.wait()
        return await original_persist_delivery(*args, **kwargs)

    monkeypatch.setattr(worker_module, "_persist_delivery_receipt", pause_delivery_receipt)
    worker_task = _start_output_worker(manager, old, events)
    await asyncio.wait_for(receipt_started.wait(), timeout=1)

    admission_task = asyncio.create_task(
        manager.create_or_reject(
            "thread-1",
            multitask_strategy="interrupt",
            user_id="new-owner",
        )
    )
    await asyncio.sleep(0)
    admission_waited = not admission_task.done()
    status_while_waiting = (await store.get(old.run_id))["status"]
    events_while_waiting = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.delivery", "run.end"],
    )
    finalizing_while_waiting = old.finalizing
    release_receipt.set()
    await asyncio.wait_for(worker_task, timeout=1)
    admitted = await asyncio.wait_for(admission_task, timeout=1)

    assert admission_waited is True
    assert status_while_waiting == RunStatus.running.value
    assert events_while_waiting == []
    assert finalizing_while_waiting is True
    assert (await store.get(old.run_id))["status"] == RunStatus.success.value
    assert admitted.status == RunStatus.pending
    delivery = await events.list_events("thread-1", old.run_id, event_types=["run.delivery"])
    terminal = await events.list_events("thread-1", old.run_id, event_types=["run.end"])
    assert len(delivery) == 1
    assert delivery[0]["content"]["presented"] == 1
    assert len(terminal) == 1
    assert terminal[0]["content"]["messages"][0].content == "real worker output"
    assert terminal[0]["metadata"] == {
        "status": RunStatus.success.value,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_cancelling_waiting_admission_does_not_cancel_terminal_finalizer():
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-1")
    await manager.set_status(old.run_id, RunStatus.running)

    release_finalizer = asyncio.Event()
    finalizer = asyncio.create_task(release_finalizer.wait())
    old.task = finalizer
    await manager.set_status(
        old.run_id,
        RunStatus.success,
        persist=False,
        stage_terminal=True,
    )
    store.create_thread_operation_atomic = AsyncMock(
        wraps=store.create_thread_operation_atomic,
    )

    admission = asyncio.create_task(
        manager.create_or_reject(
            "thread-1",
            multitask_strategy="interrupt",
        )
    )
    await asyncio.sleep(0)
    assert admission.done() is False
    store.create_thread_operation_atomic.assert_not_awaited()

    admission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await admission

    assert finalizer.done() is False
    assert (await store.get(old.run_id))["status"] == RunStatus.running.value
    store.create_thread_operation_atomic.assert_not_awaited()

    release_finalizer.set()
    await finalizer
    await manager.set_finalizing(old.run_id, False)


@pytest.mark.anyio
async def test_waiting_admission_times_out_without_cancelling_terminal_finalizer():
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(
            heartbeat_enabled=True,
            grace_seconds=0,
        ),
    )
    old = await manager.create_or_reject("thread-finalizer-timeout")
    await manager.set_status(old.run_id, RunStatus.running)

    release_finalizer = asyncio.Event()
    finalizer = asyncio.create_task(release_finalizer.wait())
    old.task = finalizer
    await manager.set_status(
        old.run_id,
        RunStatus.success,
        persist=False,
        stage_terminal=True,
    )
    store.create_thread_operation_atomic = AsyncMock(
        wraps=store.create_thread_operation_atomic,
    )

    with pytest.raises(ConflictError, match="still finalizing"):
        await manager.create_or_reject(
            old.thread_id,
            multitask_strategy="interrupt",
        )

    assert finalizer.done() is False
    assert (await store.get(old.run_id))["status"] == RunStatus.running.value
    store.create_thread_operation_atomic.assert_not_awaited()

    release_finalizer.set()
    await finalizer
    await manager.set_finalizing(old.run_id, False)


@pytest.mark.anyio
async def test_interrupt_admission_backfills_a_cancelled_pending_worker():
    store = MemoryRunStore()
    events = MemoryRunEventStore()
    manager = _make_manager(store=store, event_store=events)
    old = await manager.create_or_reject("thread-1")
    old.task = asyncio.create_task(asyncio.sleep(3600))

    replacement = await manager.create_or_reject(
        "thread-1",
        multitask_strategy="interrupt",
    )
    await asyncio.gather(old.task, return_exceptions=True)
    await asyncio.sleep(0)

    assert replacement.status == RunStatus.pending
    assert old.task.cancelled()
    assert old.finalizing is False
    stored = await store.get(old.run_id)
    assert stored is not None
    assert stored["stop_reason"] == LOCAL_FINALIZER_PENDING_STOP_REASON
    delivery = await events.list_events("thread-1", old.run_id, event_types=["run.delivery"])
    terminal = await events.list_events("thread-1", old.run_id, event_types=["run.end"])
    assert delivery == []
    assert terminal == []

    assert await manager.recover_expired_local_finalizer(old) is True
    recovered_delivery = await events.list_events("thread-1", old.run_id, event_types=["run.delivery"])
    recovered_terminal = await events.list_events("thread-1", old.run_id, event_types=["run.end"])
    assert len(recovered_delivery) == 1
    assert len(recovered_terminal) == 1
    assert recovered_terminal[0]["metadata"] == {
        "status": "interrupted",
        "recovered": True,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_cancelled_admission_compensation_persists_a_no_worker_marker(
    monkeypatch,
):
    """The strict second CAS must retain liveness when the first write failed."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    record = await manager.create_or_reject("thread-cancelled-admission")
    monkeypatch.setattr(manager, "_persist_status", AsyncMock(return_value=False))

    await manager._close_cancelled_admission(record)

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_rollback_admission_keeps_pending_worker_terminal_event_authoritative(
    monkeypatch,
):
    """A pre-start rollback is an interruption, not a checkpoint rollback."""
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-1", user_id="run-owner")
    worker_waiting = asyncio.Event()
    worker_finalizing = asyncio.Event()
    release_worker_finalization = asyncio.Event()

    async def wait_before_start(*_args, **_kwargs):
        worker_waiting.set()
        await asyncio.Event().wait()

    original_set_status = manager.set_status

    async def pause_cancelled_worker_status(run_id, status, **kwargs):
        if run_id == old.run_id and status == RunStatus.interrupted and kwargs.get("stage_terminal") is True:
            worker_finalizing.set()
            await release_worker_finalization.wait()
        return await original_set_status(run_id, status, **kwargs)

    monkeypatch.setattr(manager, "wait_for_prior_finalizing", wait_before_start)
    monkeypatch.setattr(manager, "set_status", pause_cancelled_worker_status)
    rollback = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._rollback_to_pre_run_checkpoint",
        rollback,
    )
    worker_task = _start_output_worker(manager, old, events)
    await asyncio.wait_for(worker_waiting.wait(), timeout=1)

    replacement = await manager.create_or_reject(
        "thread-1",
        multitask_strategy="rollback",
        user_id="new-owner",
    )
    await asyncio.wait_for(worker_finalizing.wait(), timeout=1)
    terminal_before_worker_cleanup = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.end"],
    )
    release_worker_finalization.set()
    await asyncio.wait_for(worker_task, timeout=1)

    stored = await store.get(old.run_id)
    delivery = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.delivery"],
    )
    terminal = await events.list_events(
        "thread-1",
        old.run_id,
        event_types=["run.end"],
    )
    assert replacement.status == RunStatus.pending
    assert old.status == RunStatus.interrupted
    assert old.error is None
    assert old.finalizing is False
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["error"] == "Cancelled by newer run"
    assert terminal_before_worker_cleanup == []
    assert len(delivery) == 1
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": stored["status"],
        "authoritative": True,
    }
    rollback.assert_not_awaited()


@pytest.mark.anyio
async def test_cross_worker_admission_survives_terminal_event_store_failure():
    class FailingEventStore(MemoryRunEventStore):
        def __init__(self):
            super().__init__()
            self.attempted_types: list[str] = []

        async def put_if_absent(self, **kwargs):
            self.attempted_types.append(kwargs["event_type"])
            raise RuntimeError("event store unavailable")

    store = MemoryRunStore()
    events = FailingEventStore()
    expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    await store.put(
        "old-run",
        thread_id="thread-1",
        status="running",
        user_id="old-owner",
        owner_worker_id="dead-worker",
        lease_expires_at=expired,
        created_at=expired,
    )
    manager = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10),
    )

    admitted = await manager.create_or_reject(
        "thread-1",
        multitask_strategy="interrupt",
        user_id="new-owner",
    )

    assert admitted.status == RunStatus.pending
    assert (await store.get(admitted.run_id))["status"] == "pending"
    assert (await store.get("old-run"))["status"] == "interrupted"
    assert (await store.get("old-run"))["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
    assert events.attempted_types == ["run.delivery", "run.end"]


@pytest.mark.anyio
async def test_reject_blocks_reentrant_same_thread_locally():
    """reject must also block when a local in-memory active run exists."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    await manager.create_or_reject("thread-1", multitask_strategy="reject")

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="reject")


# ---------------------------------------------------------------------------
# create_or_reject — interrupt strategy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_interrupt_cancels_old_run_and_creates_new():
    """interrupt must cancel the previous active run and create a new one."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-1", multitask_strategy="reject")
    await manager.set_status(old.run_id, RunStatus.running)

    new = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")

    assert new.run_id != old.run_id
    assert new.status == RunStatus.pending

    # Old run must be interrupted locally
    assert old.status == RunStatus.interrupted
    assert old.abort_event.is_set()

    # Old run must be marked interrupted in-store (persist_status after local cancel)
    old_after = await store.get(old.run_id)
    assert old_after["status"] == "interrupted"


@pytest.mark.anyio
async def test_interrupt_creates_new_when_old_completed():
    """interrupt must succeed when the previous run already reached a terminal status."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    old = await manager.create_or_reject("thread-1")
    await manager.set_status(old.run_id, RunStatus.success)

    new = await manager.create_or_reject("thread-1", multitask_strategy="interrupt")
    assert new.run_id != old.run_id
    assert new.status == RunStatus.pending


@pytest.mark.anyio
async def test_interrupt_exhausted_retries_surface_as_conflict_error():
    """When all retry attempts collide with a unique violation, the loop must
    surface ConflictError (HTTP 409) — matching the reject branch — instead of
    leaking the raw IntegrityError (HTTP 500).

    Without the post-loop conversion, the last attempt's ``raise`` re-raises
    the IntegrityError, giving callers an inconsistent signal depending on
    which strategy they picked. The reject path already converts; this test
    pins the symmetric behaviour for interrupt/rollback.
    """
    import sqlite3

    class _AlwaysUniqueViolationStore(MemoryRunStore):
        """MemoryRunStore whose ``create_thread_operation_atomic`` always raises a
        real-flavoured unique-violation IntegrityError, simulating a worker
        that keeps losing the cross-worker race for the same thread."""

        def __init__(self):
            super().__init__()
            self.atomic_call_count = 0

        async def create_thread_operation_atomic(self, *args, **kwargs):
            self.atomic_call_count += 1
            err = sqlite3.IntegrityError("UNIQUE constraint failed: runs.uq_runs_thread_active")
            err.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE
            raise err

    store = _AlwaysUniqueViolationStore()
    manager = _make_manager(store=store)

    with pytest.raises(ConflictError, match="already has an active run"):
        await manager.create_or_reject("thread-1", multitask_strategy="interrupt")

    # Sanity: the loop actually retried 3 times before giving up.
    assert store.atomic_call_count == 3


@pytest.mark.anyio
async def test_atomic_recovery_keywords_do_not_break_a_strict_legacy_store():
    """Subclasses that retain the old strict signature remain callable."""

    class StrictLegacyAtomicStore(MemoryRunStore):
        async def create_thread_operation_atomic(
            self,
            run_id: str,
            *,
            thread_id: str,
            owner_worker_id: str,
            lease_expires_at: str | None,
            operation_kind: str = "run",
            multitask_strategy: str = "reject",
            assistant_id: str | None = None,
            user_id: str | None = None,
            model_name: str | None = None,
            metadata: dict | None = None,
            kwargs: dict | None = None,
            created_at: str | None = None,
            grace_seconds: int = 10,
            idempotency_key: str | None = None,
        ):
            return await super().create_thread_operation_atomic(
                run_id,
                thread_id=thread_id,
                owner_worker_id=owner_worker_id,
                lease_expires_at=lease_expires_at,
                operation_kind=operation_kind,
                multitask_strategy=multitask_strategy,
                assistant_id=assistant_id,
                user_id=user_id,
                model_name=model_name,
                metadata=metadata,
                kwargs=kwargs,
                created_at=created_at,
                grace_seconds=grace_seconds,
                idempotency_key=idempotency_key,
            )

    store = StrictLegacyAtomicStore()
    expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    await store.put(
        "legacy-run",
        thread_id="thread-legacy",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired,
        created_at=expired,
    )
    manager = _make_manager(
        store=store,
        on_orphans_recovered=AsyncMock(return_value=False),
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )

    admitted = await manager.create_or_reject(
        "thread-legacy",
        multitask_strategy="interrupt",
    )

    assert admitted.status == RunStatus.pending
    stored = await store.get("legacy-run")
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
    callback_records = manager._on_orphans_recovered.await_args.args[0]
    assert callback_records[0].stop_reason == ORPHAN_RECOVERY_STOP_REASON


# ---------------------------------------------------------------------------
# create_or_reject — run ownership metadata
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_record_stores_owner_and_lease():
    """Newly created runs must carry owner_worker_id and lease_expires_at (when heartbeat is on)."""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1")

    assert record.owner_worker_id == manager.worker_id
    assert isinstance(record.owner_worker_id, str) and len(record.owner_worker_id) > 0
    assert record.lease_expires_at is not None

    # Store row must also carry the fields
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["owner_worker_id"] == manager.worker_id
    assert stored["lease_expires_at"] is not None
    assert stored["operation_kind"] == ThreadOperationKind.run


@pytest.mark.anyio
async def test_store_row_roundtrips_ownership_fields():
    """Records hydrated from the store must surface ownership fields."""
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread-1")

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.owner_worker_id == manager.worker_id
    assert hydrated.lease_expires_at is not None
    assert hydrated.operation_kind == ThreadOperationKind.run


@pytest.mark.anyio
async def test_reconciliation_releases_expired_internal_operation_without_reporting_run():
    """Expired internal reservations release admission without becoming failed runs."""
    store = MemoryRunStore()
    expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    await store.put(
        "checkpoint-write-1",
        thread_id="thread-1",
        status="pending",
        operation_kind=ThreadOperationKind.checkpoint_write,
        owner_worker_id="dead-worker",
        lease_expires_at=expired,
        created_at=expired,
    )
    manager = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(error="owner expired")

    assert recovered == []
    stored = await store.get("checkpoint-write-1")
    assert stored is not None
    assert stored["status"] == "error"


# ---------------------------------------------------------------------------
# reconcile_orphaned_inflight_runs — lease-based
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciliation_claims_expired_lease_runs():
    """A run with an expired lease must be reclaimed as orphaned."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # Insert a run with an already-expired lease
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "expired-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-dead",
        lease_expires_at=expired_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == "expired-run"
    assert recovered[0].status == RunStatus.error

    stored = await store.get("expired-run")
    assert stored["status"] == "error"


@pytest.mark.anyio
async def test_reconciliation_skips_active_lease_runs():
    """A run with a still-valid lease must NOT be reclaimed."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # Insert a run with a still-valid lease
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "live-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-alive",
        lease_expires_at=valid_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    # Live run's lease is still valid — must not be reclaimed
    assert all(r.run_id != "live-run" for r in recovered)

    stored = await store.get("live-run")
    assert stored["status"] == "running"


@pytest.mark.anyio
async def test_reconciliation_skips_candidate_when_owner_renews_lease_after_scan():
    """A renewed lease between scan and claim must keep the run active."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put(
        "race-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-alive",
        lease_expires_at=expired_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )
    original_list = store.list_inflight_with_expired_lease

    async def list_then_owner_renews(*, before=None, grace_seconds=10):
        rows = [dict(row) for row in await original_list(before=before, grace_seconds=grace_seconds)]
        renewed_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        updated = await store.update_lease(
            "race-run",
            owner_worker_id="worker-alive",
            lease_expires_at=renewed_lease,
        )
        assert updated is True
        return rows

    store.list_inflight_with_expired_lease = list_then_owner_renews
    manager = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert recovered == []
    stored = await store.get("race-run")
    assert stored["status"] == "running"
    assert datetime.fromisoformat(stored["lease_expires_at"]) > datetime.now(UTC)


@pytest.mark.anyio
async def test_concurrent_reconcilers_report_one_successful_claim():
    """Two reapers scanning the same candidate must report one recovery."""
    store = MemoryRunStore()
    grace = 10
    run_id = "contended-orphan"
    await store.put(
        run_id,
        thread_id="thread-1",
        status="running",
        owner_worker_id="worker-dead",
        lease_expires_at=(datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat(),
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    original_scan = store.list_inflight_with_expired_lease
    both_scanned = asyncio.Event()
    scan_lock = asyncio.Lock()
    scan_count = 0

    async def synchronized_scan(*, before=None, grace_seconds=10):
        nonlocal scan_count
        rows = [dict(row) for row in await original_scan(before=before, grace_seconds=grace_seconds)]
        async with scan_lock:
            scan_count += 1
            if scan_count == 2:
                both_scanned.set()
        await asyncio.wait_for(both_scanned.wait(), timeout=1)
        return rows

    store.list_inflight_with_expired_lease = synchronized_scan
    managers = [
        _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace)),
        _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace)),
    ]

    results = await asyncio.gather(*(manager.reconcile_orphaned_inflight_runs(error="orphaned") for manager in managers))

    assert sorted(len(recovered) for recovered in results) == [0, 1]
    assert [record.run_id for recovered in results for record in recovered] == [run_id]
    row = await store.get(run_id)
    assert row is not None
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_reconciliation_claims_null_lease_runs():
    """Pre-ownership rows (NULL lease) must be reclaimed."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    await store.put(
        "legacy-run",
        thread_id="thread-1",
        status="running",
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == "legacy-run"


@pytest.mark.anyio
async def test_heartbeat_disabled_crashed_run_reclaimed_immediately():
    """Single-worker regression: when heartbeat is off, a crashed run must be
    reclaimed on the next restart without waiting for lease expiry.

    The run is created with lease_expires_at=NULL (no heartbeat => no lease),
    so reconciliation treats it as an orphan and reclaims it right away —
    preserving the pre-ownership recovery latency.
    """
    store = MemoryRunStore()
    # Worker A: heartbeat disabled (single-worker default)
    manager_a = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))
    record = await manager_a.create("thread-1")
    await manager_a.set_status(record.run_id, RunStatus.running)

    # Verify the run was stored WITHOUT a lease (heartbeat off)
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["lease_expires_at"] is None

    # Simulate crash: drop manager_a's local state, build a fresh manager
    # (same store) as if Worker A restarted.
    manager_b = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))

    # Reconciliation must reclaim the run IMMEDIATELY — no lease to wait out.
    recovered = await manager_b.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert len(recovered) == 1
    assert recovered[0].run_id == record.run_id
    assert recovered[0].status == RunStatus.error


@pytest.mark.anyio
async def test_reconciliation_skips_locally_active_runs():
    """An active local run (owned by this worker) must NOT be reclaimed even with an expired lease."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    # Create a live local run
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    # Its lease hasn't expired yet, so this is mostly testing the local-ownership guard
    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert all(r.run_id != record.run_id for r in recovered)


@pytest.mark.anyio
async def test_reconciliation_returns_empty_when_no_orphaned_runs():
    """Reconciliation must return empty when there are no orphaned runs."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    recovered = await manager.reconcile_orphaned_inflight_runs(
        error="Gateway restarted before this run reached a durable final state.",
    )

    assert recovered == []


@pytest.mark.anyio
async def test_periodic_reconciliation_notifies_recovery_callback():
    """Periodic recovery must hand terminalized rows to Gateway orchestration."""
    store = MemoryRunStore()
    on_orphans_recovered = AsyncMock()
    manager = _make_manager(
        store=store,
        on_orphans_recovered=on_orphans_recovered,
    )
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "periodic-orphan",
        thread_id="thread-1",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
    )

    await manager._reconcile_orphans_periodic()
    await asyncio.sleep(0)

    on_orphans_recovered.assert_awaited_once()
    recovered = on_orphans_recovered.await_args.args[0]
    assert [record.run_id for record in recovered] == ["periodic-orphan"]
    assert recovered[0].status == RunStatus.error
    assert recovered[0].stop_reason == ORPHAN_RECOVERY_STOP_REASON
    stored = await store.get("periodic-orphan")
    assert stored is not None
    assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_periodic_reconciliation_logs_recovered_run_ids_when_callback_fails(caplog):
    """Callback failures must identify every recovered run in the warning."""
    store = MemoryRunStore()
    on_orphans_recovered = AsyncMock(side_effect=RuntimeError("callback failed"))
    manager = _make_manager(
        store=store,
        on_orphans_recovered=on_orphans_recovered,
    )
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    created_at = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    for run_id in ("periodic-orphan-1", "periodic-orphan-2"):
        await store.put(
            run_id,
            thread_id=f"thread-{run_id}",
            status="running",
            owner_worker_id="dead-worker",
            lease_expires_at=expired_lease,
            created_at=created_at,
        )

    with caplog.at_level("WARNING", logger="deerflow.runtime.runs.manager"):
        await manager._reconcile_orphans_periodic()
        await asyncio.sleep(0)

    assert "Periodic orphan recovery callback failed for 2 run(s)" in caplog.text
    assert "periodic-orphan-1" in caplog.text
    assert "periodic-orphan-2" in caplog.text


@pytest.mark.anyio
async def test_periodic_terminalization_does_not_block_lease_renewal_or_shutdown():
    """The real heartbeat loop must keep renewing during a slow callback."""
    store = MemoryRunStore()
    callback_started = asyncio.Event()
    callback_release = asyncio.Event()
    callback_finished = asyncio.Event()

    async def on_orphans_recovered(_recovered):
        callback_started.set()
        await callback_release.wait()
        callback_finished.set()

    manager = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True, lease_seconds=5),
        on_orphans_recovered=on_orphans_recovered,
    )
    active = await manager.create_or_reject("active-thread")
    await manager.set_status(active.run_id, RunStatus.running)
    original_expiry = active.lease_expires_at
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "periodic-orphan",
        thread_id="orphan-thread",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
        created_at=expired_lease,
    )

    await manager.start_heartbeat()
    await asyncio.wait_for(callback_started.wait(), timeout=4.5)
    expiry_during_callback = active.lease_expires_at
    await asyncio.sleep(1.2)

    assert expiry_during_callback != original_expiry
    assert active.lease_expires_at != expiry_during_callback
    assert callback_finished.is_set() is False

    shutdown_task = asyncio.create_task(manager.shutdown(timeout=1.0))
    await asyncio.sleep(0)
    assert shutdown_task.done() is False
    callback_release.set()
    await asyncio.wait_for(shutdown_task, timeout=1.0)
    assert callback_finished.is_set() is True


@pytest.mark.anyio
async def test_periodic_store_scan_does_not_block_real_heartbeat_loop():
    """A slow orphan scan must not stall later lease-renewal cycles."""

    class SlowScanStore(MemoryRunStore):
        def __init__(self):
            super().__init__()
            self.scan_started = asyncio.Event()
            self.scan_release = asyncio.Event()

        async def list_inflight_with_expired_lease(
            self,
            *,
            before=None,
            grace_seconds=10,
        ):
            self.scan_started.set()
            await self.scan_release.wait()
            return await super().list_inflight_with_expired_lease(
                before=before,
                grace_seconds=grace_seconds,
            )

    store = SlowScanStore()
    manager = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True, lease_seconds=5),
    )
    active = await manager.create_or_reject("active-thread")
    await manager.set_status(active.run_id, RunStatus.running)

    await manager.start_heartbeat()
    await asyncio.wait_for(store.scan_started.wait(), timeout=4.5)
    expiry_during_scan = active.lease_expires_at
    await asyncio.sleep(1.2)

    assert active.lease_expires_at != expiry_during_scan

    store.scan_release.set()
    await manager.stop_heartbeat()
    await manager._drain_orphan_recovery_task(timeout=0.5)


@pytest.mark.anyio
async def test_periodic_recovery_is_single_flight():
    """A second trigger must not create another recovery pipeline."""
    store = MemoryRunStore()
    callback_started = asyncio.Event()
    callback_release = asyncio.Event()
    callback_calls = 0

    async def on_orphans_recovered(_recovered):
        nonlocal callback_calls
        callback_calls += 1
        callback_started.set()
        await callback_release.wait()

    manager = _make_manager(
        store=store,
        on_orphans_recovered=on_orphans_recovered,
    )
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "periodic-orphan",
        thread_id="orphan-thread",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
        created_at=expired_lease,
    )

    manager._schedule_orphan_reconciliation()
    await asyncio.wait_for(callback_started.wait(), timeout=0.5)
    first_task = manager._orphan_recovery_task
    manager._schedule_orphan_reconciliation()

    assert manager._orphan_recovery_task is first_task
    assert callback_calls == 1

    callback_release.set()
    await asyncio.wait_for(first_task, timeout=0.5)


@pytest.mark.anyio
async def test_shutdown_cancels_recovery_that_exceeds_drain_budget():
    """The pending -> cancel -> gather branch must observe callback cancellation."""
    store = MemoryRunStore()
    callback_started = asyncio.Event()
    callback_cancelled = asyncio.Event()

    async def on_orphans_recovered(_recovered):
        callback_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            callback_cancelled.set()
            raise

    manager = _make_manager(
        store=store,
        on_orphans_recovered=on_orphans_recovered,
    )
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "periodic-orphan",
        thread_id="orphan-thread",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
        created_at=expired_lease,
    )
    manager._schedule_orphan_reconciliation()
    await asyncio.wait_for(callback_started.wait(), timeout=0.5)

    await manager.shutdown(timeout=0.01)

    assert callback_cancelled.is_set()
    assert manager._orphan_recovery_task is None


@pytest.mark.anyio
async def test_shutdown_applies_shared_deadline_to_heartbeat_stop():
    """A stuck heartbeat must not receive a separate five-second budget."""
    manager = _make_manager(
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    heartbeat_cancelled = asyncio.Event()

    async def stuck_heartbeat():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            heartbeat_cancelled.set()
            raise

    manager._heartbeat_stop = asyncio.Event()
    manager._heartbeat_task = asyncio.create_task(stuck_heartbeat())
    started = asyncio.get_running_loop().time()

    await manager.shutdown(timeout=0.01)

    elapsed = asyncio.get_running_loop().time() - started
    assert heartbeat_cancelled.is_set()
    assert elapsed < 0.5


# ---------------------------------------------------------------------------
# Lease heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_heartbeat_renews_active_run_leases():
    """Heartbeat must extend the lease on active runs owned by this worker."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    original_lease = record.lease_expires_at
    assert original_lease is not None

    # Start heartbeat and let it tick once
    await manager.start_heartbeat()
    await asyncio.sleep(0.2)  # heartbeat interval = 10s, too long; manually renew

    await manager._renew_leases()
    await manager.stop_heartbeat()

    assert record.lease_expires_at is not None
    # Lease should have been extended
    assert record.lease_expires_at >= original_lease


@pytest.mark.anyio
async def test_terminal_lease_renewal_requires_exact_live_local_finalizer_marker():
    store = MemoryRunStore()
    live = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    next_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "local-finalizer",
        thread_id="thread-1",
        status=RunStatus.interrupted.value,
        owner_worker_id="worker-a",
        lease_expires_at=live,
        stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON,
    )
    await store.put(
        "ordinary-terminal",
        thread_id="thread-2",
        status=RunStatus.interrupted.value,
        owner_worker_id="worker-a",
        lease_expires_at=live,
        stop_reason=ORPHAN_RECOVERY_STOP_REASON,
    )

    assert (
        await store.renew_lease(
            "local-finalizer",
            owner_worker_id="worker-a",
            lease_expires_at=next_lease,
        )
    ).renewed is True
    assert (
        await store.renew_lease(
            "ordinary-terminal",
            owner_worker_id="worker-a",
            lease_expires_at=next_lease,
        )
    ).renewed is False

    store._runs["local-finalizer"]["lease_expires_at"] = expired
    assert (
        await store.renew_lease(
            "local-finalizer",
            owner_worker_id="worker-a",
            lease_expires_at=next_lease,
        )
    ).renewed is False
    claimed = await store.claim_expired_local_finalizer(
        "local-finalizer",
        owner_worker_id="worker-b",
        recovery_stop_reason=ORPHAN_RECOVERY_STOP_REASON,
        grace_seconds=0,
    )
    assert claimed is not None
    assert claimed["owner_worker_id"] == "worker-b"
    assert claimed["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
    assert (
        await store.renew_lease(
            "local-finalizer",
            owner_worker_id="worker-a",
            lease_expires_at=next_lease,
        )
    ).renewed is False


@pytest.mark.anyio
async def test_expired_local_finalizer_marker_fences_its_live_task():
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    old = await manager.create_or_reject("thread-expired-local-finalizer")
    await manager.set_status(old.run_id, RunStatus.running)
    cancellation_observed = asyncio.Event()
    release = asyncio.Event()

    async def slow_finalizer() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_observed.set()
            await release.wait()

    old.task = asyncio.create_task(slow_finalizer())
    await asyncio.sleep(0)
    await manager.create_or_reject(
        old.thread_id,
        multitask_strategy="interrupt",
    )
    await asyncio.wait_for(cancellation_observed.wait(), timeout=1)
    assert old.stop_reason == LOCAL_FINALIZER_PENDING_STOP_REASON
    assert old.finalizing is True

    # The worker may already have confirmed the terminal RunRow while it is
    # still completing run.end/hooks/bridge END.  A failed marker renewal must
    # still re-read ownership and fence that remaining finalizer work.
    old.terminal_status_staged = False
    old.terminal_status_persisted = True

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    old.lease_expires_at = expired
    store._runs[old.run_id]["lease_expires_at"] = expired
    await manager._renew_leases()

    assert old.ownership_lost is True
    await asyncio.gather(old.task, return_exceptions=True)


@pytest.mark.anyio
async def test_heartbeat_renews_pending_run_before_task_is_spawned():
    """A run sitting in ``pending`` between ``create_thread_operation_atomic`` and task
    spawn must still have its lease renewed.

    Pre-fix the renewal filter required ``record.task is not None``, so a
    pending run with no task yet (the brief window after
    ``create_thread_operation_atomic`` inserts the row before the worker layer spawns
    the agent task) was silently skipped. If that window stretched past
    ``lease_seconds`` — e.g. event-loop saturation, slow checkpoint
    hydrate — peer reconciliation reclaimed the run as an orphan and
    marked it ``error`` even though this worker still intended to run it.
    """
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    record = await manager.create_or_reject("thread-1")
    assert record.status == RunStatus.pending
    # No task has been spawned — this is the regression sentinel.
    assert record.task is None

    original_lease = record.lease_expires_at
    assert original_lease is not None

    # Force a measurable gap so the renewed lease strictly post-dates the
    # original — without this the two timestamps land in the same
    # microsecond on fast hosts and the strict comparison fails trivially.
    await asyncio.sleep(0.001)

    store.update_lease = AsyncMock(wraps=store.update_lease)

    await manager._renew_leases()

    store.update_lease.assert_awaited_once()
    assert record.lease_expires_at is not None
    assert record.lease_expires_at > original_lease


@pytest.mark.anyio
async def test_try_start_fences_expired_owner_before_agent_execution():
    """The startup CAS must reject a stale worker before Agent side effects."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create_or_reject("thread-expired-start")
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    record.lease_expires_at = expired
    stored = await store.get(record.run_id)
    assert stored is not None
    stored["lease_expires_at"] = expired

    outcome = await manager.try_start(record.run_id)

    assert outcome.value == "cancelled"
    assert record.ownership_lost is True
    assert record.abort_event.is_set()
    assert record.status == RunStatus.error
    assert stored["status"] == RunStatus.pending.value


@pytest.mark.anyio
async def test_durable_cancel_before_start_blocks_agent_without_fencing_owner():
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    ownership = _lease_config(heartbeat_enabled=True)
    owner = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-a",
        run_ownership_config=ownership,
    )
    peer = _make_manager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=ownership,
    )
    record = await owner.create_or_reject(
        "thread-cancel-before-start",
        user_id="run-owner",
    )
    assert await peer.cancel(record.run_id, action="rollback") == CancelOutcome.requested
    agent_factory_called = False

    def agent_factory(**_kwargs):
        nonlocal agent_factory_called
        agent_factory_called = True
        raise AssertionError("durably cancelled run built the Agent")

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    task = asyncio.create_task(
        run_agent(
            bridge,
            owner,
            record,
            ctx=RunContext(checkpointer=None, event_store=events),
            agent_factory=agent_factory,
            graph_input={},
            config={},
        )
    )
    record.task = task
    await asyncio.wait_for(task, timeout=1)

    stored = await store.get(record.run_id)
    terminal = await events.list_events(
        record.thread_id,
        record.run_id,
        event_types=["run.end"],
    )
    assert agent_factory_called is False
    assert record.ownership_lost is False
    assert record.status == RunStatus.interrupted
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": RunStatus.interrupted.value,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_local_cancel_terminalizing_during_start_does_not_fence_owner():
    """A same-owner cancel may persist before the failed startup CAS is read."""
    store = MemoryRunStore()
    owner = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await owner.create_or_reject("thread-local-cancel-before-start")
    original_start = store.start_run_if_owned

    async def cancel_before_start_returns(run_id, *, owner_worker_id):
        assert await owner.cancel(run_id, action="interrupt") == CancelOutcome.cancelled
        return await original_start(run_id, owner_worker_id=owner_worker_id)

    store.start_run_if_owned = cancel_before_start_returns

    outcome = await owner.try_start(record.run_id)
    stored = await store.get(record.run_id)

    assert outcome.value == "cancelled"
    assert record.ownership_lost is False
    assert record.abort_event.is_set()
    assert record.status == RunStatus.interrupted
    assert record.durable_terminal_status == RunStatus.interrupted
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value


@pytest.mark.anyio
async def test_heartbeat_renews_terminal_staged_run_until_status_is_durable():
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=config,
    )
    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    release_finalizer = asyncio.Event()
    finalizer = asyncio.create_task(release_finalizer.wait())
    record.task = finalizer
    await manager.set_status(
        record.run_id,
        RunStatus.success,
        persist=False,
        stage_terminal=True,
    )
    original_lease = record.lease_expires_at
    assert original_lease is not None
    # Windows wall-clock timestamps can have coarser granularity than the
    # event-loop clock, so leave enough room for a strict ISO comparison.
    await asyncio.sleep(0.02)
    store.update_lease = AsyncMock(wraps=store.update_lease)

    await manager._renew_leases()

    store.update_lease.assert_awaited_once()
    assert record.lease_expires_at is not None
    assert record.lease_expires_at > original_lease
    assert record.terminal_status_staged is True
    assert record.terminal_status_persisted is False
    assert record.ownership_lost is False

    assert await manager.persist_current_status(record.run_id) is True
    assert record.terminal_status_staged is False
    assert record.terminal_status_persisted is True

    release_finalizer.set()
    await finalizer
    await manager.set_finalizing(record.run_id, False)


@pytest.mark.anyio
async def test_heartbeat_defers_to_inflight_terminal_owner_cas():
    """The database CAS, not a stale cached deadline, arbitrates finalization."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create_or_reject("thread-terminal-cas-race")
    await manager.set_status(record.run_id, RunStatus.running)
    finalizer = asyncio.create_task(asyncio.Event().wait())
    record.task = finalizer
    await manager.set_status(
        record.run_id,
        RunStatus.success,
        persist=False,
        stage_terminal=True,
    )

    cas_started = asyncio.Event()
    release_cas = asyncio.Event()
    original_finalize = store.finalize_if_owned_and_not_cancelled

    async def paused_finalize(*args, **kwargs):
        cas_started.set()
        await release_cas.wait()
        return await original_finalize(*args, **kwargs)

    store.finalize_if_owned_and_not_cancelled = paused_finalize
    persist_task = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    await asyncio.wait_for(cas_started.wait(), timeout=1)
    record.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    try:
        await manager._renew_leases()

        assert record.terminal_status_persistence_inflight == 1
        assert record.ownership_lost is False
        assert finalizer.done() is False

        release_cas.set()
        assert await asyncio.wait_for(persist_task, timeout=1) is None
        stored = await store.get(record.run_id)
        assert stored is not None and stored["status"] == RunStatus.success.value
        assert record.terminal_status_persistence_inflight == 0
        assert record.terminal_status_persisted is True
        assert record.ownership_lost is False
    finally:
        release_cas.set()
        if not persist_task.done():
            await persist_task
        finalizer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await finalizer


@pytest.mark.anyio
@pytest.mark.parametrize("expiry_path", ["already_expired", "renewal_timeout"])
async def test_heartbeat_adopts_same_owner_terminal_commit_before_expiry_fence(expiry_path):
    """A committed terminal CAS must keep its final event publisher alive."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create_or_reject("thread-terminal-expiry-race")
    await manager.set_status(record.run_id, RunStatus.running)

    finalizer = asyncio.create_task(asyncio.Event().wait())
    record.task = finalizer
    await manager.set_status(
        record.run_id,
        RunStatus.success,
        persist=False,
        stage_terminal=True,
    )
    assert await store.update_status_if_owned(
        record.run_id,
        RunStatus.success.value,
        owner_worker_id="worker-a",
    )

    if expiry_path == "already_expired":
        record.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    else:
        record.lease_expires_at = (datetime.now(UTC) + timedelta(milliseconds=20)).isoformat()

        async def block_renewal_until_deadline(*_args, **_kwargs):
            await asyncio.Event().wait()

        store.renew_lease = block_renewal_until_deadline

    try:
        await asyncio.wait_for(manager._renew_leases(), timeout=1)

        assert record.ownership_lost is False
        assert record.abort_event.is_set() is False
        assert finalizer.done() is False
        assert record.durable_terminal_status == RunStatus.success
        assert record.terminal_status_staged is False
        assert record.terminal_status_persisted is True
    finally:
        finalizer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await finalizer


@pytest.mark.anyio
async def test_heartbeat_skips_same_owner_terminal_fence_during_rollback():
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled

    release_finalizer = asyncio.Event()
    record.task = asyncio.create_task(release_finalizer.wait())
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="Rolled back by user",
        persist=False,
        stage_terminal=True,
    )
    store.update_lease = AsyncMock(wraps=store.update_lease)

    await manager._renew_leases()

    store.update_lease.assert_not_awaited()
    assert record.ownership_lost is False
    assert await manager.persist_current_status(record.run_id) is True
    row = await store.get(record.run_id)
    assert row is not None
    assert row["status"] == RunStatus.error.value
    assert row["error"] == "Rolled back by user"

    release_finalizer.set()
    await record.task
    await manager.set_finalizing(record.run_id, False)


@pytest.mark.anyio
async def test_transient_renewal_exception_before_deadline_keeps_run_alive():
    """A renewal error is retryable while the last confirmed lease is valid."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))
    original_update_lease = store.update_lease
    attempts = 0

    async def fail_once_then_renew(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary database outage")
        return await original_update_lease(*args, **kwargs)

    store.update_lease = fail_once_then_renew
    original_expiry = record.lease_expires_at

    try:
        await manager._renew_leases()

        assert record.abort_event.is_set() is False
        assert record.task.done() is False
        assert record.lease_expires_at == original_expiry

        await asyncio.sleep(0.02)
        await manager._renew_leases()

        assert attempts == 2
        assert record.abort_event.is_set() is False
        assert record.task.done() is False
        assert record.lease_expires_at is not None
        assert original_expiry is not None
        assert record.lease_expires_at > original_expiry
    finally:
        record.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await record.task


@pytest.mark.anyio
async def test_renewal_exception_through_confirmed_expiry_fail_stops_run():
    """The owner must stop once errors outlive its last confirmed lease."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))
    attempts = 0

    async def fail_renewal(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("database unreachable")

    store.update_lease = fail_renewal

    await manager._renew_leases()
    assert record.abort_event.is_set() is False
    assert record.task.done() is False

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired

    await manager._renew_leases()
    await asyncio.sleep(0)

    assert attempts == 1
    assert record.ownership_lost is True
    assert record.abort_event.is_set() is True
    assert record.task.cancelled()


@pytest.mark.anyio
async def test_hung_renewal_is_bounded_by_confirmed_lease_deadline():
    """A blocked store call cannot keep execution alive beyond the lease."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))
    near_expiry = (datetime.now(UTC) + timedelta(milliseconds=50)).isoformat()
    record.lease_expires_at = near_expiry
    store._runs[record.run_id]["lease_expires_at"] = near_expiry

    async def hang_renewal(*_args, **_kwargs):
        await asyncio.Event().wait()

    store.update_lease = hang_renewal

    await asyncio.wait_for(manager._renew_leases(), timeout=1)
    await asyncio.sleep(0)

    assert record.ownership_lost is True
    assert record.abort_event.is_set() is True
    assert record.task.cancelled()


@pytest.mark.anyio
async def test_late_successful_renewal_still_fences_local_run():
    """A renewal confirmed after the old deadline cannot revive local work."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))
    near_expiry = (datetime.now(UTC) + timedelta(milliseconds=50)).isoformat()
    record.lease_expires_at = near_expiry
    store._runs[record.run_id]["lease_expires_at"] = near_expiry
    original_update_lease = store.update_lease

    async def renew_after_timeout_cancellation(*args, **kwargs):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Simulate a store operation that commits successfully despite the
            # caller's deadline cancellation.
            pass
        return await original_update_lease(*args, **kwargs)

    store.update_lease = renew_after_timeout_cancellation

    await asyncio.wait_for(manager._renew_leases(), timeout=1)
    await asyncio.sleep(0)

    row = await store.get(record.run_id)
    assert row is not None
    assert row["lease_expires_at"] > near_expiry
    assert record.lease_expires_at == near_expiry
    assert record.ownership_lost is True
    assert record.abort_event.is_set() is True
    assert record.task.cancelled()


@pytest.mark.anyio
async def test_heartbeat_skips_runs_not_owned_by_this_worker():
    """Heartbeat must only renew leases for runs owned by this worker."""
    config = _lease_config(lease_seconds=30, heartbeat_enabled=True)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    # Create a run owned by a different worker
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "other-worker-run",
        thread_id="thread-1",
        status="running",
        owner_worker_id="other-worker",
        lease_expires_at=old_lease,
        created_at=(datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    )

    await manager._renew_leases()

    stored = await store.get("other-worker-run")
    # Lease should be unchanged (other worker's run)
    assert stored["lease_expires_at"] == old_lease


@pytest.mark.anyio
async def test_heartbeat_not_started_when_disabled():
    """When heartbeat_enabled is False, start_heartbeat must be a no-op."""
    config = _lease_config(heartbeat_enabled=False)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    assert manager.heartbeat_enabled is False
    await manager.start_heartbeat()
    assert manager._heartbeat_task is None
    assert manager._heartbeat_stop is None


# ---------------------------------------------------------------------------
# cancel with cross-worker lease awareness
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_local_run_succeeds():
    """Cancel must succeed for a locally-owned active run."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    result = await manager.cancel(record.run_id)
    assert result == CancelOutcome.cancelled
    assert record.status == RunStatus.interrupted


@pytest.mark.anyio
async def test_cancel_unknown_run_returns_false():
    """Cancel must return not_active_locally for a run not known to this worker (heartbeat off)."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)

    result = await manager.cancel("nonexistent-run")
    assert result == CancelOutcome.not_active_locally


@pytest.mark.anyio
async def test_cancel_idempotent():
    """Cancel must return cancelled when the run is already interrupted."""
    store = MemoryRunStore()
    manager = _make_manager(store=store)
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.interrupted)

    result = await manager.cancel(record.run_id)
    assert result == CancelOutcome.cancelled


# ---------------------------------------------------------------------------
# GATEWAY_WORKERS=1 backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_worker_default_config_behavior_unchanged():
    """With default config (heartbeat_enabled=False), behavior must match pre-ownership code."""
    config = _lease_config(heartbeat_enabled=False)
    store = MemoryRunStore()
    manager = _make_manager(store=store, run_ownership_config=config)

    # Create runs, cancel, create_or_reject — all must work
    r1 = await manager.create("thread-1")
    assert r1.owner_worker_id is not None

    r2 = await manager.create_or_reject("thread-2", multitask_strategy="reject")
    assert r2.owner_worker_id is not None

    await manager.cancel(r2.run_id)
    stored = await store.get(r2.run_id)
    assert stored["status"] == "interrupted"


@pytest.mark.anyio
async def test_manager_without_run_ownership_config():
    """Manager without run_ownership_config must still work (backward compat)."""
    store = MemoryRunStore()
    manager = RunManager(store=store)  # no run_ownership_config

    record = await manager.create_or_reject("thread-1")
    assert record is not None
    assert record.owner_worker_id is not None  # always set, even without config

    # Heartbeat must be a no-op without config
    assert manager.heartbeat_enabled is False
    await manager.start_heartbeat()
    assert manager._heartbeat_task is None


# ---------------------------------------------------------------------------
# worker_id uniqueness
# ---------------------------------------------------------------------------


def test_worker_id_is_generated():
    """worker_id must be a non-empty string containing hostname."""
    wid = _generate_worker_id()
    assert isinstance(wid, str)
    assert len(wid) > 0
    assert ":" in wid


def test_two_managers_have_different_default_ids():
    """Two managers without explicit worker_id must get unique ids."""
    m1 = RunManager()
    m2 = RunManager()
    assert m1.worker_id != m2.worker_id


# ---------------------------------------------------------------------------
# Store atomic methods
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_thread_operation_atomic_reject_prevents_duplicate():
    """Atomic thread-operation creation must reject a duplicate."""
    store = MemoryRunStore()
    config = _lease_config()

    store.create_thread_operation_atomic = AsyncMock(wraps=store.create_thread_operation_atomic)

    await store.create_thread_operation_atomic(
        run_id="run-1",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="already has an active run"):
        await store.create_thread_operation_atomic(
            run_id="run-2",
            thread_id="thread-1",
            owner_worker_id="w2",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="reject",
            grace_seconds=config.grace_seconds,
        )


@pytest.mark.anyio
async def test_create_thread_operation_atomic_interrupt_claims_and_creates():
    """Atomic thread-operation creation with interrupt must claim and replace."""
    store = MemoryRunStore()
    config = _lease_config()
    # Create an active run with an expired lease (simulating a crashed worker)
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()

    await store.create_thread_operation_atomic(
        run_id="run-old",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=expired_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_thread_operation_atomic(
        run_id="run-new",
        thread_id="thread-1",
        owner_worker_id="w2",
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="interrupt",
        grace_seconds=config.grace_seconds,
    )

    assert new_row["run_id"] == "run-new"
    assert new_row["status"] == "pending"
    assert len(claimed) == 1
    assert claimed[0]["run_id"] == "run-old"

    # Old run must be interrupted in-store
    old_row = await store.get("run-old")
    assert old_row["status"] == "interrupted"


@pytest.mark.anyio
async def test_create_thread_operation_atomic_interrupt_rejects_other_worker_valid_lease():
    """Interrupt must raise ConflictError when a valid-lease run is owned by another worker.

    The partial unique index ``uq_runs_thread_active`` would reject the INSERT
    anyway; surfacing ConflictError here gives the caller a clean signal
    instead of a futile retry loop on IntegrityError.
    """
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_thread_operation_atomic(
        run_id="valid-lease-run",
        thread_id="thread-1",
        owner_worker_id="other-worker",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="another worker"):
        await store.create_thread_operation_atomic(
            run_id="run-new",
            thread_id="thread-1",
            owner_worker_id="w2",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="interrupt",
            grace_seconds=config.grace_seconds,
        )

    # The valid-lease run must be untouched (transaction rolled back).
    old_row = await store.get("valid-lease-run")
    assert old_row["status"] == "pending"
    assert old_row["owner_worker_id"] == "other-worker"


@pytest.mark.anyio
async def test_create_thread_operation_atomic_interrupt_allows_self_owned_valid_lease():
    """Interrupt must succeed when the existing valid-lease run is owned by this worker."""
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_thread_operation_atomic(
        run_id="self-run",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_thread_operation_atomic(
        run_id="run-new",
        thread_id="thread-1",
        owner_worker_id="w1",  # same worker
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="interrupt",
        grace_seconds=config.grace_seconds,
    )

    assert new_row["run_id"] == "run-new"
    assert len(claimed) == 1
    assert claimed[0]["run_id"] == "self-run"
    assert claimed[0]["status"] == "interrupted"


@pytest.mark.anyio
async def test_create_thread_operation_atomic_interrupt_rolls_back_earlier_mutations_on_conflict():
    """Interrupt must not leave earlier candidates interrupted when a later
    candidate raises ConflictError.

    Mirrors the SQL store's transactional semantics: the whole interrupt pass
    is one transaction, so a raise on any candidate must roll back mutations
    already applied to earlier candidates. Without this, the memory store
    diverges from SQL (which the production path uses), and the
    test_multi_worker_run_ownership.py suite gives false confidence by
    passing against memory while SQL would behave differently.

    Setup: expired-lease run (interruptible) inserted FIRST, then a
    valid-lease run owned by another worker. Iteration order means the
    expired run is mutated before the valid-lease run raises — so a naive
    single-pass implementation would leave the expired run interrupted.
    """
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    # Seed both active rows directly via ``put`` (bypassing atomic operation creation's
    # reject check, which would refuse the second row). Insert the
    # interruptible run first so dict iteration visits it first — that's the
    # ordering that exposes the half-interrupted divergence in a naive
    # single-pass implementation.
    await store.put(
        "expired-run",
        thread_id="thread-1",
        status="pending",
        owner_worker_id="old-worker",
        lease_expires_at=expired_lease,
    )
    await store.put(
        "valid-lease-run",
        thread_id="thread-1",
        status="pending",
        owner_worker_id="other-worker",
        lease_expires_at=valid_lease,
    )

    with pytest.raises(ConflictError, match="another worker"):
        await store.create_thread_operation_atomic(
            run_id="run-new",
            thread_id="thread-1",
            owner_worker_id="w1",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="interrupt",
            grace_seconds=config.grace_seconds,
        )

    # The expired run must be UNTOUCHED — the interrupt pass must roll back
    # on ConflictError, not leave a half-interrupted store.
    expired_row = await store.get("expired-run")
    assert expired_row["status"] == "pending"
    assert expired_row["owner_worker_id"] == "old-worker"
    assert expired_row["error"] is None

    # The valid-lease run that caused the conflict is also untouched.
    valid_row = await store.get("valid-lease-run")
    assert valid_row["status"] == "pending"
    assert valid_row["owner_worker_id"] == "other-worker"

    # The new run was never inserted.
    assert await store.get("run-new") is None


# ---------------------------------------------------------------------------
# update_lease
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_lease_renews_row():
    """update_lease must update the lease_expires_at on the stored row."""
    store = MemoryRunStore()
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "run-1",
        thread_id="thread-1",
        status="running",
        owner_worker_id="w1",
        lease_expires_at=old_lease,
    )

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w1",
        lease_expires_at=new_lease,
    )
    assert updated is True

    stored = await store.get("run-1")
    assert stored["lease_expires_at"] == new_lease


@pytest.mark.anyio
async def test_update_lease_returns_false_for_terminal_run():
    """update_lease must return False when the run is not pending/running."""
    store = MemoryRunStore()
    await store.put("run-1", thread_id="thread-1", status="success", owner_worker_id="w1")

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w1",
        lease_expires_at=new_lease,
    )
    assert updated is False

    stored = await store.get("run-1")
    assert stored["status"] == "success"


@pytest.mark.anyio
async def test_update_lease_returns_false_for_wrong_owner():
    """update_lease must reject renewal when owner_worker_id does not match."""
    store = MemoryRunStore()
    old_lease = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    await store.put(
        "run-1",
        thread_id="thread-1",
        status="running",
        owner_worker_id="w1",
        lease_expires_at=old_lease,
    )

    new_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    updated = await store.update_lease(
        "run-1",
        owner_worker_id="w2",  # different worker
        lease_expires_at=new_lease,
    )
    assert updated is False

    # The original lease must be untouched
    stored = await store.get("run-1")
    assert stored["owner_worker_id"] == "w1"
    assert stored["lease_expires_at"] == old_lease


# ---------------------------------------------------------------------------
# list_inflight_with_expired_lease
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_filters_correctly():
    """Only runs with expired or NULL leases must be returned."""
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # Expired lease
    expired = (now - timedelta(seconds=60)).isoformat()
    await store.put("expired-run", thread_id="t1", status="running", owner_worker_id="w1", lease_expires_at=expired, created_at=expired)

    # Valid lease
    valid = (now + timedelta(seconds=60)).isoformat()
    await store.put("valid-run", thread_id="t2", status="running", owner_worker_id="w2", lease_expires_at=valid, created_at=valid)

    # NULL lease (legacy)
    await store.put("null-lease-run", thread_id="t3", status="running", created_at=(now - timedelta(seconds=30)).isoformat())

    # Terminal status (should not appear)
    await store.put("success-run", thread_id="t4", status="success", created_at=(now - timedelta(seconds=60)).isoformat())

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)

    result_ids = {r["run_id"] for r in results}
    assert "expired-run" in result_ids
    assert "null-lease-run" in result_ids
    assert "valid-run" not in result_ids
    assert "success-run" not in result_ids


# ---------------------------------------------------------------------------
# MemoryRunStore — datetime comparison for created_at filtering
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_compares_created_at_as_datetime():
    """``before`` filter must use datetime comparison, not string lexical order.

    ISO-8601 strings compare lexically only when every component is zero-padded
    to the same width and the timezone suffix matches. Datetime parsing is
    order-safe regardless of format.
    """
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # A run created "now" — should be included when before=None (defaults to now).
    await store.put("recent-run", thread_id="t1", status="running", created_at=now.isoformat())
    # A run created far in the future — should be excluded by the before filter
    # even though the string "2300-01-01..." > "2025-..." lexically.
    far_future = "2300-01-01T00:00:00+00:00"
    await store.put("future-run", thread_id="t2", status="running", created_at=far_future)

    results = await store.list_inflight_with_expired_lease(before=now.isoformat(), grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    assert "recent-run" in result_ids
    assert "future-run" not in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_handles_malformed_created_at():
    """Malformed ``created_at`` values must not crash the listing."""
    store = MemoryRunStore()
    grace = 10

    store._runs["bad-run"] = {
        "run_id": "bad-run",
        "thread_id": "t1",
        "status": "running",
        "created_at": "not-a-datetime",
    }
    store._runs["empty-run"] = {
        "run_id": "empty-run",
        "thread_id": "t2",
        "status": "running",
        "created_at": "",
    }

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    # Both should be skipped because their created_at can't be parsed
    result_ids = {r["run_id"] for r in results}
    assert "bad-run" not in result_ids
    assert "empty-run" not in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_datetime_aware_naive_handling():
    """Lease comparison must handle aware and naive datetimes.

    ``lease_expires_at`` stored with a trailing ``+00:00`` (aware) and without
    (naive) should both be comparable against the aware ``cutoff``. The MemoryRunStore
    uses ``datetime.fromisoformat`` which preserves the offset, so both paths
    must work.
    """
    store = MemoryRunStore()
    now = datetime.now(UTC)
    grace = 10

    # Naive datetime (no timezone suffix) — common on SQLite read-back
    naive_expired = (now - timedelta(seconds=60)).isoformat()  # "2025-01-01T00:00:00"
    await store.put("naive-run", thread_id="t1", status="running", lease_expires_at=naive_expired, created_at=naive_expired)

    # Aware datetime (with +00:00)
    aware_expired = (now - timedelta(seconds=60)).replace(tzinfo=UTC).isoformat()  # "2025-01-01T00:00:00+00:00"
    await store.put("aware-run", thread_id="t2", status="running", lease_expires_at=aware_expired, created_at=aware_expired)

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    # Both expired, both should be returned
    assert "naive-run" in result_ids
    assert "aware-run" in result_ids


@pytest.mark.anyio
async def test_list_inflight_with_expired_lease_null_lease_always_reclaimed():
    """NULL lease rows are always reclaimed regardless of created_at value."""
    store = MemoryRunStore()
    grace = 10

    # NULL lease is the single-worker mode default — every inflight row
    # must be returned so reconciliation can reclaim it.
    await store.put("null-run", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    results = await store.list_inflight_with_expired_lease(grace_seconds=grace)
    result_ids = {r["run_id"] for r in results}
    assert "null-run" in result_ids


# ---------------------------------------------------------------------------
# claim_for_takeover — store primitive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_claim_for_takeover_succeeds_with_expired_lease():
    """claim_for_takeover must succeed when the lease has passed the grace window."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-1", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=expired_lease)

    ok = await store.claim_for_takeover(
        "run-1",
        grace_seconds=grace,
        error="claimed",
        stop_reason=ORPHAN_RECOVERY_STOP_REASON,
    )
    assert ok is True

    row = await store.get("run-1")
    assert row is not None
    assert row["status"] == "error"
    assert row["error"] == "claimed"
    assert row["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_claim_for_takeover_fails_with_valid_lease():
    """claim_for_takeover must return False when the lease is still valid."""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put("run-1", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=valid_lease)

    ok = await store.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
    assert ok is False

    row = await store.get("run-1")
    assert row is not None
    assert row["status"] == "running"


@pytest.mark.anyio
async def test_claim_for_takeover_succeeds_with_null_lease():
    """NULL-lease rows (pre-ownership data) must be claimable."""
    store = MemoryRunStore()
    await store.put("run-null", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    ok = await store.claim_for_takeover("run-null", grace_seconds=10, error="claimed")
    assert ok is True

    row = await store.get("run-null")
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_claim_for_takeover_fails_on_terminal_status():
    """claim_for_takeover must return False for already-terminal runs."""
    store = MemoryRunStore()
    await store.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

    ok = await store.claim_for_takeover("run-done", grace_seconds=10, error="claimed")
    assert ok is False


@pytest.mark.anyio
async def test_claim_for_takeover_fails_for_nonexistent_run():
    """claim_for_takeover must return False when the run doesn't exist."""
    store = MemoryRunStore()
    ok = await store.claim_for_takeover("no-such-run", grace_seconds=10, error="claimed")
    assert ok is False


# ---------------------------------------------------------------------------
# cancel() cross-worker takeover — work item 4
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_takeover_from_crashed_worker():
    """cancel must take over (mark error) when lease is expired and owner is another worker."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-expired", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="dead-worker", lease_expires_at=expired_lease)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-expired")
    assert outcome == CancelOutcome.taken_over

    row = await store.get("run-expired")
    assert row is not None
    assert row["status"] == "error"
    assert row["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_cancel_takeover_backfills_owner_scoped_terminal_events_once():
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    on_recovered = AsyncMock(return_value=False)
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put(
        "run-expired",
        thread_id="t1",
        status="running",
        user_id="run-owner",
        created_at=datetime.now(UTC).isoformat(),
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
    )
    manager = _make_manager(
        store=store,
        event_store=events,
        on_orphans_recovered=on_recovered,
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace),
    )

    first = await manager.cancel("run-expired")
    second = await manager.cancel("run-expired")
    recovered_record = await manager.get("run-expired", user_id=None)
    assert recovered_record is not None
    await manager._ensure_recovered_run_events(recovered_record)

    assert first == CancelOutcome.taken_over
    assert second == CancelOutcome.not_cancellable
    delivery = await events.list_events("t1", "run-expired", event_types=["run.delivery"])
    terminal = await events.list_events("t1", "run-expired", event_types=["run.end"])
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": "error",
        "recovered": True,
        "authoritative": True,
    }
    assert events.writes == [
        ("run-expired", "run.delivery", "run-owner"),
        ("run-expired", "run.end", "run-owner"),
        ("run-expired", "run.delivery", "run-owner"),
        ("run-expired", "run.end", "run-owner"),
    ]
    on_recovered.assert_awaited_once()
    callback_records = on_recovered.await_args.args[0]
    assert [record.run_id for record in callback_records] == ["run-expired"]
    assert callback_records[0].stop_reason == ORPHAN_RECOVERY_STOP_REASON


@pytest.mark.anyio
async def test_cancel_takeover_clears_ambient_user_for_a_legacy_ownerless_run():
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put(
        "legacy-run",
        thread_id="t1",
        status="running",
        user_id=None,
        created_at=datetime.now(UTC).isoformat(),
        owner_worker_id="dead-worker",
        lease_expires_at=expired_lease,
    )
    manager = _make_manager(
        store=store,
        event_store=events,
        run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace),
    )

    ambient_user = SimpleNamespace(id="new-request-user")
    token = set_current_user(ambient_user)
    try:
        outcome = await manager.cancel("legacy-run")
        assert get_current_user() is ambient_user
    finally:
        reset_current_user(token)

    assert outcome == CancelOutcome.taken_over
    assert events.writes == [
        ("legacy-run", "run.delivery", None),
        ("legacy-run", "run.end", None),
    ]


@pytest.mark.anyio
async def test_cancel_requests_active_lease_from_other_worker():
    """A cancel routed to a peer must durably notify the live owner."""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put("run-alive", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="alive-worker", lease_expires_at=valid_lease)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-alive")
    assert outcome == CancelOutcome.requested

    row = await store.get("run-alive")
    assert row is not None
    assert row["status"] == "running"
    assert row["cancel_action"] == "interrupt"
    assert row["cancel_requested_at"] is not None


@pytest.mark.anyio
async def test_cancel_routes_an_idempotent_observation_to_its_live_remote_owner():
    """A store-only cache entry is an observation handle, not local ownership."""
    store = MemoryRunStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "remote-idempotent-run",
        thread_id="thread-idempotent",
        status="running",
        user_id="user-1",
        owner_worker_id="worker-a",
        lease_expires_at=valid_lease,
        idempotency_key="scheduled-task:retry-1",
    )
    manager = _make_manager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    cached = await manager.create_or_reject(
        "thread-idempotent",
        user_id="user-1",
        idempotency_key="scheduled-task:retry-1",
    )
    assert cached.store_only is True
    assert cached.run_id not in manager._runs

    outcome = await manager.cancel(cached.run_id)

    stored = await store.get(cached.run_id, user_id="user-1")
    assert outcome == CancelOutcome.requested
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-a"
    assert stored["cancel_action"] == "interrupt"
    assert cached.status == RunStatus.running


@pytest.mark.anyio
async def test_remote_idempotent_snapshot_does_not_poison_later_admission():
    """Remote completion must release both fresh retries and local reject guards."""
    store = MemoryRunStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "remote-completing-run",
        thread_id="thread-idempotent-complete",
        status="running",
        owner_worker_id="worker-a",
        lease_expires_at=valid_lease,
        idempotency_key="scheduled-task:retry-complete",
    )
    manager = _make_manager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    observed = await manager.create_or_reject(
        "thread-idempotent-complete",
        idempotency_key="scheduled-task:retry-complete",
    )
    assert observed.status == RunStatus.running
    assert observed.run_id not in manager._runs

    await store.update_status(observed.run_id, RunStatus.success.value)
    retried = await manager.create_or_reject(
        "thread-idempotent-complete",
        idempotency_key="scheduled-task:retry-complete",
    )
    replacement = await manager.create_or_reject(
        "thread-idempotent-complete",
        multitask_strategy="reject",
    )

    assert retried.run_id == observed.run_id
    assert retried.status == RunStatus.success
    assert replacement.status == RunStatus.pending


@pytest.mark.anyio
async def test_cached_store_only_cancel_fails_safe_for_a_legacy_remote_store():
    """Missing remote-cancel support must not trigger an unfenced local write."""

    class LegacyRemoteCancelStore(MemoryRunStore):
        async def request_cancel(self, run_id, *, action):
            raise NotImplementedError

    store = LegacyRemoteCancelStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put(
        "legacy-remote-run",
        thread_id="thread-legacy-remote",
        status="running",
        owner_worker_id="worker-a",
        lease_expires_at=valid_lease,
        idempotency_key="legacy-retry-1",
    )
    manager = _make_manager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    cached = await manager.create_or_reject(
        "thread-legacy-remote",
        idempotency_key="legacy-retry-1",
    )

    outcome = await manager.cancel(cached.run_id)

    stored = await store.get(cached.run_id)
    assert outcome == CancelOutcome.lease_valid_elsewhere
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-a"


@pytest.mark.anyio
async def test_non_owner_cancel_is_observed_by_owner_heartbeat():
    """Heartbeat signals the owner task without performing terminal writes."""
    store = MemoryRunStore()
    config = _lease_config(heartbeat_enabled=True, lease_seconds=30)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    peer = _make_manager(store=store, worker_id="worker-b", run_ownership_config=config)

    record = await owner.create_or_reject("thread-1")
    await owner.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))

    try:
        assert await peer.cancel(record.run_id, action="rollback") == CancelOutcome.requested
        # Match local idempotency: once accepted, a later action cannot change
        # whether the owner rolls back or merely interrupts.
        assert await peer.cancel(record.run_id, action="interrupt") == CancelOutcome.requested

        await owner._renew_leases()
        await asyncio.sleep(0)

        assert record.abort_event.is_set()
        assert record.abort_action == "rollback"
        assert record.status == RunStatus.running
        assert record.task.cancelled()

        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == "running"
        assert stored["cancel_action"] == "rollback"

        # The worker's existing cancellation path, not heartbeat, owns the
        # terminal status write and any rollback cleanup.
        await owner.set_status(
            record.run_id,
            RunStatus.error,
            error="Rolled back by user",
        )
        next_run = await peer.create_or_reject("thread-1")
        assert next_run.status == RunStatus.pending
    finally:
        if not record.task.done():
            record.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await record.task


@pytest.mark.anyio
async def test_first_cancel_action_wins_when_retry_lands_on_owner():
    """Routing a retry to the owner must not replace the durable first action."""
    store = MemoryRunStore()
    config = _lease_config(heartbeat_enabled=True, lease_seconds=30)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    peer = _make_manager(store=store, worker_id="worker-b", run_ownership_config=config)

    record = await owner.create_or_reject("thread-1")
    await owner.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))

    try:
        assert await peer.cancel(record.run_id, action="rollback") == CancelOutcome.requested
        assert await owner.cancel(record.run_id, action="interrupt") == CancelOutcome.cancelled
        await asyncio.sleep(0)

        assert record.abort_action == "rollback"
        assert record.task.cancelled()
        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["cancel_action"] == "rollback"
    finally:
        if not record.task.done():
            record.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await record.task


@pytest.mark.anyio
async def test_active_local_cancel_leaves_inflight_row_for_crash_recovery():
    """A crash before the worker tail must leave an active row peers can reclaim."""
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    config = _lease_config(
        heartbeat_enabled=True,
        lease_seconds=30,
        grace_seconds=0,
    )
    owner = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=config,
    )
    peer = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-b",
        run_ownership_config=config,
    )
    record = await owner.create_or_reject(
        "thread-cancel-crash",
        user_id="run-owner",
    )
    await owner.set_status(record.run_id, RunStatus.running)
    worker_started = asyncio.Event()

    async def crash_before_terminal_tail() -> None:
        worker_started.set()
        await asyncio.Event().wait()

    record.task = asyncio.create_task(crash_before_terminal_tail())
    await asyncio.wait_for(worker_started.wait(), timeout=1)

    assert await owner.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    with pytest.raises(asyncio.CancelledError):
        await record.task

    crash_row = await store.get(record.run_id)
    assert crash_row is not None
    assert crash_row["status"] == RunStatus.running.value
    assert crash_row["cancel_action"] == "rollback"
    assert record.status == RunStatus.interrupted
    assert record.terminal_status_staged is True
    assert record.terminal_status_persisted is False
    assert (
        await events.list_events(
            record.thread_id,
            record.run_id,
            event_types=["run.delivery", "run.end"],
        )
        == []
    )

    # Model process death after cancel acknowledgement but before the worker's
    # receipt/status/event tail. The still-active row remains discoverable by
    # ordinary lease recovery instead of becoming a terminal observability gap.
    store._runs[record.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    recovered = await peer.reconcile_orphaned_inflight_runs(
        error="owner crashed during cancellation",
        stop_reason=ORPHAN_RECOVERY_STOP_REASON,
    )

    assert [item.run_id for item in recovered] == [record.run_id]
    recovered_row = await store.get(record.run_id)
    assert recovered_row is not None
    assert recovered_row["status"] == RunStatus.error.value
    assert recovered_row["owner_worker_id"] == "worker-b"
    assert recovered_row["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
    delivery = await events.list_events(
        record.thread_id,
        record.run_id,
        event_types=["run.delivery"],
    )
    terminal = await events.list_events(
        record.thread_id,
        record.run_id,
        event_types=["run.end"],
    )
    assert len(delivery) == 1
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": RunStatus.error.value,
        "recovered": True,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_local_owner_cancel_falls_back_when_durable_request_fails():
    """A local owner can still abort its own task when durable cancel persistence fails."""

    class FailingCancelStore(MemoryRunStore):
        async def request_cancel(self, run_id: str, *, action: str) -> str | None:
            raise RuntimeError("store unavailable")

    store = FailingCancelStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True, lease_seconds=30),
    )

    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.sleep(3600))

    try:
        assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
        assert record.abort_event.is_set()
        assert record.abort_action == "rollback"

        with pytest.raises(asyncio.CancelledError):
            await record.task

        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == "running"
        assert stored["cancel_action"] is None
        assert record.terminal_status_staged is True
        assert record.terminal_status_persisted is False
    finally:
        if not record.task.done():
            record.task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await record.task


@pytest.mark.anyio
async def test_owner_cancel_retry_on_peer_is_accepted():
    """A peer must treat the owner's interrupted status as an accepted cancel."""
    store = MemoryRunStore()
    config = _lease_config(heartbeat_enabled=True, lease_seconds=30)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    peer = _make_manager(store=store, worker_id="worker-b", run_ownership_config=config)

    record = await owner.create_or_reject("thread-1")
    await owner.set_status(record.run_id, RunStatus.running)

    assert await owner.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    assert await peer.cancel(record.run_id, action="interrupt") == CancelOutcome.requested

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == "interrupted"
    assert stored["cancel_action"] == "rollback"


@pytest.mark.anyio
async def test_owner_cancel_uses_store_while_terminal_status_is_staged_locally():
    """A staged local terminal status must not bypass the durable cancel CAS."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create_or_reject("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    # Event-store finalization stages success in memory before persisting it.
    record.status = RunStatus.success

    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == "running"
    assert stored["cancel_action"] == "rollback"


@pytest.mark.anyio
async def test_cancel_returns_unknown_when_no_store():
    """cancel must return unknown when there's no store and the run is not in memory."""
    manager = _make_manager(run_ownership_config=_lease_config(heartbeat_enabled=True))
    outcome = await manager.cancel("no-such-run")
    assert outcome == CancelOutcome.unknown


@pytest.mark.anyio
async def test_cancel_returns_not_active_locally_when_heartbeat_disabled():
    """With heartbeat disabled, store-only runs must not be cancellable (old 409 path)."""
    store = MemoryRunStore()
    await store.put("store-only", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=False))
    outcome = await manager.cancel("store-only")
    assert outcome == CancelOutcome.not_active_locally


@pytest.mark.anyio
async def test_cancel_takeover_race_owner_renewed_lease():
    """When takeover loses to a renewal, cancellation must notify the live owner."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-race", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=expired_lease)

    # Simulate the race: right before claim_for_takeover writes, another
    # heartbeat renews the lease.  We monkey-patch claim_for_takeover to
    # simulate the lease having been renewed.
    original = store.claim_for_takeover

    async def race_lost(run_id, *, grace_seconds, error, stop_reason=None):
        # Simulate a heartbeat renewal between the read and the write
        run = store._runs.get(run_id)
        if run and run["status"] in ("pending", "running"):
            run["lease_expires_at"] = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        return await original(
            run_id,
            grace_seconds=grace_seconds,
            error=error,
            stop_reason=stop_reason,
        )

    store.claim_for_takeover = race_lost
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))

    outcome = await manager.cancel("run-race")
    assert outcome == CancelOutcome.requested
    assert (await store.get("run-race"))["cancel_action"] == "interrupt"


@pytest.mark.anyio
async def test_cancel_takeover_respects_grace_seconds():
    """Within the grace window, cancellation must notify rather than take over."""
    store = MemoryRunStore()
    grace = 10
    # Lease expired, but only by 3s — still within the 10s grace window
    just_expired = (datetime.now(UTC) - timedelta(seconds=3)).isoformat()
    await store.put("run-grace", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=just_expired)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-grace")
    assert outcome == CancelOutcome.requested
    assert (await store.get("run-grace"))["cancel_action"] == "interrupt"


@pytest.mark.anyio
async def test_cancel_not_cancellable_for_store_terminal_run():
    """cancel must return not_cancellable when the store run is already in a terminal state."""
    store = MemoryRunStore()
    await store.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))
    outcome = await manager.cancel("run-done")
    assert outcome == CancelOutcome.not_cancellable


# ---------------------------------------------------------------------------
# HTTP-level — cancel endpoint cross-worker responses
# ---------------------------------------------------------------------------


class _EndingCrossProcessBridge:
    supports_cross_process = True

    async def publish(self, run_id, event, data):
        return None

    async def publish_end(self, run_id):
        return None

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        from deerflow.runtime import END_SENTINEL

        async def events():
            yield END_SENTINEL

        return events()

    async def cleanup(self, run_id, *, delay=0):
        return None


def _make_cancel_test_app(mgr: RunManager, *, bridge=None):
    """Build a TestClient wired with the thread_runs router + memory bridge."""
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.routers import thread_runs
    from deerflow.runtime import MemoryStreamBridge

    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    app.state.stream_bridge = bridge or MemoryStreamBridge()
    return TestClient(app, raise_server_exceptions=False)


def test_http_cancel_non_owner_valid_lease_returns_202():
    """POST /cancel must not fail solely because routing chose a non-owner."""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-alive/cancel")
    assert resp.status_code == 202
    assert "Retry-After" not in resp.headers

    # The owner remains fenced, while the cancellation request is durable.
    row = asyncio.run(store.get("run-alive"))
    assert row["status"] == "running"
    assert row["cancel_action"] == "interrupt"


def test_http_stream_action_non_owner_without_shared_bridge_returns_202():
    """A peer cancel is accepted without subscribing to an unreachable local stream."""
    store = MemoryRunStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive-stream",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
        )
    )
    mgr = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    client = _make_cancel_test_app(mgr)

    resp = client.post(
        "/api/threads/t1/runs/run-alive-stream/stream",
        params={"action": "interrupt"},
    )

    assert resp.status_code == 202
    row = asyncio.run(store.get("run-alive-stream"))
    assert row["status"] == "running"
    assert row["cancel_action"] == "interrupt"


def test_http_cancel_non_owner_wait_uses_shared_bridge():
    """wait=true observes remote owner finalization through the shared bridge."""
    store = MemoryRunStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive-wait",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
        )
    )
    mgr = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    client = _make_cancel_test_app(mgr, bridge=_EndingCrossProcessBridge())

    resp = client.post(
        "/api/threads/t1/runs/run-alive-wait/cancel",
        params={"action": "rollback", "wait": "true"},
    )

    assert resp.status_code == 204
    row = asyncio.run(store.get("run-alive-wait"))
    assert row["cancel_action"] == "rollback"


def test_http_stream_action_non_owner_uses_shared_bridge():
    """The SDK stop path drains the remote owner's shared stream after accept."""
    store = MemoryRunStore()
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive-shared-stream",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
        )
    )
    mgr = _make_manager(
        store=store,
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    client = _make_cancel_test_app(mgr, bridge=_EndingCrossProcessBridge())

    resp = client.post(
        "/api/threads/t1/runs/run-alive-shared-stream/stream",
        params={"action": "interrupt"},
    )

    assert resp.status_code == 200
    assert "event: end" in resp.text
    row = asyncio.run(store.get("run-alive-shared-stream"))
    assert row["cancel_action"] == "interrupt"


def test_http_cancel_non_owner_expired_lease_returns_202_takeover():
    """POST /cancel on a non-owning worker with an expired lease must return 202 (takeover)."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 30)).isoformat()
    asyncio.run(
        store.put(
            "run-dead",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="dead-worker",
            lease_expires_at=expired_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-dead/cancel")
    assert resp.status_code == 202

    # Store row must be marked error
    row = asyncio.run(store.get("run-dead"))
    assert row["status"] == "error"


def test_http_stream_action_interrupt_takeover_returns_202_not_hang():
    """POST /stream?action=interrupt on a dead-owner run must return 202 immediately, not hang on SSE."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 30)).isoformat()
    asyncio.run(
        store.put(
            "run-dead-stream",
            thread_id="t1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
            owner_worker_id="dead-worker",
            lease_expires_at=expired_lease,
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    # This must NOT hang — the takeover path returns 202 before reaching StreamingResponse.
    resp = client.post("/api/threads/t1/runs/run-dead-stream/stream", params={"action": "interrupt"})
    assert resp.status_code == 202

    row = asyncio.run(store.get("run-dead-stream"))
    assert row["status"] == "error"


# ---------------------------------------------------------------------------
# Split-brain defences — update_status guard + heartbeat self-termination
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_status_rejects_terminal_row():
    """update_status must return False when the store row is already terminal
    (error/success), so a late writer cannot overwrite a peer's takeover or
    a completed run. interrupted is NOT terminal — the rollback path needs
    ``interrupted → error`` to finalize."""
    store = MemoryRunStore()
    # error (takeover) must stay locked
    await store.put("run-err", thread_id="t1", status="error", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-err", "success") is False
    assert (await store.get("run-err"))["status"] == "error"

    # success must stay locked
    await store.put("run-ok", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-ok", "error") is False
    assert (await store.get("run-ok"))["status"] == "success"

    # interrupted → error MUST pass (rollback finalize path)
    await store.put("run-rb", thread_id="t1", status="interrupted", created_at=datetime.now(UTC).isoformat())
    assert await store.update_status("run-rb", "error", error="Rolled back by user") is True
    row = await store.get("run-rb")
    assert row["status"] == "error"
    assert row["error"] == "Rolled back by user"


@pytest.mark.anyio
async def test_persist_status_skips_recovery_when_row_taken_over():
    """_persist_status must not recreate a row that was taken over by another worker.

    When update_status returns False, the recovery path checks whether the
    row still exists. A row that exists but is terminal (taken over) must
    be left alone — calling put() would overwrite the takeover."""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    # Simulate: this worker created and started a run, but a peer took it over.
    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)
    # Peer takeover: directly flip the store row to error
    await store.update_status(record.run_id, "error")
    # Now simulate the original owner's task finishing and trying to write success
    ok = await mgr._persist_status(record, RunStatus.success)
    assert ok is False  # skipped recovery, row already exists and is terminal
    row = await store.get(record.run_id)
    assert row["status"] == "error"  # not overwritten


@pytest.mark.anyio
async def test_heartbeat_cancels_task_on_lease_loss():
    """Heartbeat must cancel the local asyncio task when update_lease returns False.

    If the store row was claimed by another worker (status no longer
    pending/running, or owner changed), the heartbeat tick must abort the
    local task so wasted CPU is bounded to ~10s instead of the full task
    lifetime."""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, lease_seconds=30))

    # Create a run that this worker owns
    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # Spawn a dummy task so cancel has something to stop
    loop = asyncio.get_running_loop()
    record.task = loop.create_task(asyncio.sleep(3600))

    # Simulate an atomic peer takeover: terminalize and transfer the owner.
    await store.update_status(record.run_id, "error")
    store._runs[record.run_id]["owner_worker_id"] = "worker-b"

    # Run a single heartbeat tick — it should see update_lease return False
    # and cancel the task
    await mgr._renew_leases()

    # Let the event loop process the cancellation (task.cancel() schedules,
    # doesn't await).
    await asyncio.sleep(0)
    assert record.ownership_lost is True
    assert record.abort_event.is_set() is True
    assert record.task.cancelled()


@pytest.mark.anyio
async def test_cancel_returns_taken_over_when_peer_claims_during_local_cancel():
    """When a peer's claim_for_takeover flips the row to error between this
    worker's in-memory cancel and the guarded update_status, cancel() must
    surface taken_over (not cancelled) so the client sees a status consistent
    with the store."""
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # Wrap update_status so that the first call (from cancel's _persist_status)
    # is rejected as if a peer already marked the row error. This simulates
    # the race: in-memory cancel succeeds, but store write is blocked.
    original = store.update_status

    async def race_update(run_id, status, *, error=None, stop_reason=None):
        # Simulate peer takeover: flip to error before our write lands
        run = store._runs.get(run_id)
        if run and run["status"] == "running" and status == "interrupted":
            run["status"] = "error"
            run["error"] = "peer takeover"
            run["updated_at"] = datetime.now(UTC).isoformat()
            return False  # our write was blocked
        return await original(run_id, status, error=error, stop_reason=stop_reason)

    store.update_status = race_update

    outcome = await mgr.cancel(record.run_id)
    assert outcome == CancelOutcome.taken_over

    # Store row must reflect the takeover, not the local cancel
    row = await store.get(record.run_id)
    assert row["status"] == "error"


@pytest.mark.anyio
async def test_cancel_action_rollback_finalizes_to_error_in_store():
    """action=rollback must end up as error in the store with the
    "Rolled back by user" message preserved.

    Regression guard: the update_status guard was originally
    ``status IN ('pending','running')`` which blocked the rollback path's
    ``interrupted → error`` transition — the store stayed interrupted and
    the rollback message was lost.
    """
    store = MemoryRunStore()
    mgr = RunManager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True))

    record = await mgr.create("thread-1")
    await mgr.set_status(record.run_id, RunStatus.running)

    # Step 1: cancel(action=rollback) flips running → interrupted
    outcome = await mgr.cancel(record.run_id, action="rollback")
    assert outcome == CancelOutcome.cancelled
    row = await store.get(record.run_id)
    assert row["status"] == "interrupted"

    # Step 2: worker.py finalize path — task raises CancelledError, then
    # set_status(error, "Rolled back by user"). The widened guard
    # (interrupted is in the whitelist) must let this through.
    await mgr.set_status(record.run_id, RunStatus.error, error="Rolled back by user")
    row = await store.get(record.run_id)
    assert row["status"] == "error"
    assert row["error"] == "Rolled back by user"


@pytest.mark.anyio
async def test_peer_reconciliation_fences_late_success_and_completion():
    """A stale owner cannot overwrite a peer's terminal takeover."""
    store = MemoryRunStore()
    config = _lease_config(heartbeat_enabled=True, grace_seconds=0)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    peer = _make_manager(store=store, worker_id="worker-b", run_ownership_config=config)
    record = await owner.create("thread-1")
    await owner.set_status(record.run_id, RunStatus.running)

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired
    recovered = await peer.reconcile_orphaned_inflight_runs(error="peer takeover")

    assert [recovered_record.run_id for recovered_record in recovered] == [record.run_id]
    assert (await store.get(record.run_id))["status"] == "error"

    await owner.set_status(record.run_id, RunStatus.success)
    await owner.update_run_completion(record.run_id, status=record.status.value, total_tokens=1)

    row = await store.get(record.run_id)
    assert record.ownership_lost is True
    assert record.status == RunStatus.error
    assert row["status"] == "error"
    assert row["error"] == "peer takeover"


@pytest.mark.anyio
async def test_peer_owned_active_row_rejects_stale_worker_completion():
    """Completion and owner fencing must be one atomic store predicate."""
    store = MemoryRunStore()
    config = _lease_config(heartbeat_enabled=True)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    record = await owner.create("thread-1")
    await owner.set_status(record.run_id, RunStatus.running)

    # Model a lease hand-off primitive that transferred an otherwise-active row.
    # The stale worker must not be able to complete it solely by run_id.
    store._runs[record.run_id]["owner_worker_id"] = "worker-b"

    await owner.set_status_if_not_cancelled(record.run_id, RunStatus.success)

    row = await store.get(record.run_id)
    assert row is not None
    assert row["status"] == RunStatus.running.value
    assert row["owner_worker_id"] == "worker-b"
    assert record.ownership_lost is True
    assert record.status == RunStatus.error


@pytest.mark.anyio
async def test_expired_owner_cannot_finalize_before_heartbeat_tick():
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired

    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)

    row = await store.get(record.run_id)
    assert row is not None
    assert row["status"] == RunStatus.running.value
    assert record.ownership_lost is True
    assert record.status == RunStatus.error


@pytest.mark.anyio
async def test_takeover_owner_transfer_fences_same_status_from_stale_worker():
    """A stale worker's error must not impersonate the recovering worker's error."""
    store = MemoryRunStore()
    events = _OwnerCapturingEventStore(store)
    config = _lease_config(heartbeat_enabled=True, grace_seconds=0)
    owner = _make_manager(store=store, worker_id="worker-a", run_ownership_config=config)
    peer = _make_manager(
        store=store,
        event_store=events,
        worker_id="worker-b",
        run_ownership_config=config,
    )
    record = await owner.create("thread-1", user_id="run-owner")
    await owner.set_status(record.run_id, RunStatus.running)
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired

    recovered = await peer.reconcile_orphaned_inflight_runs(error="peer takeover")
    await owner.set_status(record.run_id, RunStatus.error, error="stale worker failure")

    assert [item.run_id for item in recovered] == [record.run_id]
    row = await store.get(record.run_id)
    assert row is not None
    assert row["status"] == RunStatus.error.value
    assert row["error"] == "peer takeover"
    assert row["owner_worker_id"] == "worker-b"
    assert record.ownership_lost is True
    terminal = await events.list_events("thread-1", record.run_id, event_types=["run.end"])
    assert len(terminal) == 1
    assert terminal[0]["metadata"] == {
        "status": "error",
        "recovered": True,
        "authoritative": True,
    }


@pytest.mark.anyio
async def test_unconfirmed_success_is_fenced_when_heartbeat_is_enabled():
    """A store outage cannot turn an unconfirmed terminal write into local success."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)

    async def fail_status_write(*_args, **_kwargs):
        raise OSError("database unreachable")

    store.update_status = fail_status_write

    await manager.set_status(record.run_id, RunStatus.success)

    row = await store.get(record.run_id)
    assert record.ownership_lost is True
    assert record.status == RunStatus.error
    assert record.abort_event.is_set() is True
    assert row["status"] == "running"


@pytest.mark.anyio
async def test_unconfirmed_staged_success_is_fenced_on_deferred_persistence():
    """Receipt-ordered status persistence retains the success fail-close fence."""
    store = MemoryRunStore()
    manager = _make_manager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=_lease_config(heartbeat_enabled=True),
    )
    record = await manager.create("thread-1")
    await manager.set_status(record.run_id, RunStatus.running)
    await manager.set_status(record.run_id, RunStatus.success, persist=False)

    async def fail_status_write(*_args, **_kwargs):
        raise OSError("database unreachable")

    store.update_status = fail_status_write

    persisted = await manager.persist_current_status(record.run_id)

    row = await store.get(record.run_id)
    assert persisted is False
    assert record.ownership_lost is True
    assert record.status == RunStatus.error
    assert record.abort_event.is_set() is True
    assert row["status"] == "running"


# ---------------------------------------------------------------------------
# cancel() claim_for_takeover False → re-read precision
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancel_claim_lost_to_terminal_returns_not_cancellable():
    """When cancel() reads the run as active but claim_for_takeover returns
    False because the row went terminal (run finished) between the read and
    the conditional UPDATE, the re-read must surface not_cancellable."""
    store = MemoryRunStore()
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10))

    # Seed as running so cancel()'s first read passes the status guard.
    expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "run-race",
        thread_id="t1",
        status="running",
        owner_worker_id="w-a",
        lease_expires_at=expired,
        created_at=datetime.now(UTC).isoformat(),
    )

    # Wrap claim_for_takeover: flip the row to success just before the
    # conditional UPDATE so it matches 0 rows.
    original = store.claim_for_takeover

    async def race_claim(run_id, *, grace_seconds, error, stop_reason=None):
        store._runs[run_id]["status"] = "success"
        return await original(
            run_id,
            grace_seconds=grace_seconds,
            error=error,
            stop_reason=stop_reason,
        )

    store.claim_for_takeover = race_claim

    outcome = await mgr.cancel("run-race")
    assert outcome == CancelOutcome.not_cancellable


@pytest.mark.anyio
async def test_cancel_claim_lost_to_takeover_returns_taken_over():
    """When cancel() reads the run as active but claim_for_takeover returns
    False because another worker already took it over (row is error), the
    re-read must surface taken_over."""
    store = MemoryRunStore()
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=10))

    expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "run-race",
        thread_id="t1",
        status="running",
        owner_worker_id="w-a",
        lease_expires_at=expired,
        created_at=datetime.now(UTC).isoformat(),
    )

    # Wrap claim_for_takeover: flip the row to error before the conditional
    # UPDATE so it matches 0 rows (peer already took it over).
    original = store.claim_for_takeover

    async def race_takeover(run_id, *, grace_seconds, error, stop_reason=None):
        store._runs[run_id]["status"] = "error"
        store._runs[run_id]["error"] = "peer claim"
        return await original(
            run_id,
            grace_seconds=grace_seconds,
            error=error,
            stop_reason=stop_reason,
        )

    store.claim_for_takeover = race_takeover

    outcome = await mgr.cancel("run-race")
    assert outcome == CancelOutcome.taken_over


# ---------------------------------------------------------------------------
# _compute_retry_after unit tests
# ---------------------------------------------------------------------------


def test_compute_retry_after_null_lease_returns_none():
    from app.gateway.routers.thread_runs import _compute_retry_after

    assert _compute_retry_after(None, 10) is None


def test_compute_retry_after_unparseable_returns_none():
    from app.gateway.routers.thread_runs import _compute_retry_after

    assert _compute_retry_after("not-a-date", 10) is None


def test_compute_retry_after_normal():
    from app.gateway.routers.thread_runs import _compute_retry_after

    future = (datetime.now(UTC) + timedelta(seconds=45)).isoformat()
    val = _compute_retry_after(future, 10)
    assert val is not None
    # lease_expires_at is ~45s from now + grace_seconds 10 = ~55, within reason
    assert 40 <= val <= 65
