"""Regression cases from the authoritative terminal-event review."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import LOCAL_FINALIZER_PENDING_STOP_REASON, ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import CancelOutcome
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.mark.asyncio
@pytest.mark.parametrize("heartbeat", [False, True])
async def test_accepted_attached_cancel_survives_owner_crash(heartbeat):
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=heartbeat))
    record = await manager.create_or_reject("thread", user_id="alice")
    # Keep the worker pending so cancellation cannot finish its terminal tail.
    record.task = asyncio.create_task(asyncio.Event().wait())
    try:
        assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.requested
        assert (await store.get(record.run_id))["cancel_action"] == "rollback"
        if heartbeat:
            store._runs[record.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        recovered = await RunManager(store=store, worker_id="peer").reconcile_orphaned_inflight_runs(error="owner crashed", stop_reason=ORPHAN_RECOVERY_STOP_REASON)
        assert len(recovered) == 1
        assert recovered[0].status == RunStatus.interrupted
        assert (await store.get(record.run_id))["status"] == "interrupted"
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_uncertain_owner_write_cannot_confirm_terminal_status():
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread")
    await manager.set_status(record.run_id, RunStatus.success, persist=False, stage_terminal=True)
    store.update_status_if_owned = AsyncMock(return_value=None)
    assert await manager.persist_current_status(record.run_id) is False
    assert record.terminal_status_persisted is False


@pytest.mark.asyncio
async def test_recovery_does_not_publish_end_until_both_events_persist():
    store = MemoryRunStore()
    callback = AsyncMock(return_value=True)
    manager = RunManager(store=store, event_store=MemoryRunEventStore(), on_orphans_recovered=callback)
    record = await manager.create("thread")
    await manager.set_status(record.run_id, RunStatus.error, stop_reason=ORPHAN_RECOVERY_STOP_REASON)
    manager._ensure_recovered_run_events = AsyncMock(side_effect=[False, True])
    assert await manager.terminalize_recovered_runs([record]) is False
    callback.assert_not_awaited()
    assert await manager.terminalize_recovered_runs([record]) is True
    callback.assert_awaited_once_with([record])


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["persist_current_status", "set_status"])
async def test_worker_final_status_clears_internal_marker(entrypoint):
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread")
    record.stop_reason = LOCAL_FINALIZER_PENDING_STOP_REASON
    await manager.set_status(record.run_id, RunStatus.interrupted, stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON, persist=False, stage_terminal=True)
    await store.update_status(record.run_id, "interrupted", stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON)
    if entrypoint == "persist_current_status":
        assert await manager.persist_current_status(record.run_id)
    else:
        await manager.set_status(record.run_id, RunStatus.interrupted)
    assert record.stop_reason is None
    assert (await store.get(record.run_id))["stop_reason"] is None


@pytest.mark.asyncio
async def test_interrupt_fences_unclaimed_local_worker_without_rewriting_peer_outcome():
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    record = await manager.create_or_reject("thread")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.Event().wait())
    store._runs[record.run_id]["lease_expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    assert await store.claim_for_takeover_as(record.run_id, owner_worker_id="peer", grace_seconds=0, error="peer won", stop_reason=ORPHAN_RECOVERY_STOP_REASON)
    try:
        replacement = await manager.create_or_reject("thread", multitask_strategy="interrupt")
        assert replacement.run_id != record.run_id
        assert record.ownership_lost
        assert record.abort_event.is_set()
        await asyncio.gather(record.task, return_exceptions=True)
        assert record.task.cancelled()
        row = await store.get(record.run_id)
        assert row["owner_worker_id"] == "peer"
        assert row["error"] == "peer won"
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_confirmed_terminal_status_is_not_persisted_twice():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread")
    await manager.set_status(record.run_id, RunStatus.success)
    store.update_status = AsyncMock(wraps=store.update_status)
    assert await manager.persist_current_status(record.run_id)
    store.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_outage_does_not_claim_durable_acceptance():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("thread")
    record.task = asyncio.create_task(asyncio.Event().wait())
    store.request_cancel = AsyncMock(side_effect=RuntimeError("offline"))
    try:
        assert await manager.cancel(record.run_id) == CancelOutcome.unknown
        assert record.abort_event.is_set()
        assert await manager.cancel(record.run_id) == CancelOutcome.unknown
        store.request_cancel = AsyncMock(return_value="interrupt")
        assert await manager.cancel(record.run_id) == CancelOutcome.requested
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_nonheartbeat_cancel_arbitrates_staged_success():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("thread")
    await manager.set_status(record.run_id, RunStatus.success, persist=False, stage_terminal=True)
    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.requested
    assert (await store.get(record.run_id))["cancel_action"] == "rollback"
    assert await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success) == "rollback"


@pytest.mark.asyncio
async def test_admission_does_not_fence_local_completion_before_cas_acknowledgement():
    """The no-event-store path must arbitrate admission during a terminal CAS."""
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("thread")
    await manager.set_status(record.run_id, RunStatus.running)
    committed = asyncio.Event()
    release = asyncio.Event()
    original_finalize = store.finalize_if_not_cancelled

    async def pause_after_commit(*args, **kwargs):
        result = await original_finalize(*args, **kwargs)
        committed.set()
        await release.wait()
        return result

    store.finalize_if_not_cancelled = pause_after_commit
    record.task = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    await asyncio.wait_for(committed.wait(), timeout=1)
    admission_checked = asyncio.Event()
    original_admit = manager._admit_thread_operation

    async def signal_admission(*args, **kwargs):
        try:
            return await original_admit(*args, **kwargs)
        finally:
            admission_checked.set()

    manager._admit_thread_operation = signal_admission
    replacement = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="interrupt"))
    try:
        await asyncio.wait_for(admission_checked.wait(), timeout=1)
        assert not record.ownership_lost
        assert not record.abort_event.is_set()
        release.set()
        await asyncio.wait_for(record.task, timeout=1)
        await asyncio.wait_for(replacement, timeout=1)
        assert (await store.get(record.run_id))["status"] == "success"
    finally:
        release.set()
        await asyncio.gather(record.task, replacement, return_exceptions=True)
