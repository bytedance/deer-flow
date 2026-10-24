"""Lease renewals that predate rollback admission need a bounded second check."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from test_terminal_store_contract import store as store

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus


def manager_for(run_store):
    return RunManager(
        store=run_store,
        worker_id="owner",
        run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=0),
    )


async def running_record(manager):
    record = await manager.create_or_reject("thread")
    await manager.set_status(record.run_id, RunStatus.running)
    record.task = asyncio.create_task(asyncio.Event().wait())
    return record


async def finish(manager, record, *tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    if not record.task.done():
        record.task.cancel()
    with suppress(asyncio.CancelledError):
        await record.task
    await manager.stop_heartbeat(timeout=0)


@pytest.mark.anyio
async def test_pre_rollback_renewal_retries_after_interrupted_ack(store):
    manager = manager_for(store)
    record = await running_record(manager)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    original_renew = store.renew_lease

    async def hold_first_active_renewal(run_id, **kwargs):
        calls.append(kwargs.get("allow_interrupted", False))
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return await original_renew(run_id, **kwargs)

    store.renew_lease = hold_first_active_renewal
    renewal = asyncio.create_task(manager._renew_leases())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        replacement = await manager.create_or_reject("thread", multitask_strategy="rollback")
        assert replacement.status == RunStatus.pending
        assert record.terminal_commit_proof is not None
        assert record.terminal_commit_proof.status == RunStatus.interrupted
        assert record.rollback_finalization_pending
        old_expiry = record.lease_expires_at

        release.set()
        await asyncio.wait_for(renewal, 2)

        assert calls == [False, True]
        assert not record.ownership_lost
        assert record.status == RunStatus.interrupted
        assert record.rollback_finalization_pending
        assert datetime.fromisoformat(record.lease_expires_at) > datetime.fromisoformat(old_expiry)
        row = await store.get(record.run_id)
        assert row["status"] == "interrupted"
        assert row["owner_worker_id"] == "owner"
        assert datetime.fromisoformat(row["lease_expires_at"]) > datetime.now(UTC)
    finally:
        release.set()
        await finish(manager, record, renewal)


@pytest.mark.anyio
async def test_pre_rollback_renewal_waits_for_inflight_interrupted_ack(store):
    manager = manager_for(store)
    record = await running_record(manager)
    renewal_entered, release_renewal = asyncio.Event(), asyncio.Event()
    admission_committed, release_admission_ack = asyncio.Event(), asyncio.Event()
    calls = []
    original_renew = store.renew_lease
    original_admission = store.create_thread_operation_atomic

    async def hold_first_active_renewal(run_id, **kwargs):
        calls.append(kwargs.get("allow_interrupted", False))
        if len(calls) == 1:
            renewal_entered.set()
            await release_renewal.wait()
        return await original_renew(run_id, **kwargs)

    async def hold_committed_admission_ack(*args, **kwargs):
        result = await original_admission(*args, **kwargs)
        admission_committed.set()
        await release_admission_ack.wait()
        return result

    store.renew_lease = hold_first_active_renewal
    store.create_thread_operation_atomic = hold_committed_admission_ack
    renewal = asyncio.create_task(manager._renew_leases())
    admission = None
    try:
        await asyncio.wait_for(renewal_entered.wait(), 1)
        admission = asyncio.create_task(manager.create_or_reject("thread", multitask_strategy="rollback"))
        await asyncio.wait_for(admission_committed.wait(), 1)
        assert record.terminal_commit_proof is None

        release_renewal.set()
        await asyncio.sleep(0)
        assert not renewal.done()
        assert not record.ownership_lost

        release_admission_ack.set()
        replacement = await asyncio.wait_for(admission, 2)
        await asyncio.wait_for(renewal, 2)

        assert replacement.status == RunStatus.pending
        assert calls == [False, True]
        assert record.terminal_commit_proof is not None
        assert record.terminal_commit_proof.status == RunStatus.interrupted
        assert not record.ownership_lost
        assert (await store.get(record.run_id))["status"] == "interrupted"
    finally:
        release_renewal.set()
        release_admission_ack.set()
        await finish(manager, record, renewal, *([admission] if admission is not None else []))


@pytest.mark.anyio
@pytest.mark.parametrize("taken_over", [False, True], ids=["expired", "peer"])
async def test_pre_rollback_retry_still_fences_when_live_owner_was_lost(store, taken_over):
    manager = manager_for(store)
    record = await running_record(manager)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    original_renew = store.renew_lease

    async def lose_owner_before_retry(run_id, **kwargs):
        calls.append(kwargs.get("allow_interrupted", False))
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return await original_renew(run_id, **kwargs)

    store.renew_lease = lose_owner_before_retry
    renewal = asyncio.create_task(manager._renew_leases())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await manager.create_or_reject("thread", multitask_strategy="rollback")
        await store.put(
            record.run_id,
            thread_id=record.thread_id,
            status="interrupted",
            owner_worker_id="peer" if taken_over else "owner",
            lease_expires_at=(datetime.now(UTC) + (timedelta(seconds=30) if taken_over else -timedelta(seconds=1))).isoformat(),
            error="Cancelled by newer run",
        )

        release.set()
        await asyncio.wait_for(renewal, 2)

        assert calls == [False, True]
        assert record.ownership_lost
    finally:
        release.set()
        await finish(manager, record, renewal)
