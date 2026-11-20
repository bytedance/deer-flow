import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from test_terminal_store_contract import store as store

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus


@pytest.fixture
def anyio_backend():
    return "asyncio"


def manager_for(store):
    return RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_same_owner_atomic_replacement_does_not_fence_its_old_run(store, strategy):
    manager = manager_for(store)
    first = await manager.create_or_reject("thread", user_id="review")
    await manager.try_start(first.run_id)
    second = await manager.create_or_reject("thread", multitask_strategy=strategy, user_id="review")
    row = await store.get(first.run_id, user_id="review")
    assert row["owner_worker_id"] == "owner"
    assert row["status"] == "interrupted"
    assert datetime.fromisoformat(row["lease_expires_at"]) > datetime.now(UTC)
    assert second.status == RunStatus.pending
    if strategy == "rollback":
        await manager.set_status(first.run_id, RunStatus.error, error="Rolled back by user")
        row = await store.get(first.run_id, user_id="review")
        assert row["status"] == "error"
        assert row["error"] == "Rolled back by user"
    assert not first.ownership_lost, "successful same-owner atomic replacement was treated as lost ownership"


@pytest.mark.anyio
async def test_fast_renewal_exception_retains_deadline_fencing():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    await manager.try_start(record.run_id)
    record.task = asyncio.create_task(asyncio.Event().wait())
    expiry = datetime.now(UTC) + timedelta(milliseconds=100)
    record.lease_expires_at = expiry.isoformat()
    store._runs[record.run_id]["lease_expires_at"] = expiry.isoformat()
    store.renew_lease = AsyncMock(side_effect=RuntimeError("unavailable"))
    expired = asyncio.Event()
    loop = asyncio.get_running_loop()
    handle = loop.call_later(0.15, expired.set)
    await manager.start_heartbeat()
    try:
        await manager._renew_leases()
        await expired.wait()
        assert datetime.now(UTC) > expiry
        assert await store.claim_for_takeover(record.run_id, grace_seconds=0, error="peer recovery")
        assert record.ownership_lost, "the failed lease check exited and left no deadline decision before the next heartbeat tick"
    finally:
        handle.cancel()
        await manager.stop_heartbeat(timeout=1)
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.anyio
async def test_shutdown_does_not_join_uncooperative_orphan_io_past_budget():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def resistant(*args, **kwargs):
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
        return []

    store.list_inflight_with_expired_lease = resistant
    manager._schedule_orphan_reconciliation()
    recovery = manager._orphan_recovery_task
    await asyncio.wait_for(entered.wait(), 1)
    shutdown = asyncio.create_task(manager.shutdown(timeout=0.01))
    try:
        await asyncio.wait_for(cancelled.wait(), 1)
        done, _ = await asyncio.wait({shutdown}, timeout=0.05)
        assert shutdown in done, "shutdown joined cancellation-resistant orphan I/O without a bound"
        assert manager._orphan_recovery_task is recovery
        assert not recovery.done()
        manager._schedule_orphan_reconciliation()
        assert manager._orphan_recovery_task is recovery
    finally:
        release.set()
        await asyncio.wait_for(shutdown, 1)
        await asyncio.wait_for(recovery, 1)


@pytest.mark.anyio
async def test_cancelled_admission_compensation_cannot_write_after_expiry(store):
    manager = manager_for(store)
    record = await manager.create_or_reject("thread", user_id="review")
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await store.put(record.run_id, thread_id="thread", status="pending", user_id="review", owner_worker_id="owner", lease_expires_at=expired)
    record.lease_expires_at = expired
    await manager._close_cancelled_admission(record)
    row = await store.get(record.run_id, user_id="review")
    assert row["status"] == "pending", "unowned compensation terminalized a row after the owned write had lost its lease"


@pytest.mark.anyio
async def test_atomic_attempt_is_registered_until_its_actual_claim_ack():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    old = await manager.create_or_reject("thread")
    await manager.try_start(old.run_id)
    committed, release = asyncio.Event(), asyncio.Event()
    original = store.create_thread_operation_atomic

    async def hold_ack(**kwargs):
        assert manager._terminal_attempts.get(old.run_id), "attempt must precede Store I/O"
        result = await original(**kwargs)
        committed.set()
        await release.wait()
        return result

    store.create_thread_operation_atomic = hold_ack
    admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="interrupt"))
    try:
        await asyncio.wait_for(committed.wait(), 1)
        assert manager._terminal_attempts.get(old.run_id)
        assert not manager._has_terminal_ack(old)
        release.set()
        await asyncio.wait_for(admission, 1)
        assert manager._has_terminal_ack(old)
        assert old.error == "Cancelled by newer run"
        assert not old.ownership_lost
        assert not manager._terminal_attempts
    finally:
        release.set()
        await asyncio.gather(admission, return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_unclaimed_local_row_cannot_borrow_atomic_admission_ack():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    old = await manager.create_or_reject("thread")
    await manager.try_start(old.run_id)
    original = store.create_thread_operation_atomic

    async def omit_claim(**kwargs):
        new, _ = await original(**kwargs)
        return new, []

    store.create_thread_operation_atomic = omit_claim
    await manager.create_or_reject("thread", multitask_strategy="rollback")
    assert old.status != RunStatus.interrupted
    assert old.terminal_commit_proof is None
    assert not manager._terminal_attempts
    await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_atomic_exception_settles_attempt_without_cancelling_old_worker():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    old = await manager.create_or_reject("thread")

    async def reject(**kwargs):
        assert manager._terminal_attempts.get(old.run_id)
        raise RuntimeError("admission rejected")

    store.create_thread_operation_atomic = reject
    with pytest.raises(RuntimeError, match="admission rejected"):
        await manager.create_or_reject("thread", multitask_strategy="rollback")
    assert not manager._terminal_attempts
    assert old.terminal_commit_proof is None
    assert not old.abort_event.is_set()
    assert old.status == RunStatus.pending
    await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_successful_renewal_invalidates_the_earlier_deadline_guard():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    initial = (datetime.now(UTC) + timedelta(milliseconds=100)).isoformat()
    record.lease_expires_at = initial
    store._runs[record.run_id]["lease_expires_at"] = initial
    original = store.renew_lease
    store.renew_lease = AsyncMock(side_effect=RuntimeError("unavailable"))
    await manager._renew_leases()
    store.renew_lease = original
    await manager._renew_leases()
    elapsed = asyncio.Event()
    asyncio.get_running_loop().call_later(0.15, elapsed.set)
    await elapsed.wait()
    assert not record.ownership_lost
    assert record.lease_expires_at != initial
    await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_expiry_fences_even_while_atomic_ack_holds_the_manager_lock():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    old = await manager.create_or_reject("thread")
    original_atomic, original_renew = store.create_thread_operation_atomic, store.renew_lease
    expiry = (datetime.now(UTC) + timedelta(milliseconds=100)).isoformat()
    old.lease_expires_at = expiry
    store._runs[old.run_id]["lease_expires_at"] = expiry
    renewing, allow_renew, committed, release_ack = (asyncio.Event() for _ in range(4))

    async def held_renew(*args, **kwargs):
        renewing.set()
        await allow_renew.wait()
        return await original_renew(*args, **kwargs)

    async def held_atomic(**kwargs):
        result = await original_atomic(**kwargs)
        committed.set()
        await release_ack.wait()
        return result

    store.renew_lease, store.create_thread_operation_atomic = held_renew, held_atomic
    renewal = asyncio.create_task(manager._renew_leases())
    admission = None
    try:
        await asyncio.wait_for(renewing.wait(), 1)
        admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="rollback"))
        await asyncio.wait_for(committed.wait(), 1)
        allow_renew.set()
        done, _ = await asyncio.wait({renewal}, timeout=0.3)
        assert renewal in done, "expiry fencing waited behind the atomic Store await under the manager lock"
        assert old.ownership_lost
        release_ack.set()
        await asyncio.wait_for(admission, 1)
        assert old.ownership_lost
        assert not manager._has_terminal_ack(old)
        assert not manager._terminal_attempts
    finally:
        allow_renew.set()
        release_ack.set()
        await asyncio.gather(renewal, *([admission] if admission else []), return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["renew_lease", "update_lease"])
@pytest.mark.parametrize(
    "status,owner,expired,allowed",
    [
        ("interrupted", "owner", False, True),
        ("interrupted", "peer", False, False),
        ("interrupted", "owner", True, False),
        ("error", "owner", False, False),
        ("success", "owner", False, False),
    ],
)
async def test_interrupted_renewal_requires_opt_in_and_live_owner(store, method, status, owner, expired, allowed):
    expiry = (datetime.now(UTC) + timedelta(seconds=-1 if expired else 30)).isoformat()
    await store.put("run", thread_id="thread", status=status, user_id=None, owner_worker_id="owner", lease_expires_at=expiry)
    kwargs = dict(owner_worker_id=owner, lease_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat())
    result = await getattr(store, method)("run", **kwargs)
    assert not (result.renewed if method == "renew_lease" else result)
    result = await getattr(store, method)("run", allow_interrupted=True, **kwargs)
    assert (result.renewed if method == "renew_lease" else result) is allowed


@pytest.mark.anyio
async def test_atomic_claim_ack_is_a_snapshot_of_the_committed_outcome(store):
    manager = manager_for(store)
    old = await manager.create_or_reject("thread", user_id="review")
    _, claims = await store.create_thread_operation_atomic(
        run_id="replacement",
        thread_id="thread",
        owner_worker_id="owner",
        lease_expires_at=old.lease_expires_at,
        multitask_strategy="rollback",
        user_id="review",
    )
    assert len(claims) == 1
    assert claims[0]["run_id"] == old.run_id
    assert claims[0]["owner_worker_id"] == "owner"
    assert claims[0]["status"] == "interrupted"
    assert claims[0]["error"] == "Cancelled by newer run"
    assert await store.update_status(old.run_id, "error", error="Rolled back by user", owner_worker_id="owner")
    assert claims[0]["status"] == "interrupted"
    assert claims[0]["error"] == "Cancelled by newer run"


@pytest.mark.anyio
async def test_atomic_replacement_rejects_live_peer_without_ack(store):
    from deerflow.runtime.runs.manager import ConflictError

    manager = manager_for(store)
    old = await manager.create_or_reject("thread", user_id="review")
    peer = RunManager(store=store, worker_id="peer", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
    with pytest.raises(ConflictError):
        await peer.create_or_reject("thread", multitask_strategy="rollback", user_id="review")
    assert (await store.get(old.run_id, user_id="review"))["status"] == "pending"
    assert old.terminal_commit_proof is None
    assert not old.abort_event.is_set()
    assert not peer._terminal_attempts


@pytest.mark.anyio
async def test_pending_caller_cancellation_closes_admitted_replacement():
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = RunManager(store=store)
    old = await manager.create_or_reject("thread")
    original = store.create_thread_operation_atomic

    async def cancel_before_return(**kwargs):
        result = await original(**kwargs)
        asyncio.current_task().cancel()
        return result

    store.create_thread_operation_atomic = cancel_before_return
    task = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="interrupt"))
    with pytest.raises(asyncio.CancelledError):
        await task
    replacement = next(r for r in manager._runs.values() if r is not old)
    assert (await store.get(replacement.run_id))["status"] == "interrupted"


@pytest.mark.anyio
async def test_delayed_atomic_interrupted_ack_cannot_restart_acknowledged_error():
    from deerflow.runtime.runs.manager import TerminalCommitProof
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    committed, release_ack = asyncio.Event(), asyncio.Event()
    original = store.create_thread_operation_atomic

    async def held_atomic(**kwargs):
        result = await original(**kwargs)
        committed.set()
        await release_ack.wait()
        return result

    store.create_thread_operation_atomic = held_atomic
    admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="rollback"))
    try:
        await asyncio.wait_for(committed.wait(), 1)
        # A previously registered terminal writer can finish while admission
        # awaits its older interrupted response under the manager lock.
        outcome = TerminalCommitProof(RunStatus.error, "final error", None, None)
        assert await manager._terminal_operation(record, outcome, lambda: store.update_status(record.run_id, "error", error="final error", owner_worker_id="owner"))
        assert manager._has_final_terminal_ack(record)
        release_ack.set()
        await asyncio.wait_for(admission, 1)
        assert record.status == RunStatus.error
        assert record.error == "final error"
        assert not record.abort_event.is_set()
        assert not record.rollback_finalization_pending
        assert not record.terminal_commit_pending
        assert not manager._terminal_attempts
    finally:
        release_ack.set()
        await asyncio.gather(admission, return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["interrupt", "rollback"])
async def test_direct_cancel_keeps_terminal_confirmation_behind_rollback(store, action):
    from deerflow.runtime.runs.manager import CancelOutcome

    manager = manager_for(store)
    record = await manager.create_or_reject("thread", user_id="review")
    await manager.try_start(record.run_id)
    record.task = asyncio.create_task(asyncio.Event().wait())
    try:
        assert await manager.cancel(record.run_id, action=action) == CancelOutcome.cancelled
        assert (await store.get(record.run_id, user_id="review"))["status"] == "interrupted"
        assert record.terminal_commit_proof.status == RunStatus.interrupted
        assert record.rollback_finalization_pending is (action == "rollback")
        assert record.terminal_status_persisted is (action == "interrupt")

        if action == "rollback":
            await manager.set_status(record.run_id, RunStatus.error, error="Rolled back by user")
            assert record.terminal_status_persisted
            assert not record.rollback_finalization_pending
            assert record.terminal_commit_proof.status == RunStatus.error
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)
        await manager.stop_heartbeat(timeout=0.1)
