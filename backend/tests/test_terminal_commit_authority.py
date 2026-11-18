"""Deterministic terminal attribution and independent lease deadline regressions."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.store.base import RunStore, StatusFinalization
from deerflow.runtime.runs.store.memory import MemoryRunStore


def manager_for(store):
    return RunManager(store=store, worker_id="owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=0))


async def staged(manager, thread="thread"):
    record = await manager.create_or_reject(thread)
    record.terminal_commit_pending = True
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    return record


async def finish(*tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [RunStatus.success, RunStatus.error])
async def test_identical_peer_terminal_row_is_not_own_ack(status):
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    await manager.set_status(record.run_id, status, persist=False)
    assert (await store.finalize_if_not_cancelled(record.run_id, status=status.value)).finalized
    await manager._renew_leases()
    assert record.ownership_lost, "an externally committed identical row must fence the unconfirmed writer"


@pytest.mark.anyio
async def test_rejected_cas_has_no_status_or_completion_fallback():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    store.finalize_if_not_cancelled = AsyncMock(return_value=StatusFinalization(finalized=False))
    store.update_status = AsyncMock(wraps=store.update_status)
    store.update_run_completion = AsyncMock(wraps=store.update_run_completion)
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    await manager.update_run_completion(record.run_id, status="success", total_tokens=7)
    assert (await store.get(record.run_id))["status"] == "pending"
    store.update_status.assert_not_awaited()
    store.update_run_completion.assert_not_awaited()
    assert record.ownership_lost


@pytest.mark.anyio
async def test_unacknowledged_completion_cannot_terminalize_or_recreate():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    await manager.update_run_completion(record.run_id, status="success", total_tokens=7)
    assert (await store.get(record.run_id))["status"] == "pending"
    assert not record.terminal_status_persisted
    await store.delete(record.run_id)
    await manager.update_run_completion(record.run_id, status="success")
    assert await store.get(record.run_id) is None


@pytest.mark.anyio
async def test_metadata_persistence_retains_idempotency_without_store_io_under_lock():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("thread", idempotency_key="admission-key", idempotency_request={"input": "same"})
    record.metadata["hitl_approval"] = {"request_id": "approval-1"}
    original_put = store.put

    async def checked_put(*args, **kwargs):
        assert not manager._lock.locked()
        return await original_put(*args, **kwargs)

    store.put = checked_put

    assert await manager.persist_metadata(record.run_id) is True
    row = await store.get(record.run_id)
    assert row["idempotency_key"] == "admission-key"
    assert row["idempotency_request"] == {"input": "same"}
    assert row["metadata"]["hitl_approval"] == {"request_id": "approval-1"}


@pytest.mark.anyio
async def test_mark_approval_answered_retries_and_updates_memory_and_store():
    import sqlite3

    from deerflow.runtime.runs.manager import PersistenceRetryPolicy

    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=2, initial_delay=0, max_delay=0),
    )
    identity = {"version": 1, "kind": "resume", "sha256": "a" * 64}
    paused = await manager.create_or_reject(
        "thread",
        metadata={"hitl_approval": {"request_id": "approval-1"}, "retained": True},
        idempotency_key="admission-key",
        idempotency_request=identity,
    )
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)
    original_answer = store.answer_approval
    attempts = 0

    async def fail_once(run_id, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return await original_answer(run_id, **kwargs)

    store.answer_approval = fail_once
    assert await manager.mark_approval_answered("thread") is not None

    assert attempts == 2
    assert paused.status == RunStatus.success
    assert paused.metadata == {"retained": True}
    answered = await store.get(paused.run_id)
    assert answered["status"] == "success"
    assert answered["metadata"] == {"retained": True}
    assert answered["idempotency_key"] == "admission-key"
    assert answered["idempotency_request"] == identity


@pytest.mark.anyio
async def test_mark_approval_answered_has_single_cross_manager_winner():
    store = MemoryRunStore()
    first = RunManager(store=store, worker_id="worker-a")
    second = RunManager(store=store, worker_id="worker-b")
    paused = await first.create_or_reject(
        "thread",
        metadata={"hitl_approval": {"request_id": "approval-1"}, "retained": True},
    )
    await first.set_status(paused.run_id, RunStatus.waiting_for_input)
    original_answer = store.answer_approval
    both_answer_attempts = asyncio.Event()
    attempts = 0

    async def synchronized_answer(run_id, *, metadata, answered_updated_at, expected_request_id=None):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            both_answer_attempts.set()
        await asyncio.wait_for(both_answer_attempts.wait(), 1)
        return await original_answer(
            run_id,
            metadata=metadata,
            answered_updated_at=answered_updated_at,
            expected_request_id=expected_request_id,
        )

    store.answer_approval = synchronized_answer

    results = await asyncio.gather(
        first.mark_approval_answered("thread"),
        second.mark_approval_answered("thread"),
    )

    assert sorted(result is not None for result in results) == [False, True]
    answered = await store.get(paused.run_id)
    assert answered["status"] == "success"
    assert answered["metadata"] == {"retained": True}


@pytest.mark.anyio
async def test_stale_response_cannot_consume_newer_pause_across_managers():
    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")

    def metadata(request_id):
        return {
            "hitl_approval": {
                "kind": "hitl_approval",
                "request_id": request_id,
                "pending_tool_call_ids": ["call-1"],
                "actions": [{"tool_call_id": "call-1", "request_id": request_id}],
            },
            "retained": True,
        }

    first = await owner.create_or_reject("thread", metadata=metadata("approval-1"))
    await owner.set_status(first.run_id, RunStatus.waiting_for_input)
    first_answer = await owner.mark_approval_answered("thread", expected_request_ids={"call-1": "approval-1"})
    assert first_answer is not None

    second = await owner.create_or_reject("thread", metadata=metadata("approval-2"))
    await owner.set_status(second.run_id, RunStatus.waiting_for_input)

    # The peer has no process-local record or lock in common with the owner.
    # Its response was validated against P1, but the newest durable pause is P2.
    assert await peer.mark_approval_answered("thread", expected_request_ids={"call-1": "approval-1"}) is None
    assert (await store.get(second.run_id))["status"] == "waiting_for_input"
    assert (await store.get(second.run_id))["metadata"] == metadata("approval-2")

    second_answer = await peer.mark_approval_answered("thread", expected_request_ids={"call-1": "approval-2"})
    assert second_answer is not None
    assert second_answer.record.store_only
    assert (await store.get(second.run_id))["status"] == "success"

    assert await peer.restore_approval_answer(second_answer) is True
    restored = await store.get(second.run_id)
    assert restored["metadata"] == metadata("approval-2")
    assert await peer.restore_approval_answer(second_answer) is False


@pytest.mark.anyio
async def test_restore_approval_answer_rejects_stale_committed_version():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval-1"}, "retained": True})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)

    answer = await manager.mark_approval_answered("thread")
    assert answer is not None
    committed = await store.get(paused.run_id)
    assert answer.answered_updated_at == committed["updated_at"]

    await store.put(paused.run_id, thread_id="thread", status="success", metadata={"retained": True})
    assert await manager.restore_approval_answer(answer) is False
    assert (await store.get(paused.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_mark_approval_answered_acknowledges_worker_finalization_before_store_io():
    store = MemoryRunStore()
    manager = manager_for(store)
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval-1"}})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)
    previous_revision = paused.terminal_status_revision
    original_answer = store.answer_approval
    answered_cas_started, release_answered_cas = asyncio.Event(), asyncio.Event()

    async def hold_answered_cas(run_id, **kwargs):
        answered_cas_started.set()
        await release_answered_cas.wait()
        return await original_answer(run_id, **kwargs)

    store.answer_approval = hold_answered_cas
    answered = asyncio.create_task(manager.mark_approval_answered("thread"))
    try:
        await asyncio.wait_for(answered_cas_started.wait(), 1)
        assert paused.terminal_status_revision == previous_revision + 1
        assert paused.terminal_commit_proof is not None
        assert paused.terminal_commit_proof.status == RunStatus.success
        assert manager.terminal_event_status(paused) == "success"
        assert not paused.terminal_status_persisted
        release_answered_cas.set()
        assert await asyncio.wait_for(answered, 1) is not None
    finally:
        release_answered_cas.set()
        await finish(answered)

    receipt = object()
    seal_evidence = AsyncMock(return_value=True)
    store.seal_evidence = seal_evidence
    assert await manager.seal_completed_evidence(paused.run_id, receipt) is True
    seal_evidence.assert_awaited_once_with(paused.run_id, owner_worker_id="owner", receipt=receipt)
    await manager.update_run_completion(paused.run_id, status="success", total_tokens=17, message_count=2)
    completed = await store.get(paused.run_id)
    assert completed["total_tokens"] == 17
    assert completed["message_count"] == 2
    assert paused.terminal_status_persisted
    assert manager.terminal_event_status(paused) == "success"


@pytest.mark.anyio
async def test_stale_paused_status_ack_cannot_replace_answered_proof():
    store = MemoryRunStore()
    manager = manager_for(store)
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval-1"}})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input, persist=False)
    paused_revision = paused.terminal_status_revision
    original_finalize = store.finalize_if_not_cancelled
    committed, release_ack = asyncio.Event(), asyncio.Event()

    async def commit_then_hold_ack(*args, **kwargs):
        result = await original_finalize(*args, **kwargs)
        committed.set()
        await release_ack.wait()
        return result

    store.finalize_if_not_cancelled = commit_then_hold_ack
    worker_commit = asyncio.create_task(manager.set_status_if_not_cancelled(paused.run_id, RunStatus.waiting_for_input))
    try:
        await asyncio.wait_for(committed.wait(), 1)
        assert await manager.mark_approval_answered("thread") is not None
        assert paused.terminal_status_revision == paused_revision + 1
        assert paused.terminal_commit_proof is not None
        assert paused.terminal_commit_proof.status == RunStatus.success
        assert paused.terminal_status_persisted
        release_ack.set()
        await asyncio.wait_for(worker_commit, 1)
    finally:
        release_ack.set()
        await finish(worker_commit)

    answered = await store.get(paused.run_id)
    assert answered["status"] == RunStatus.success.value
    assert paused.status == RunStatus.success
    assert paused.terminal_commit_proof.status == RunStatus.success
    assert paused.terminal_status_revision == paused_revision + 1
    assert manager.terminal_event_status(paused) == "success"


@pytest.mark.anyio
async def test_worker_waiting_metadata_put_cannot_resurrect_answered_run():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval-1"}, "retained": True})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)
    original_put = store.put
    stale_put_started, release_stale_put = asyncio.Event(), asyncio.Event()

    async def hold_worker_waiting_put(run_id, **kwargs):
        if kwargs["status"] == RunStatus.waiting_for_input.value:
            stale_put_started.set()
            await release_stale_put.wait()
        await original_put(run_id, **kwargs)

    store.put = hold_worker_waiting_put
    worker_persist = asyncio.create_task(manager.persist_metadata(paused.run_id))
    try:
        await asyncio.wait_for(stale_put_started.wait(), 1)
        assert await manager.mark_approval_answered("thread") is not None
        assert (await store.get(paused.run_id))["status"] == RunStatus.success.value
        release_stale_put.set()
        assert await asyncio.wait_for(worker_persist, 1) is True
    finally:
        release_stale_put.set()
        await finish(worker_persist)

    assert paused.status == RunStatus.success
    assert paused.metadata == {"retained": True}
    answered = await store.get(paused.run_id)
    assert answered["status"] == RunStatus.success.value
    assert answered["metadata"] == {"retained": True}


@pytest.mark.anyio
async def test_mark_approval_answered_reconciles_newer_local_state():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval-1"}})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)
    original_answer = store.answer_approval
    answered_cas_started, release_answered_cas = asyncio.Event(), asyncio.Event()

    async def hold_answered_cas(run_id, **kwargs):
        answered_cas_started.set()
        await release_answered_cas.wait()
        return await original_answer(run_id, **kwargs)

    store.answer_approval = hold_answered_cas
    answered = asyncio.create_task(manager.mark_approval_answered("thread"))
    try:
        await asyncio.wait_for(answered_cas_started.wait(), 1)
        await manager.set_status(paused.run_id, RunStatus.error, error="newer terminal state", persist=False)
        release_answered_cas.set()
        assert await asyncio.wait_for(answered, 1) is not None
    finally:
        release_answered_cas.set()
        await finish(answered)

    assert paused.status == RunStatus.error
    assert paused.error == "newer terminal state"
    latest = await store.get(paused.run_id)
    assert latest["status"] == RunStatus.error.value
    assert latest["error"] == "newer terminal state"


@pytest.mark.anyio
async def test_committed_cas_waits_for_its_ack_after_renewal_rejection():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    committed, release, rejected = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_finalize, original_renew = store.finalize_if_not_cancelled, store.renew_lease

    async def commit_then_hold_ack(*args, **kwargs):
        result = await original_finalize(*args, **kwargs)
        committed.set()
        await release.wait()
        return result

    async def reject_terminal_renewal(*args, **kwargs):
        result = await original_renew(*args, **kwargs)
        rejected.set()
        return result

    store.finalize_if_not_cancelled = commit_then_hold_ack
    store.renew_lease = reject_terminal_renewal
    commit = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    renewal = None
    try:
        await asyncio.wait_for(committed.wait(), 1)
        renewal = asyncio.create_task(manager._renew_leases())
        await asyncio.wait_for(rejected.wait(), 0.3)
        assert record.terminal_commit_pending
        assert not renewal.done(), "the matching durable row cannot replace the held acknowledgment"
        release.set()
        await asyncio.wait_for(asyncio.gather(commit, renewal), 1)
        assert not record.ownership_lost
        assert not record.terminal_commit_pending
        assert record.terminal_status_persisted
    finally:
        release.set()
        await finish(commit, *([renewal] if renewal else []))


@pytest.mark.anyio
async def test_uncancellable_renewal_does_not_delay_peer_cancel_or_deadline():
    store = MemoryRunStore()
    manager = manager_for(store)
    slow = await manager.create_or_reject("slow")
    fast = await manager.create_or_reject("fast")
    deadline = (datetime.now(UTC) + timedelta(milliseconds=100)).isoformat()
    slow.lease_expires_at = deadline
    store._runs[slow.run_id]["lease_expires_at"] = deadline
    entered, release, fast_renewed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = store.renew_lease
    calls = 0

    async def blocked(*args, **kwargs):
        nonlocal calls
        if args[0] == slow.run_id:
            calls += 1
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            return await original(*args, **kwargs)
        result = await original(*args, **kwargs)
        fast_renewed.set()
        return result

    store.renew_lease = blocked
    await store.request_cancel(fast.run_id, action="rollback")
    cycle = asyncio.create_task(manager._renew_leases())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(fast_renewed.wait(), 0.3)
        await asyncio.wait_for(asyncio.shield(cycle), 0.4)
        assert slow.ownership_lost
        assert fast.abort_event.is_set()
        assert fast.abort_action == "rollback"
        assert not fast.ownership_lost
        await manager._renew_leases()
        assert calls == 1
        release.set()
        await manager.stop_heartbeat(timeout=0.1)
        assert slow.ownership_lost
        assert slow.lease_expires_at == deadline
    finally:
        release.set()
        await finish(cycle)
        await manager.stop_heartbeat(timeout=0.1)


@pytest.mark.anyio
async def test_caller_cancelled_cas_has_no_positive_proof():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.finalize_if_not_cancelled

    async def commit_without_ack(*args, **kwargs):
        await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return StatusFinalization(finalized=True)

    store.finalize_if_not_cancelled = commit_without_ack
    commit = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        commit.cancel()
        with pytest.raises(asyncio.CancelledError):
            await commit
        await manager._renew_leases()
        assert record.ownership_lost
        assert not record.terminal_status_persisted
    finally:
        release.set()
        await finish(commit)


@pytest.mark.anyio
async def test_different_attempts_settle_without_borrowing_another_status_ack():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    committed, rejected, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = store.finalize_if_not_cancelled

    async def hold_success(*args, **kwargs):
        result = await original(*args, **kwargs)
        if result.finalized:
            committed.set()
            await release.wait()
        else:
            rejected.set()
        return result

    store.finalize_if_not_cancelled = hold_success
    success = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    failure = None
    try:
        await asyncio.wait_for(committed.wait(), 1)
        failure = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.error, error="losing attempt"))
        await asyncio.wait_for(rejected.wait(), 1)
        assert record.terminal_commit_pending
        assert not record.terminal_status_persisted
        release.set()
        await asyncio.wait_for(asyncio.gather(success, failure), 1)
        assert record.status == RunStatus.success
        assert not record.ownership_lost
        assert record.terminal_status_persisted
        assert manager._terminal_attempts == {}
    finally:
        release.set()
        await finish(success, *([failure] if failure else []))


@pytest.mark.anyio
async def test_unknown_commit_fences_at_deadline_and_late_ack_cannot_revive():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    expiry = (datetime.now(UTC) + timedelta(milliseconds=100)).isoformat()
    record.lease_expires_at = expiry
    store._runs[record.run_id]["lease_expires_at"] = expiry
    committed, release = asyncio.Event(), asyncio.Event()
    original = store.finalize_if_not_cancelled

    async def hold_ack(*args, **kwargs):
        result = await original(*args, **kwargs)
        committed.set()
        await release.wait()
        return result

    store.finalize_if_not_cancelled = hold_ack
    commit = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success))
    try:
        await asyncio.wait_for(committed.wait(), 1)
        await asyncio.wait_for(manager._renew_leases(), 0.5)
        assert record.ownership_lost
        assert not record.terminal_status_persisted
        release.set()
        await asyncio.wait_for(commit, 1)
        assert record.ownership_lost
        assert record.status == RunStatus.error
        assert not record.terminal_status_persisted
        assert manager._terminal_attempts == {}
    finally:
        release.set()
        await finish(commit)


@pytest.mark.anyio
async def test_legacy_none_status_result_is_unconfirmed_in_heartbeat_mode():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    original = store.update_status

    async def no_rowcount(*args, **kwargs):
        await original(*args, **kwargs)

    store.update_status = no_rowcount
    assert await manager.persist_current_status(record.run_id) is False
    assert record.ownership_lost
    assert not record.terminal_status_persisted


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["update_status", "legacy_finalization", "default_finalization"])
async def test_unsupported_owned_store_contract_fails_closed_with_diagnostic(method, caplog):
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    calls = []

    async def legacy_write(run_id, status, *, error=None, stop_reason=None, goal_verdict=None):
        calls.append(run_id)
        return True

    if method == "update_status":
        store.update_status = legacy_write
        assert await manager.persist_current_status(record.run_id) is False
    else:
        store.finalize_if_not_cancelled = legacy_write if method == "legacy_finalization" else RunStore.finalize_if_not_cancelled.__get__(store)
        await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)

    assert calls == []
    assert (await store.get(record.run_id))["status"] == "pending"
    assert record.ownership_lost
    assert record.terminal_commit_proof is None
    assert not record.terminal_status_persisted
    assert manager._terminal_attempts == {}
    assert "owner_worker_id" in caplog.text


@pytest.mark.anyio
async def test_legacy_completion_cannot_bypass_strict_contract(caplog):
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    proof = record.terminal_commit_proof
    assert proof is not None
    calls = []

    async def legacy_completion(run_id, *, status, total_tokens=0):
        calls.append(run_id)
        return True

    store.update_run_completion = legacy_completion
    await manager.update_run_completion(record.run_id, status="success", total_tokens=5)
    assert calls == []
    assert (await store.get(record.run_id)).get("total_tokens", 0) == 0
    assert record.terminal_commit_proof is proof
    assert not record.ownership_lost
    assert "require_terminal" in caplog.text


@pytest.mark.anyio
async def test_subsequent_ticks_renew_fast_run_while_slow_check_is_pending():
    store = MemoryRunStore()
    manager = manager_for(store)
    slow = await manager.create_or_reject("slow")
    fast = await manager.create_or_reject("fast")
    entered, release, twice = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = store.renew_lease
    slow_calls, fast_calls = 0, 0

    async def renew(run_id, **kwargs):
        nonlocal slow_calls, fast_calls
        if run_id == slow.run_id:
            slow_calls += 1
            entered.set()
            await release.wait()
        result = await original(run_id, **kwargs)
        if run_id == fast.run_id:
            fast_calls += 1
            if fast_calls == 2:
                twice.set()
        return result

    store.renew_lease = renew
    try:
        await manager._renew_leases(wait=False)
        await asyncio.wait_for(entered.wait(), 1)
        async with asyncio.timeout(1):
            while fast_calls < 1:
                await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.shield(manager._lease_checks[fast.run_id]), 1)
        await manager._renew_leases(wait=False)
        await asyncio.wait_for(twice.wait(), 1)
        assert slow_calls == 1
        assert not manager._lease_checks[slow.run_id].done()
        assert not fast.ownership_lost
    finally:
        release.set()
        await manager.stop_heartbeat(timeout=1)


@pytest.mark.anyio
async def test_shutdown_bounds_uncancellable_io_and_observes_late_exception(caplog):
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    entered, release = asyncio.Event(), asyncio.Event()

    async def resistant(*args, **kwargs):
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        raise RuntimeError("late Store failure")

    store.renew_lease = resistant
    try:
        await manager._renew_leases(wait=False)
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(manager.stop_heartbeat(timeout=0.01), 0.3)
        assert record.run_id in manager._lease_operations
        assert "still draining" in caplog.text
        release.set()
        async with asyncio.timeout(1):
            while manager._lease_operations:
                await asyncio.sleep(0)
        assert "RuntimeError" in caplog.text
    finally:
        release.set()
        await manager.stop_heartbeat(timeout=1)


@pytest.mark.anyio
async def test_staged_terminal_still_receives_durable_cancellation():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    assert await store.request_cancel(record.run_id, action="rollback") == "rollback"
    await manager._renew_leases()
    assert record.abort_event.is_set()
    assert record.abort_action == "rollback"
    assert not record.ownership_lost


@pytest.mark.anyio
async def test_completion_cannot_mutate_an_acknowledged_outcome():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    await manager.update_run_completion(record.run_id, status="success", error="different outcome")
    assert record.error is None
    assert (await store.get(record.run_id)).get("error") is None
    assert manager._has_terminal_ack(record)


@pytest.mark.anyio
async def test_exited_unconfirmed_worker_does_not_keep_renewing_forever():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    record.task = asyncio.create_task(asyncio.sleep(0))
    await record.task
    await manager._renew_leases()
    assert record.ownership_lost
    assert not record.terminal_commit_pending


@pytest.mark.anyio
async def test_barrier_requires_own_ack_only_for_durable_heartbeat_mode():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    assert not manager.can_release_terminal_barrier(record)
    memory_only = RunManager(run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    assert memory_only.can_release_terminal_barrier(record)
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    assert manager.can_release_terminal_barrier(record)


@pytest.mark.anyio
async def test_older_interrupted_ack_cannot_overwrite_newer_error_commit():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    committed, release = asyncio.Event(), asyncio.Event()
    original = store.update_status

    async def hold_interrupted(*args, **kwargs):
        result = await original(*args, **kwargs)
        if args[1] == "interrupted":
            committed.set()
            await release.wait()
        return result

    store.update_status = hold_interrupted
    first = asyncio.create_task(manager.set_status(record.run_id, RunStatus.interrupted))
    try:
        await asyncio.wait_for(committed.wait(), 1)
        await manager.set_status(record.run_id, RunStatus.error, error="Rolled back by user")
        assert record.status == RunStatus.error
        release.set()
        await asyncio.wait_for(first, 1)
        assert record.status == RunStatus.error
        assert (await store.get(record.run_id))["status"] == "error"
        assert record.error == "Rolled back by user"
        assert record.terminal_status_persisted
        assert manager._has_terminal_ack(record)
        assert not manager._has_terminal_ack(record, manager._terminal_outcome(record, RunStatus.interrupted, error="Rolled back by user"))
        assert not record.ownership_lost
        assert manager._terminal_attempts == {}
    finally:
        release.set()
        await finish(first)


@pytest.mark.anyio
async def test_attempt_uses_immutable_verdict_snapshot_for_store_and_proof():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.finalize_if_not_cancelled
    verdict = {"satisfied": True}

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    store.finalize_if_not_cancelled = delayed
    commit = asyncio.create_task(manager.set_status_if_not_cancelled(record.run_id, RunStatus.success, goal_verdict=verdict))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        verdict["satisfied"] = False
        release.set()
        await asyncio.wait_for(commit, 1)
        assert (await store.get(record.run_id))["goal_verdict"] == {"satisfied": True}
        assert record.goal_verdict == {"satisfied": True}
        assert manager._has_terminal_ack(record)
    finally:
        release.set()
        await finish(commit)


@pytest.mark.anyio
async def test_intermediate_ack_cannot_confirm_newer_pending_error():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await manager.create_or_reject("thread")
    first_committed, second_committed = asyncio.Event(), asyncio.Event()
    release_first, release_second = asyncio.Event(), asyncio.Event()
    original = store.update_status

    async def hold_ack(run_id, status, **kwargs):
        result = await original(run_id, status, **kwargs)
        if status == "interrupted":
            first_committed.set()
            await release_first.wait()
        elif status == "error":
            second_committed.set()
            await release_second.wait()
        return result

    store.update_status = hold_ack
    first = asyncio.create_task(manager.set_status(record.run_id, RunStatus.interrupted))
    second = None
    try:
        await asyncio.wait_for(first_committed.wait(), 1)
        second = asyncio.create_task(manager.set_status(record.run_id, RunStatus.error, error="Rolled back by user"))
        await asyncio.wait_for(second_committed.wait(), 1)
        release_first.set()
        await asyncio.wait_for(first, 1)
        assert record.status == RunStatus.error
        assert not record.terminal_status_persisted
        assert record.terminal_commit_pending
        release_second.set()
        await asyncio.wait_for(second, 1)
        assert record.status == RunStatus.error
        assert record.terminal_status_persisted
        assert not record.terminal_commit_pending
        assert not record.ownership_lost
    finally:
        release_first.set()
        release_second.set()
        await finish(first, *([second] if second else []))


@pytest.mark.anyio
async def test_acknowledged_final_outcome_rejects_late_conflicting_local_status():
    store = MemoryRunStore()
    manager = manager_for(store)
    record = await staged(manager)
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.success)
    await manager.set_status(record.run_id, RunStatus.error, error="late cancellation")
    await manager.set_status_if_not_cancelled(record.run_id, RunStatus.error, error="late failure")
    assert record.status == RunStatus.success
    assert (await store.get(record.run_id))["status"] == "success"
    assert manager._has_terminal_ack(record)
    assert not record.ownership_lost
