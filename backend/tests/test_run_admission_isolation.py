"""An admission waiting on its store must not block unrelated run control."""

import asyncio

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore


class HeldAdmissionStore(MemoryRunStore):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.renewed = asyncio.Event()

    async def put(self, run_id, *, thread_id, **kwargs):
        if thread_id == "slow-thread":
            self.entered.set()
            await self.release.wait()
        return await super().put(run_id, thread_id=thread_id, **kwargs)

    async def create_thread_operation_atomic(self, *, thread_id, idempotency_key=None, **kwargs):
        if thread_id == "slow-thread":
            self.entered.set()
            await self.release.wait()
        return await super().create_thread_operation_atomic(thread_id=thread_id, idempotency_key=idempotency_key, **kwargs)

    async def renew_lease(self, run_id, **kwargs):
        result = await super().renew_lease(run_id, **kwargs)
        if result.renewed:
            self.renewed.set()
        return result


@pytest.mark.anyio
@pytest.mark.parametrize("entrypoint", ["create", "create_or_reject", "record_assembly_evidence"])
async def test_admission_wait_does_not_block_another_threads_read_and_cancel(entrypoint):
    store = HeldAdmissionStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject("other-thread", user_id="owner")
    await manager.try_start(record.run_id)
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.Event().wait()

    record.task = asyncio.create_task(work())
    await started.wait()
    if entrypoint == "record_assembly_evidence":
        store.release.set()
        other = await manager.create_or_reject("slow-thread", user_id="owner")
        store.entered.clear()
        store.release.clear()
        admission = asyncio.create_task(manager.record_assembly_evidence(other.run_id, {"run_id": other.run_id, "thread_id": other.thread_id}))
    else:
        admission = asyncio.create_task(getattr(manager, entrypoint)("slow-thread", user_id="owner"))
    readers = []
    try:
        await asyncio.wait_for(store.entered.wait(), timeout=5)
        readers = [asyncio.create_task(manager.get(record.run_id, user_id="owner")), asyncio.create_task(manager.cancel(record.run_id))]
        result = await asyncio.wait_for(asyncio.gather(*readers), timeout=5)
        assert result[0] is record
        await asyncio.wait_for(asyncio.gather(record.task, return_exceptions=True), timeout=5)
        assert record.task.cancelled()
        assert not admission.done()
    finally:
        store.release.set()
        await asyncio.wait_for(asyncio.gather(admission, return_exceptions=True), timeout=5)
        record.task.cancel()
        await asyncio.gather(record.task, *readers, return_exceptions=True)


@pytest.mark.anyio
async def test_admission_wait_does_not_stop_healthy_run_heartbeats():
    store = HeldAdmissionStore()
    manager = RunManager(store=store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
    record = await manager.create_or_reject("healthy-thread", user_id="owner")
    await manager.try_start(record.run_id)
    record.task = asyncio.create_task(asyncio.Event().wait())
    initial_lease = record.lease_expires_at
    store.renewed.clear()
    admission = asyncio.create_task(manager.create_or_reject("slow-thread", user_id="owner"))
    try:
        await asyncio.wait_for(store.entered.wait(), timeout=5)
        await manager.start_heartbeat()
        await asyncio.wait_for(store.renewed.wait(), timeout=5)
        # The Store operation and its Manager decision run in separate tasks.
        # Observe the Manager's acknowledgment, not merely the Store return.
        async with asyncio.timeout(5):
            while record.lease_expires_at == initial_lease:
                await asyncio.sleep(0)
        assert record.lease_expires_at > initial_lease
        assert not record.ownership_lost
        assert not record.task.done()
        assert not admission.done()
    finally:
        store.release.set()
        admitted = await asyncio.wait_for(asyncio.gather(admission, return_exceptions=True), timeout=5)
        if not isinstance(admitted[0], BaseException):
            await manager.cancel(admitted[0].run_id)
        await manager.cancel(record.run_id)
        await manager.stop_heartbeat(timeout=3)
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.anyio
async def test_same_thread_admissions_and_preallocated_id_reads_wait_for_publication():
    store = HeldAdmissionStore()
    manager = RunManager(store=store)
    first = asyncio.create_task(manager.create_or_reject("slow-thread", run_id="first-run"))
    tasks = [first]
    started = asyncio.Event()

    async def second_admission():
        started.set()
        return await manager.create_or_reject("slow-thread", run_id="second-run")

    try:
        await asyncio.wait_for(store.entered.wait(), timeout=5)
        second = asyncio.create_task(second_admission())
        read = asyncio.create_task(manager.get("first-run"))
        history = asyncio.create_task(manager.list_by_thread("slow-thread"))
        tasks.extend([second, read, history])
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not second.done() and not read.done() and not history.done()
        assert await store.get("first-run") is None
        store.release.set()
        record = await asyncio.wait_for(first, timeout=5)
        with pytest.raises(ConflictError):
            await asyncio.wait_for(second, timeout=5)
        assert await asyncio.wait_for(read, timeout=5) is record
        assert await asyncio.wait_for(history, timeout=5) == [record]
        assert await store.get("second-run") is None
    finally:
        store.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_cancelled_waiter_does_not_release_an_active_admission():
    store = HeldAdmissionStore()
    manager = RunManager(store=store)
    owner = asyncio.create_task(manager.create_or_reject("slow-thread", run_id="owner-run"))
    tasks = [owner]
    waiter_entered = asyncio.Event()

    async def waiter():
        waiter_entered.set()
        return await manager.create_or_reject("slow-thread", run_id="cancelled-run")

    try:
        await asyncio.wait_for(store.entered.wait(), timeout=5)
        queued = asyncio.create_task(waiter())
        tasks.append(queued)
        await asyncio.wait_for(waiter_entered.wait(), timeout=5)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert not owner.done()
        store.release.set()
        first = await asyncio.wait_for(owner, timeout=5)
        assert await manager.get("cancelled-run") is None
        assert await manager.list_by_thread("slow-thread") == [first]
        with pytest.raises(ConflictError):
            await manager.create_or_reject("slow-thread")
    finally:
        store.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_same_thread_keyed_retry_reuses_the_committed_admission():
    store = HeldAdmissionStore()
    manager = RunManager(store=store)
    first = asyncio.create_task(manager.create_or_reject("slow-thread", idempotency_key="request-key"))
    tasks = [first]
    try:
        await asyncio.wait_for(store.entered.wait(), timeout=5)
        retry = asyncio.create_task(manager.create_or_reject("slow-thread", idempotency_key="request-key"))
        tasks.append(retry)
        store.release.set()
        original, reused = await asyncio.wait_for(asyncio.gather(first, retry), timeout=5)
        assert reused.run_id == original.run_id
        assert reused.idempotency_reused
        assert len(await manager.list_by_thread("slow-thread")) == 1
    finally:
        store.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_assembly_snapshot_does_not_overwrite_an_acknowledged_renewal():
    store = MemoryRunStore()
    manager = RunManager(store=store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
    record = await manager.create_or_reject("thread", user_id="owner")
    # Assembly is published before execution; pending runs also renew leases.
    renewed = asyncio.Event()
    release_ack = asyncio.Event()
    assembly_started = asyncio.Event()
    original_renew = store.renew_lease
    renewal_targets = []

    async def delayed_ack(run_id, **kwargs):
        result = await original_renew(run_id, **kwargs)
        renewal_targets.append(kwargs["lease_expires_at"])
        renewed.set()
        await release_ack.wait()
        return result

    async def publish_assembly():
        assembly_started.set()
        await manager.record_assembly_evidence(record.run_id, {"run_id": record.run_id, "thread_id": record.thread_id})

    store.renew_lease = delayed_ack
    publication = None
    try:
        await manager.start_heartbeat()
        await asyncio.wait_for(renewed.wait(), timeout=5)
        publication = asyncio.create_task(publish_assembly())
        await asyncio.wait_for(assembly_started.wait(), timeout=5)
        release_ack.set()
        await manager.stop_heartbeat(timeout=5)
        await asyncio.wait_for(publication, timeout=5)
        stored = await store.get(record.run_id)
        assert stored["lease_expires_at"] >= renewal_targets[0]
        assert stored["lease_expires_at"] == record.lease_expires_at
    finally:
        release_ack.set()
        if publication is not None:
            await asyncio.gather(publication, return_exceptions=True)
        await manager.cancel(record.run_id)
        await manager.stop_heartbeat(timeout=3)


@pytest.mark.anyio
async def test_renewal_cancel_does_not_hold_snapshot_gate_while_waiting_for_assembly():
    store = MemoryRunStore()
    manager = RunManager(store=store, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5, grace_seconds=0))
    record = await manager.create_or_reject("thread", user_id="owner")
    await store.request_cancel(record.run_id, action="interrupt")
    renewed, release_ack, assembly_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_renew = store.renew_lease

    async def delayed_ack(run_id, **kwargs):
        result = await original_renew(run_id, **kwargs)
        assert result.cancel_action == "interrupt"
        renewed.set()
        await release_ack.wait()
        return result

    async def publish_assembly():
        assembly_started.set()
        await manager.record_assembly_evidence(record.run_id, {"run_id": record.run_id, "thread_id": record.thread_id})

    store.renew_lease = delayed_ack
    renewal = asyncio.create_task(manager._renew_leases())
    publication = None
    try:
        await asyncio.wait_for(renewed.wait(), timeout=5)
        publication = asyncio.create_task(publish_assembly())
        await asyncio.wait_for(assembly_started.wait(), timeout=5)
        release_ack.set()
        await asyncio.wait_for(asyncio.shield(renewal), timeout=2)
        await asyncio.wait_for(publication, timeout=2)
        assert record.abort_event.is_set()
        assert record.abort_action == "interrupt"
        assert not record.ownership_lost
    finally:
        release_ack.set()
        if publication is not None:
            publication.cancel()
            await asyncio.gather(publication, return_exceptions=True)
        await manager.stop_heartbeat(timeout=3)
        await asyncio.gather(renewal, return_exceptions=True)
        await manager.cancel(record.run_id)
