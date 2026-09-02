"""Regression tests for bounded terminal ``RunManager`` retention (#5009)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import (
    TERMINAL_RUN_EVICTION_WARNING_RETRY_COUNT,
    CancelOutcome,
    PersistenceRetryPolicy,
    RunManager,
    RunStartOutcome,
    RunStartupError,
)
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.base import StatusFinalization
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import (
    _BACKGROUND_TERMINAL_TASKS,
    RunContext,
    _spawn_background_terminal_task,
    run_agent,
)


class RecoveringRunStore(MemoryRunStore):
    """Store whose terminal writes can be held failed until a test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_terminal_writes = False
        self.status_write_calls = 0
        self.completion_write_calls = 0
        self.get_calls = 0
        self.read_while_stale = asyncio.Event()

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        self.status_write_calls += 1
        if self.fail_terminal_writes:
            raise RuntimeError("simulated terminal status outage")
        return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    async def update_run_completion(self, run_id, *, status, **kwargs):
        self.completion_write_calls += 1
        if self.fail_terminal_writes:
            raise RuntimeError("simulated completion outage")
        return await super().update_run_completion(run_id, status=status, **kwargs)

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        run = self._runs.get(args[0])
        can_finalize = bool(run is not None and run.get("owner_worker_id") == kwargs["expected_owner_worker_id"] and run.get("status") in ("pending", "running") and run.get("cancel_action") is None)
        if can_finalize:
            self.completion_write_calls += 1
            if self.fail_terminal_writes:
                raise RuntimeError("simulated completion outage")
        return await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )

    async def get(self, run_id, *, user_id=None):
        self.get_calls += 1
        row = await super().get(run_id, user_id=user_id)
        if row is not None and row.get("status") in {RunStatus.pending.value, RunStatus.running.value}:
            self.read_while_stale.set()
        return row


class StatusWriteFailingRunStore(MemoryRunStore):
    """Store where terminal status writes fail but completion writes succeed."""

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        raise RuntimeError("simulated status-only outage")


class BlockingReadRunStore(MemoryRunStore):
    """Store that can pause one read after capturing the durable snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.block_next_get = False
        self.read_started = asyncio.Event()
        self.allow_read = asyncio.Event()

    async def get(self, run_id, *, user_id=None):
        row = await super().get(run_id, user_id=user_id)
        if self.block_next_get:
            self.block_next_get = False
            self.read_started.set()
            await self.allow_read.wait()
        return row


class UnsupportedOwnedFinalizeRunStore(RecoveringRunStore):
    """Legacy-compatible store without the new terminal capabilities."""

    async def finalize_completion_if_owned_and_not_cancelled(self, *_args, **_kwargs):
        return None

    async def finalize_cancelled_completion_if_owned(self, *_args, **_kwargs):
        return None

    async def insert_terminal_completion_if_absent(self, *_args, **_kwargs):
        return None


class UnsupportedDurableCancellationRunStore(MemoryRunStore):
    """Heartbeat store that cannot durably record a cancellation action."""

    async def request_cancel(self, *_args, **_kwargs):
        raise NotImplementedError


class MalformedOwnedFinalizeRunStore(RecoveringRunStore):
    async def finalize_completion_if_owned_and_not_cancelled(self, *_args, **_kwargs):
        return True


class BlockingTerminalInsertRunStore(MemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.insert_started = asyncio.Event()
        self.allow_insert = asyncio.Event()

    async def insert_terminal_completion_if_absent(self, run_id, **kwargs):
        self.insert_started.set()
        await self.allow_insert.wait()
        return await super().insert_terminal_completion_if_absent(run_id, **kwargs)


class RecordingTerminalInsertRunStore(MemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.terminal_insert_calls = 0

    async def insert_terminal_completion_if_absent(self, run_id, **kwargs):
        self.terminal_insert_calls += 1
        return await super().insert_terminal_completion_if_absent(run_id, **kwargs)


class FailingReadRunStore(MemoryRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_reads = False

    async def get(self, run_id, *, user_id=None):
        if self.fail_reads:
            raise RuntimeError("simulated terminal read outage")
        return await super().get(run_id, user_id=user_id)


class ProgressWriteFailingRunStore(MemoryRunStore):
    async def update_run_progress(self, run_id, **kwargs):
        raise RuntimeError("simulated finalizing progress outage")


class CheckpointMutationFenceFailingRunStore(MemoryRunStore):
    """Store whose rollback ownership fence fails before it can yield."""

    @asynccontextmanager
    async def checkpoint_mutation_fence(self, *_args, **_kwargs):
        raise RuntimeError("simulated checkpoint mutation fence outage")
        yield  # pragma: no cover


class CancellationStatusWriteFailingRunStore(MemoryRunStore):
    """Store where one post-cancellation terminal status write is lost."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_terminal_status = False

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        if self.fail_next_terminal_status and status in {
            RunStatus.error.value,
            RunStatus.interrupted.value,
        }:
            self.fail_next_terminal_status = False
            raise RuntimeError("simulated cancellation status outage")
        return await super().update_status(
            run_id,
            status,
            error=error,
            stop_reason=stop_reason,
        )

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        if self.fail_next_terminal_status:
            self.fail_next_terminal_status = False
            raise RuntimeError("simulated cancellation status outage")
        return await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )

    async def finalize_cancelled_completion_if_owned(self, *args, **kwargs):
        if self.fail_next_terminal_status:
            self.fail_next_terminal_status = False
            raise RuntimeError("simulated cancellation status outage")
        return await super().finalize_cancelled_completion_if_owned(
            *args,
            **kwargs,
        )


class PeerTakeoverDuringFinalizationStore(MemoryRunStore):
    """Simulate a peer choosing the same error before local persistence."""

    async def finalize_completion_if_owned_and_not_cancelled(
        self,
        run_id,
        **kwargs,
    ) -> StatusFinalization:
        status = kwargs["status"]
        run = self._runs.get(run_id)
        if run is not None and status == RunStatus.error.value:
            run["status"] = RunStatus.error.value
            run["error"] = kwargs.get("error")
            run["stop_reason"] = kwargs.get("stop_reason")
            run["owner_worker_id"] = None
            run["lease_expires_at"] = None
            return StatusFinalization(finalized=False)
        return await super().finalize_completion_if_owned_and_not_cancelled(
            run_id,
            **kwargs,
        )


class AmbiguousDifferentCancelWinnerStore(MemoryRunStore):
    """Persist interrupt as winner, then lose the response to rollback caller."""

    async def request_cancel(self, run_id, *, action):
        assert action == "rollback"
        assert await super().request_cancel(run_id, action="interrupt") == "interrupt"
        raise RuntimeError("simulated response loss after competing cancel won")


class AmbiguousCancelWinnerAndReadFailureStore(MemoryRunStore):
    """Lose both the cancel response and the immediate winner verification."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_get = False

    async def request_cancel(self, run_id, *, action):
        assert action == "rollback"
        assert await super().request_cancel(run_id, action="interrupt") == "interrupt"
        self.fail_next_get = True
        raise RuntimeError("simulated response loss after competing cancel won")

    async def get(self, run_id, *, user_id=None):
        if self.fail_next_get:
            self.fail_next_get = False
            raise RuntimeError("simulated winner verification outage")
        return await super().get(run_id, user_id=user_id)


class AuthorityReadFailAfterFinalizeStore(MemoryRunStore):
    """Fail the first authority read after a locally-owned terminal CAS."""

    def __init__(self) -> None:
        super().__init__()
        self.remaining_get_failures = 0

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        result = await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )
        if result.finalized:
            # ``verify_terminal_authority`` first attempts convergence and then
            # performs a read-only fallback. Both reads must fail to prove that
            # the process-local confirmed-write evidence is actually used.
            self.remaining_get_failures = 2
        return result

    async def get(self, run_id, *, user_id=None):
        if self.remaining_get_failures:
            self.remaining_get_failures -= 1
            raise RuntimeError("simulated authority read outage")
        return await super().get(run_id, user_id=user_id)


class AuthorityReadFailAfterCancelledFinalizeStore(MemoryRunStore):
    """Lose the verification read after a confirmed cancellation CAS."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_get = False

    async def finalize_cancelled_completion_if_owned(self, *args, **kwargs):
        result = await super().finalize_cancelled_completion_if_owned(
            *args,
            **kwargs,
        )
        if result.finalized:
            self.fail_next_get = True
        return result

    async def get(self, run_id, *, user_id=None):
        if self.fail_next_get:
            self.fail_next_get = False
            raise RuntimeError("simulated post-cancel verification outage")
        return await super().get(run_id, user_id=user_id)


class BlockingOwnedFinalizeReturnStore(MemoryRunStore):
    """Pause after the durable terminal CAS but before manager acknowledgement."""

    def __init__(self) -> None:
        super().__init__()
        self.finalize_committed = asyncio.Event()
        self.allow_finalize_return = asyncio.Event()

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        result = await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )
        if result.finalized:
            self.finalize_committed.set()
            await self.allow_finalize_return.wait()
        return result


class BlockingInterruptedCancellationFinalizeStore(MemoryRunStore):
    """Pause a stale rollback-interrupted CAS before it reaches the store."""

    def __init__(self) -> None:
        super().__init__()
        self.interrupted_finalize_started = asyncio.Event()
        self.allow_interrupted_finalize = asyncio.Event()

    async def finalize_cancelled_completion_if_owned(self, *args, **kwargs):
        if kwargs.get("status") == RunStatus.interrupted.value:
            self.interrupted_finalize_started.set()
            await self.allow_interrupted_finalize.wait()
        return await super().finalize_cancelled_completion_if_owned(
            *args,
            **kwargs,
        )


class BlockingFirstOwnedFinalizeStore(MemoryRunStore):
    """Let a newer same-status snapshot race an older owner finalizer."""

    def __init__(self) -> None:
        super().__init__()
        self.first_finalize_started = asyncio.Event()
        self.allow_first_finalize = asyncio.Event()
        self.finalize_calls = 0

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        self.finalize_calls += 1
        if self.finalize_calls == 1:
            self.first_finalize_started.set()
            await self.allow_first_finalize.wait()
        return await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )


class FailStartFallbackReadFailStore(BlockingFirstOwnedFinalizeStore):
    """Lose fail_start's immediate cancel-winner read after its CAS miss."""

    def __init__(self) -> None:
        super().__init__()
        self.reads_after_finalize_miss = 0
        self.finalize_missed = False

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        result = await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )
        if not result.finalized:
            self.finalize_missed = True
        return result

    async def get(self, run_id, *, user_id=None):
        if self.finalize_missed:
            self.reads_after_finalize_miss += 1
            if self.reads_after_finalize_miss == 2:
                raise RuntimeError("simulated fail_start fallback read outage")
        return await super().get(run_id, user_id=user_id)


class CommitThenRaiseOwnedFinalizeStore(MemoryRunStore):
    """Commit one owner CAS, then simulate a lost database response."""

    def __init__(self) -> None:
        super().__init__()
        self.raise_after_next_commit = True

    async def finalize_completion_if_owned_and_not_cancelled(self, *args, **kwargs):
        result = await super().finalize_completion_if_owned_and_not_cancelled(
            *args,
            **kwargs,
        )
        if result.finalized and self.raise_after_next_commit:
            self.raise_after_next_commit = False
            raise OSError("simulated connection loss after commit")
        return result


class UnconfirmedTerminalWriteStore(MemoryRunStore):
    """Return an ambiguous legacy write result, then make reads unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_reads = False

    async def update_status(self, run_id, status, *, error=None, stop_reason=None):
        run = self._runs[run_id]
        run["status"] = status
        run["error"] = error
        run["stop_reason"] = stop_reason
        run["owner_worker_id"] = None
        run["lease_expires_at"] = None
        self.fail_reads = True
        return None

    async def finalize_completion_if_owned_and_not_cancelled(
        self,
        run_id,
        **kwargs,
    ):
        run = self._runs[run_id]
        run["status"] = kwargs["status"]
        run["error"] = kwargs.get("error")
        run["stop_reason"] = kwargs.get("stop_reason")
        run["owner_worker_id"] = None
        run["lease_expires_at"] = None
        self.fail_reads = True
        return StatusFinalization(finalized=True)

    async def get(self, run_id, *, user_id=None):
        if self.fail_reads:
            raise RuntimeError("simulated authority read outage")
        return await super().get(run_id, user_id=user_id)


async def _terminal_run(manager: RunManager, thread_id: str = "thread-eviction") -> str:
    record = await manager.create(thread_id)
    await manager.set_status(record.run_id, RunStatus.success)
    return record.run_id


async def _forget_local_record(manager: RunManager, run_id: str, thread_id: str) -> None:
    """Drop a local entry so the next idempotent admission hydrates it."""
    async with manager._lock:
        manager._runs.pop(run_id, None)
        manager._unindex_run_locked(run_id, thread_id)


@pytest.mark.asyncio
async def test_memory_only_manager_preserves_terminal_history():
    manager = RunManager()
    run_id = await _terminal_run(manager)

    assert manager.schedule_terminal_eviction(run_id, delay=0) is None
    assert run_id in manager._runs


@pytest.mark.asyncio
async def test_terminal_eviction_prunes_both_indexes_and_hydrates_from_store():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)
    thread_id = manager._runs[run_id].thread_id

    task = manager.schedule_terminal_eviction(run_id, delay=0)
    assert task is not None
    await task

    assert run_id not in manager._runs
    assert thread_id not in manager._runs_by_thread
    hydrated = await manager.get(run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_terminal_idempotent_reuse_stays_store_only():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create_or_reject(
        "thread-idempotent-terminal",
        user_id="user-a",
        idempotency_key="idempotency-terminal-1",
    )
    await manager.set_status(record.run_id, RunStatus.success)
    await _forget_local_record(manager, record.run_id, record.thread_id)

    reused = await manager.create_or_reject(
        record.thread_id,
        user_id="user-a",
        idempotency_key="idempotency-terminal-1",
    )

    assert reused.run_id == record.run_id
    assert reused.idempotency_reused is True
    assert reused.status == RunStatus.success
    assert reused.store_only is True
    assert record.run_id not in manager._runs
    assert record.thread_id not in manager._runs_by_thread

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_inflight_idempotent_reuse_stays_store_only_and_cancels_remotely():
    store = MemoryRunStore()
    ownership = RunOwnershipConfig(
        lease_seconds=30,
        grace_seconds=10,
        heartbeat_enabled=True,
    )
    owner = RunManager(
        store=store,
        worker_id="worker-owner",
        run_ownership_config=ownership,
    )
    peer = RunManager(
        store=store,
        worker_id="worker-peer",
        run_ownership_config=ownership,
    )
    record = await owner.create_or_reject(
        "thread-idempotent-inflight",
        user_id="user-a",
        idempotency_key="idempotency-inflight-1",
    )
    assert await owner.try_start(record.run_id) == RunStartOutcome.started

    reused = await peer.create_or_reject(
        "thread-idempotent-inflight",
        user_id="user-a",
        idempotency_key="idempotency-inflight-1",
    )

    assert reused.idempotency_reused is True
    assert reused.status == RunStatus.running
    assert reused.store_only is True
    assert reused.run_id not in peer._runs
    assert reused.thread_id not in peer._runs_by_thread
    with pytest.raises(RunStartupError):
        await peer.try_start(reused.run_id)

    outcome = await peer.cancel(reused.run_id, action="rollback")
    stored = await store.get(reused.run_id)
    assert outcome == CancelOutcome.requested
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-owner"
    assert stored["cancel_action"] == "rollback"
    assert reused.abort_event.is_set() is False

    await owner._renew_leases()
    assert record.abort_event.is_set() is True
    assert record.abort_action == "rollback"

    await owner.set_status(
        record.run_id,
        RunStatus.error,
        error="Rolled back by user",
    )
    hydrated = await peer.get(record.run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.error
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_local_rollback_requires_a_live_owned_durable_lease():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-expired-local-cancel")
    await manager.try_start(record.run_id)
    expired = "2000-01-01T00:00:00+00:00"
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired

    outcome = await manager.cancel(record.run_id, action="rollback")
    stored = await store.get(record.run_id)
    assert outcome == CancelOutcome.unknown
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["cancel_action"] == "rollback"
    assert record.abort_action == "interrupt"
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_heartbeat_local_rollback_fails_closed_without_durable_cancel_capability():
    store = UnsupportedDurableCancellationRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-unsupported-durable-cancel")
    await manager.try_start(record.run_id)

    outcome = await manager.cancel(record.run_id, action="rollback")
    stored = await store.get(record.run_id)
    assert outcome == CancelOutcome.lease_valid_elsewhere
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored.get("cancel_action") is None
    assert record.status == RunStatus.running
    assert record.abort_action == "interrupt"
    assert record.abort_event.is_set() is False


@pytest.mark.asyncio
async def test_fail_start_adopts_durable_cancel_winner_before_worker_attach():
    store = BlockingFirstOwnedFinalizeStore()
    ownership = RunOwnershipConfig(
        lease_seconds=30,
        grace_seconds=10,
        heartbeat_enabled=True,
    )
    owner = RunManager(
        store=store,
        worker_id="worker-owner",
        run_ownership_config=ownership,
    )
    peer = RunManager(
        store=store,
        worker_id="worker-peer",
        run_ownership_config=ownership,
    )
    record = await owner.create("thread-fail-start-cancel-winner")

    fail_start = asyncio.create_task(
        owner.fail_start_if_pending(
            record.run_id,
            error="Failed to attach run worker",
        )
    )
    try:
        await asyncio.wait_for(store.first_finalize_started.wait(), timeout=5)
        assert record.run_id in owner._terminal_eviction_tasks
        assert await peer.cancel(record.run_id, action="interrupt") == CancelOutcome.requested
    finally:
        store.allow_first_finalize.set()

    assert await asyncio.wait_for(fail_start, timeout=5) is True
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["cancel_action"] == "interrupt"
    assert record.status == RunStatus.interrupted
    assert record.abort_action == "interrupt"
    assert record.ownership_lost is False

    await owner._renew_leases()
    assert record.durable_terminal_authority_status == RunStatus.interrupted
    await owner._stop_terminal_evictions(timeout=1)


@pytest.mark.asyncio
async def test_fail_start_adopts_cancel_on_heartbeat_after_fallback_read_outage():
    store = FailStartFallbackReadFailStore()
    ownership = RunOwnershipConfig(
        lease_seconds=30,
        grace_seconds=10,
        heartbeat_enabled=True,
    )
    owner = RunManager(
        store=store,
        worker_id="worker-owner",
        run_ownership_config=ownership,
    )
    peer = RunManager(
        store=store,
        worker_id="worker-peer",
        run_ownership_config=ownership,
    )
    record = await owner.create("thread-fail-start-heartbeat-cancel")

    fail_start = asyncio.create_task(
        owner.fail_start_if_pending(
            record.run_id,
            error="Failed to attach run worker",
        )
    )
    try:
        await asyncio.wait_for(store.first_finalize_started.wait(), timeout=5)
        assert await peer.cancel(record.run_id, action="rollback") == CancelOutcome.requested
    finally:
        store.allow_first_finalize.set()

    assert await asyncio.wait_for(fail_start, timeout=5) is True
    active = await store.get(record.run_id)
    assert active is not None
    assert active["status"] == RunStatus.pending.value
    assert active["cancel_action"] == "rollback"
    assert record.status == RunStatus.error
    assert record.abort_action == "interrupt"

    await owner._renew_leases()
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["cancel_action"] == "rollback"
    assert stored["error"] == "Rolled back by user"
    assert record.abort_action == "rollback"
    assert record.ownership_lost is False
    await owner._stop_terminal_evictions(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("durable_action", "replacement_strategy"),
    [
        ("interrupt", "rollback"),
        ("rollback", "interrupt"),
    ],
)
async def test_replacement_admission_preserves_first_durable_cancel_action(
    durable_action,
    replacement_strategy,
):
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    original = await manager.create_or_reject("thread-admission-cancel-winner")
    await manager.try_start(original.run_id)
    assert (
        await store.request_cancel(
            original.run_id,
            action=durable_action,
        )
        == durable_action
    )

    replacement = await manager.create_or_reject(
        original.thread_id,
        multitask_strategy=replacement_strategy,
    )
    stored_original = await store.get(original.run_id)
    assert replacement.run_id != original.run_id
    assert stored_original is not None
    assert stored_original["status"] == RunStatus.interrupted.value
    assert stored_original["cancel_action"] == durable_action
    assert original.status == RunStatus.interrupted
    assert original.abort_action == durable_action


@pytest.mark.asyncio
async def test_terminal_eviction_skips_redundant_writes_when_store_snapshot_matches():
    store = RecoveringRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread-already-durable")
    await manager.try_start(record.run_id)
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await manager.update_finalizing_progress(record.run_id, total_tokens=42)
    assert await manager.persist_current_status(record.run_id) is True
    completion_payload = manager._completion_payload(record)
    await manager.update_run_completion(record.run_id, **completion_payload)
    status_writes = store.status_write_calls
    completion_writes = store.completion_write_calls
    reads = store.get_calls

    task = manager.schedule_terminal_eviction(record.run_id, delay=0)
    assert task is not None
    await task

    assert store.status_write_calls == status_writes
    assert store.completion_write_calls == completion_writes
    assert store.get_calls == reads + 1
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_eviction_waits_for_terminal_persistence_and_retries_after_recovery(caplog):
    caplog.set_level("DEBUG", logger="deerflow.runtime.runs.manager")
    store = RecoveringRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=1, initial_delay=0),
    )
    record = await manager.create("thread-persistence-recovery")
    store.fail_terminal_writes = True
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="worker failed",
        stop_reason="tool_capped",
    )
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=42,
    )

    task = manager.schedule_terminal_eviction(record.run_id, delay=0, retry_delay=0.01)
    assert task is not None
    await asyncio.wait_for(store.read_while_stale.wait(), timeout=1)
    assert record.run_id in manager._runs

    async def wait_for_retry_log() -> None:
        while "retained pending durable terminal state" not in caplog.text:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_retry_log(), timeout=5)
    assert "retained pending durable terminal state" in caplog.text

    store.fail_terminal_writes = False
    await asyncio.wait_for(task, timeout=1)

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.status == RunStatus.error
    assert hydrated.error == "worker failed"
    assert hydrated.stop_reason == "tool_capped"
    assert hydrated.total_tokens == 42
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_eviction_owner_cas_repairs_same_worker_active_row():
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-owned-active-repair")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="worker failed",
        stop_reason="tool_capped",
        persist=False,
    )
    record.total_tokens = 42

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["owner_worker_id"] == "worker-local"
    assert stored["error"] == "worker failed"
    assert stored["stop_reason"] == "tool_capped"
    assert stored["total_tokens"] == 42
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_eviction_does_not_overwrite_live_active_row_owned_by_peer():
    store = RecoveringRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-peer-owned-active")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await store.put(
        record.run_id,
        thread_id=record.thread_id,
        status=RunStatus.running.value,
        operation_kind="run",
        multitask_strategy="reject",
        metadata={},
        kwargs={},
        owner_worker_id="worker-peer",
        lease_expires_at="2099-01-01T00:00:00+00:00",
    )

    assert await manager._evict_if_durable_terminal(record.run_id) is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-peer"
    assert store.status_write_calls == 0
    assert store.completion_write_calls == 0
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_terminal_status_does_not_overwrite_peer_owned_active_row():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-peer-before-terminal-status")
    await store.put(
        record.run_id,
        thread_id=record.thread_id,
        status=RunStatus.running.value,
        owner_worker_id="worker-peer",
        lease_expires_at="2099-01-01T00:00:00+00:00",
    )

    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="stale local failure",
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-peer"
    assert stored.get("error") is None
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_not_cancelled_finalizer_does_not_overwrite_peer_owned_active_row():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-peer-before-finalize-cas")
    await store.put(
        record.run_id,
        thread_id=record.thread_id,
        status=RunStatus.running.value,
        owner_worker_id="worker-peer",
        lease_expires_at="2099-01-01T00:00:00+00:00",
    )

    assert (
        await manager.set_status_if_not_cancelled(
            record.run_id,
            RunStatus.success,
        )
        is None
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-peer"
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_expired_local_lease_cannot_terminalize_active_row():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-expired-before-terminal")
    expired = "2000-01-01T00:00:00+00:00"
    record.lease_expires_at = expired
    store._runs[record.run_id]["lease_expires_at"] = expired

    await manager.set_status(record.run_id, RunStatus.success)

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.pending.value
    assert stored["owner_worker_id"] == "worker-local"
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_stale_owner_does_not_adopt_preserved_cancel_action_after_takeover():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-cancel-before-takeover")
    await manager.try_start(record.run_id)
    assert await store.request_cancel(record.run_id, action="rollback") == "rollback"
    store._runs[record.run_id]["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    assert (
        await store.claim_for_takeover(
            record.run_id,
            grace_seconds=10,
            error="peer recovered expired owner",
            stop_reason="orphan_recovered",
        )
        is True
    )

    assert (
        await manager.set_status_if_not_cancelled(
            record.run_id,
            RunStatus.success,
        )
        is None
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["owner_worker_id"] is None
    assert stored["cancel_action"] == "rollback"
    assert record.abort_event.is_set() is True
    assert record.abort_action == "interrupt"
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_rejected_renewal_recognizes_just_committed_local_terminal_row():
    store = BlockingOwnedFinalizeReturnStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-finalize-renew-race")
    record.task = asyncio.create_task(asyncio.Event().wait())
    finalization = asyncio.create_task(
        manager.set_status_if_not_cancelled(
            record.run_id,
            RunStatus.success,
        )
    )

    try:
        await asyncio.wait_for(store.finalize_committed.wait(), timeout=5)
        assert record.status == RunStatus.success
        assert record.durable_terminal_authority_status is None

        await manager._renew_leases()

        assert record.ownership_lost is False
        assert record.durable_terminal_authority_status == RunStatus.success
    finally:
        store.allow_finalize_return.set()
        await asyncio.wait_for(finalization, timeout=5)
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_rejected_renewal_does_not_prove_incomplete_terminal_snapshot():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-incomplete-terminal-renew")
    record.task = asyncio.create_task(asyncio.Event().wait())
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    record.total_tokens = 17
    store._runs[record.run_id]["status"] = RunStatus.success.value

    try:
        await manager._renew_leases()

        assert record.ownership_lost is False
        assert record.durable_terminal_authority_status is None
        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.success.value
        assert stored.get("total_tokens") in (None, 0)
    finally:
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_finalizer_recovers_when_database_response_is_lost_after_commit():
    store = CommitThenRaiseOwnedFinalizeStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-lost-finalize-response")

    assert (
        await manager.set_status_if_not_cancelled(
            record.run_id,
            RunStatus.success,
        )
        is None
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert stored["owner_worker_id"] == "worker-local"
    assert record.ownership_lost is False
    assert record.durable_terminal_authority_status == RunStatus.success


@pytest.mark.asyncio
async def test_cancelled_finalizer_uses_confirmed_proof_when_verification_read_fails():
    store = AuthorityReadFailAfterCancelledFinalizeStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-cancelled-finalize-proof")
    await manager.try_start(record.run_id)

    assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.cancelled

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["cancel_action"] == "interrupt"
    assert stored["owner_worker_id"] == "worker-local"
    assert record.ownership_lost is False
    assert record.durable_terminal_authority_status == RunStatus.interrupted


@pytest.mark.asyncio
async def test_single_worker_store_without_owner_cas_uses_legacy_compatibility():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-unsupported-owner-cas")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert store.status_write_calls == 0
    assert store.completion_write_calls == 1
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_multi_worker_store_without_owner_cas_fails_closed():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-unsupported-owner-cas-multi-worker")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)

    assert await manager._evict_if_durable_terminal(record.run_id) is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.pending.value
    assert store.status_write_calls == 0
    assert store.completion_write_calls == 0
    assert manager._runs[record.run_id] is record
    assert record.ownership_lost is True

    supervisor = manager.schedule_terminal_eviction(record.run_id, delay=300)
    assert supervisor is not None
    store.update_lease = AsyncMock(wraps=store.update_lease)
    try:
        await manager._renew_leases()
        store.update_lease.assert_not_awaited()
    finally:
        supervisor.cancel()
        await asyncio.gather(supervisor, return_exceptions=True)


@pytest.mark.asyncio
async def test_single_worker_legacy_store_recovers_missing_terminal_row():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-legacy-missing")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    record.total_tokens = 23
    await store.delete(record.run_id)

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert stored["total_tokens"] == 23
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_multi_worker_legacy_store_keeps_missing_terminal_row():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-legacy-missing-multi-worker")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await store.delete(record.run_id)

    assert await manager._evict_if_durable_terminal(record.run_id) is False
    assert await store.get(record.run_id) is None
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_single_worker_legacy_store_repairs_same_terminal_snapshot():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-legacy-same-terminal")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    record.total_tokens = 31
    assert await store.update_status(record.run_id, RunStatus.success.value)

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert stored["total_tokens"] == 31


@pytest.mark.asyncio
async def test_multi_worker_legacy_store_repairs_verified_owned_terminal_snapshot():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-legacy-same-terminal-multi-worker")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    record.total_tokens = 31
    assert await store.update_status(record.run_id, RunStatus.success.value)

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert stored["total_tokens"] == 31
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_single_worker_legacy_fallback_refuses_peer_owned_active_row():
    store = UnsupportedOwnedFinalizeRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-legacy-peer-owned")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await store.put(
        record.run_id,
        thread_id=record.thread_id,
        status=RunStatus.running.value,
        owner_worker_id="worker-peer",
        lease_expires_at="2099-01-01T00:00:00+00:00",
    )

    assert await manager._evict_if_durable_terminal(record.run_id) is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-peer"
    assert store.completion_write_calls == 0
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_eviction_fails_closed_on_malformed_owner_cas_result():
    store = MalformedOwnedFinalizeRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-malformed-owner-cas")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)

    assert await manager._evict_if_durable_terminal(record.run_id) is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.pending.value
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_eviction_does_not_overwrite_cancellation_that_won():
    store = RecoveringRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-cancel-won")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    assert await store.request_cancel(record.run_id, action="rollback") == "rollback"

    assert await manager._evict_if_durable_terminal(record.run_id) is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.pending.value
    assert stored["cancel_action"] == "rollback"
    assert store.status_write_calls == 0
    assert store.completion_write_calls == 0
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_terminal_status_missing_row_uses_atomic_insert_capability():
    store = RecordingTerminalInsertRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-missing-status-row")
    await store.delete(record.run_id)

    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="local failure",
    )

    stored = await store.get(record.run_id)
    assert store.terminal_insert_calls == 1
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "local failure"
    assert stored["owner_worker_id"] == "worker-local"


@pytest.mark.asyncio
async def test_missing_row_is_recreated_with_full_snapshot_and_list_fallback():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread-missing-row")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="worker failed",
        stop_reason="loop_capped",
    )
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=73,
        message_count=4,
        last_ai_message="final answer",
    )
    await store.delete(record.run_id)

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "worker failed"
    assert stored["stop_reason"] == "loop_capped"
    assert stored["total_tokens"] == 73
    assert stored["message_count"] == 4
    assert stored["last_ai_message"] == "final answer"
    assert record.run_id not in manager._runs
    assert record.thread_id not in manager._runs_by_thread
    history = await manager.list_by_thread(record.thread_id)
    assert [item.run_id for item in history] == [record.run_id]
    assert history[0].store_only is True


@pytest.mark.asyncio
async def test_missing_row_recovery_does_not_overwrite_concurrent_peer_insert():
    store = BlockingTerminalInsertRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-missing-row-race")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await store.delete(record.run_id)

    eviction = asyncio.create_task(manager._evict_if_durable_terminal(record.run_id))
    try:
        await asyncio.wait_for(store.insert_started.wait(), timeout=5)
        await store.put(
            record.run_id,
            thread_id=record.thread_id,
            status=RunStatus.running.value,
            operation_kind="run",
            multitask_strategy="reject",
            metadata={},
            kwargs={},
            owner_worker_id="worker-peer",
            lease_expires_at="2099-01-01T00:00:00+00:00",
        )
    finally:
        store.allow_insert.set()

    assert await asyncio.wait_for(eviction, timeout=5) is False
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["owner_worker_id"] == "worker-peer"
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_same_terminal_status_with_conflicting_snapshot_is_authoritative():
    store = RecoveringRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-peer-terminal-same-status")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="local worker failed",
        persist=False,
    )
    store._runs[record.run_id]["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    assert await store.claim_for_takeover(
        record.run_id,
        grace_seconds=0,
        error="peer lease takeover",
        stop_reason="orphan_recovered",
    )
    completion_writes = store.completion_write_calls

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["error"] == "peer lease takeover"
    assert stored["stop_reason"] == "orphan_recovered"
    assert stored["owner_worker_id"] is None
    assert store.completion_write_calls == completion_writes
    assert record.ownership_lost is True
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_normal_completion_does_not_overwrite_same_status_peer_terminal():
    store = RecoveringRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-peer-terminal-before-completion")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="local worker failed",
        stop_reason="tool_capped",
        persist=False,
    )
    store._runs[record.run_id]["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    assert await store.claim_for_takeover(
        record.run_id,
        grace_seconds=0,
        error="peer lease takeover",
        stop_reason="orphan_recovered",
    )
    completion_writes = store.completion_write_calls

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=99,
        message_count=7,
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["error"] == "peer lease takeover"
    assert stored["stop_reason"] == "orphan_recovered"
    assert stored["owner_worker_id"] is None
    assert stored.get("total_tokens") in (None, 0)
    assert stored.get("message_count") in (None, 0)
    assert store.completion_write_calls == completion_writes
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_matching_same_status_peer_terminal_still_fences_local_side_effects():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-matching-peer-terminal")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="identical failure",
        persist=False,
    )
    store._runs[record.run_id]["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
    assert await store.claim_for_takeover(
        record.run_id,
        grace_seconds=0,
        error="identical failure",
    )

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "identical failure"
    assert stored["owner_worker_id"] is None
    assert record.ownership_lost is True


@pytest.mark.asyncio
async def test_different_peer_terminal_outcome_is_authoritative_and_evicts():
    store = RecoveringRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-peer-terminal-different-status")
    await manager.set_status(record.run_id, RunStatus.success, persist=False)
    await store.update_status(
        record.run_id,
        RunStatus.error.value,
        error="peer lease takeover",
        stop_reason="orphan_recovered",
    )
    completion_writes = store.completion_write_calls

    assert await manager._evict_if_durable_terminal(record.run_id) is True

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "peer lease takeover"
    assert store.completion_write_calls == completion_writes
    assert record.run_id not in manager._runs


@pytest.mark.asyncio
async def test_ownership_lost_missing_row_is_not_recreated():
    store = MemoryRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread-missing-row-ownership-lost")
    await manager.set_status(record.run_id, RunStatus.error)
    record.ownership_lost = True
    await store.delete(record.run_id)

    assert await manager._evict_if_durable_terminal(record.run_id) is False
    assert await store.get(record.run_id) is None
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_eviction_rechecks_local_status_after_store_verification():
    store = BlockingReadRunStore()
    manager = RunManager(store=store)
    record = await manager.create("thread-status-recheck")
    await manager.set_status(record.run_id, RunStatus.success)
    store.block_next_get = True

    eviction = asyncio.create_task(manager._evict_if_durable_terminal(record.run_id))
    try:
        await asyncio.wait_for(store.read_started.wait(), timeout=5)
        await manager.set_status(record.run_id, RunStatus.error, persist=False)
    finally:
        store.allow_read.set()

    assert await asyncio.wait_for(eviction, timeout=5) is False
    assert manager._runs[record.run_id] is record
    assert record.status == RunStatus.error
    assert record.run_id in manager._runs_by_thread[record.thread_id]


@pytest.mark.asyncio
async def test_eviction_retains_record_when_initial_store_read_fails():
    store = FailingReadRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=1, initial_delay=0),
    )
    record = await manager.create("thread-store-read-failure")
    await manager.set_status(record.run_id, RunStatus.success)
    store.fail_reads = True

    assert await manager._evict_if_durable_terminal(record.run_id) is False
    assert manager._runs[record.run_id] is record


@pytest.mark.asyncio
async def test_completion_snapshot_preserves_stop_reason_when_status_write_failed():
    store = StatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        persistence_retry_policy=PersistenceRetryPolicy(max_attempts=1, initial_delay=0),
    )
    record = await manager.create("thread-stop-reason-repair")
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="worker failed",
        stop_reason="token_capped",
    )

    # This mirrors worker finalization: the completion write can make status
    # terminal even though the earlier status write failed. The completion
    # snapshot itself must carry stop_reason, avoiding an unsafe later repair.
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=42,
    )
    stored_before_eviction = await store.get(record.run_id)
    assert stored_before_eviction is not None
    assert stored_before_eviction["status"] == RunStatus.error.value
    assert stored_before_eviction["error"] == "worker failed"
    assert stored_before_eviction["stop_reason"] == "token_capped"

    task = manager.schedule_terminal_eviction(record.run_id, delay=0)
    assert task is not None
    await asyncio.wait_for(task, timeout=1)

    hydrated = await manager.get(record.run_id)
    assert hydrated is not None
    assert hydrated.error == "worker failed"
    assert hydrated.stop_reason == "token_capped"
    assert hydrated.total_tokens == 42
    assert hydrated.store_only is True


@pytest.mark.asyncio
async def test_terminal_status_owner_cas_includes_full_snapshot_after_progress_failure():
    store = ProgressWriteFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-finalizing-progress-failed")
    await manager.try_start(record.run_id)
    await manager.set_status(
        record.run_id,
        RunStatus.success,
        stop_reason="completed",
        persist=False,
    )
    await manager.update_finalizing_progress(
        record.run_id,
        total_tokens=81,
        message_count=4,
        last_ai_message="finished",
    )
    assert await manager.persist_current_status(record.run_id) is True

    stored_before = await store.get(record.run_id)
    assert stored_before is not None
    assert stored_before["status"] == RunStatus.success.value
    assert stored_before["total_tokens"] == 81
    assert stored_before["message_count"] == 4
    assert stored_before["last_ai_message"] == "finished"

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.success.value,
        total_tokens=81,
        message_count=4,
        last_ai_message="finished",
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["total_tokens"] == 81
    assert stored["message_count"] == 4
    assert stored["last_ai_message"] == "finished"
    assert stored["stop_reason"] == "completed"
    assert await manager._evict_if_durable_terminal(record.run_id) is True


@pytest.mark.asyncio
async def test_same_status_owner_cas_persists_cancelled_run_completion():
    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-cancelled-completion")
    await manager.try_start(record.run_id)
    await manager.update_run_progress(
        record.run_id,
        total_tokens=10,
        message_count=1,
    )
    assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.cancelled
    assert record.abort_action == "interrupt"

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.interrupted.value,
        total_tokens=55,
        message_count=3,
        last_ai_message="partial",
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["cancel_action"] == "interrupt"
    assert stored.get("error") is None
    assert stored["total_tokens"] == 55
    assert stored["message_count"] == 3
    assert stored["last_ai_message"] == "partial"
    assert await manager._evict_if_durable_terminal(record.run_id) is True


@pytest.mark.asyncio
async def test_cancel_owner_cas_recovers_when_terminal_status_write_failed():
    store = CancellationStatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-cancel-status-failed")
    await manager.try_start(record.run_id)
    store.fail_next_terminal_status = True

    assert await manager.cancel(record.run_id, action="interrupt") == CancelOutcome.cancelled
    assert record.abort_action == "interrupt"
    active = await store.get(record.run_id)
    assert active is not None
    assert active["status"] == RunStatus.running.value
    assert active["cancel_action"] == "interrupt"

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.interrupted.value,
        total_tokens=55,
        message_count=3,
        last_ai_message="partial",
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.interrupted.value
    assert stored["cancel_action"] == "interrupt"
    assert stored["owner_worker_id"] == "worker-local"
    assert stored.get("error") is None
    assert stored["total_tokens"] == 55
    assert stored["message_count"] == 3
    assert stored["last_ai_message"] == "partial"
    assert await manager._evict_if_durable_terminal(record.run_id) is True


@pytest.mark.asyncio
async def test_cancel_owner_cas_finishes_rollback_after_error_status_write_failed():
    store = CancellationStatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-rollback-error-status-failed")
    await manager.try_start(record.run_id)
    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    assert record.abort_action == "rollback"
    active = await store.get(record.run_id)
    assert active is not None
    assert active["status"] == RunStatus.running.value
    assert active["cancel_action"] == "rollback"

    store.fail_next_terminal_status = True
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="Rolled back by user",
    )
    still_active = await store.get(record.run_id)
    assert still_active is not None
    assert still_active["status"] == RunStatus.running.value
    # The live owner keeps this active admission fence leased while the
    # supervised completion retry repairs the final rollback snapshot.

    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=34,
        message_count=2,
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["cancel_action"] == "rollback"
    assert stored["owner_worker_id"] == "worker-local"
    assert stored["error"] == "Rolled back by user"
    assert stored["total_tokens"] == 34
    assert stored["message_count"] == 2
    assert await manager._evict_if_durable_terminal(record.run_id) is True


@pytest.mark.asyncio
async def test_owner_cas_finishes_legacy_rollback_without_durable_cancel_action():
    store = CancellationStatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-local-rollback-undurable-request")
    await manager.try_start(record.run_id)
    record.abort_action = "rollback"
    record.abort_event.set()
    await manager.set_status(record.run_id, RunStatus.interrupted)
    interrupted = await store.get(record.run_id)
    assert interrupted is not None
    assert interrupted["status"] == RunStatus.interrupted.value
    assert interrupted.get("cancel_action") is None

    store.fail_next_terminal_status = True
    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="Rolled back by user",
    )
    await manager.update_run_completion(
        record.run_id,
        status=RunStatus.error.value,
        total_tokens=21,
        message_count=2,
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored.get("cancel_action") is None
    assert stored["owner_worker_id"] == "worker-local"
    assert stored["error"] == "Rolled back by user"
    assert stored["total_tokens"] == 21
    assert stored["message_count"] == 2
    assert record.ownership_lost is False
    assert await manager._evict_if_durable_terminal(record.run_id) is True


@pytest.mark.asyncio
async def test_stale_interrupted_persist_cannot_fence_newer_rollback_error():
    store = BlockingInterruptedCancellationFinalizeStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-stale-interrupted-persist")
    await manager.try_start(record.run_id)
    assert await store.request_cancel(record.run_id, action="rollback") == "rollback"
    record.abort_action = "rollback"
    record.abort_event.set()
    await manager.set_status(
        record.run_id,
        RunStatus.interrupted,
        persist=False,
    )

    stale_persist = asyncio.create_task(manager.persist_current_status(record.run_id))
    newer_persist: asyncio.Task | None = None
    try:
        await asyncio.wait_for(
            store.interrupted_finalize_started.wait(),
            timeout=5,
        )
        newer_persist = asyncio.create_task(
            manager.set_status(
                record.run_id,
                RunStatus.error,
                error="Rolled back by user",
            )
        )
        for _ in range(10):
            if record.status == RunStatus.error:
                break
            await asyncio.sleep(0)
        assert record.status == RunStatus.error
    finally:
        store.allow_interrupted_finalize.set()

    # The older transition may commit first while holding the per-run
    # persistence lock; the newer rollback error must then advance it without
    # the stale caller fencing local authority.
    assert await asyncio.wait_for(stale_persist, timeout=5) is True
    assert newer_persist is not None
    await asyncio.wait_for(newer_persist, timeout=5)
    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["cancel_action"] == "rollback"
    assert stored["error"] == "Rolled back by user"
    assert record.status == RunStatus.error
    assert record.ownership_lost is False
    assert await manager.verify_terminal_authority(record.run_id) is True


@pytest.mark.asyncio
async def test_older_same_status_snapshot_cannot_overwrite_newer_completion():
    store = BlockingFirstOwnedFinalizeStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-same-status-snapshot-order")
    await manager.try_start(record.run_id)
    record.total_tokens = 10
    await manager.set_status(
        record.run_id,
        RunStatus.success,
        persist=False,
    )

    older = asyncio.create_task(manager.persist_current_status(record.run_id))
    await asyncio.wait_for(store.first_finalize_started.wait(), timeout=5)
    async with manager._lock:
        record.total_tokens = 20
        record.message_count = 2
    newer = asyncio.create_task(manager.persist_current_status(record.run_id))
    await asyncio.sleep(0)
    store.allow_first_finalize.set()
    await asyncio.wait_for(asyncio.gather(older, newer), timeout=5)

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.success.value
    assert stored["total_tokens"] == 20
    assert stored["message_count"] == 2
    assert record.ownership_lost is False


@pytest.mark.asyncio
async def test_single_worker_rollback_keeps_active_fence_until_error_transition():
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="worker-local")
    record = await manager.create("thread-single-worker-rollback")
    await manager.try_start(record.run_id)

    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    active = await store.get(record.run_id)
    assert active is not None
    assert active["status"] == RunStatus.running.value
    assert active.get("cancel_action") is None

    await manager.set_status(
        record.run_id,
        RunStatus.error,
        error="Rolled back by user",
    )

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.error.value
    assert stored["error"] == "Rolled back by user"


@pytest.mark.asyncio
async def test_ambiguous_cancel_response_cannot_overwrite_different_winning_action():
    store = AmbiguousDifferentCancelWinnerStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-ambiguous-different-cancel")
    await manager.try_start(record.run_id)

    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
    assert record.abort_action == "interrupt"
    after_cancel = await store.get(record.run_id)
    assert after_cancel is not None
    assert after_cancel["status"] == RunStatus.interrupted.value
    assert after_cancel["cancel_action"] == "interrupt"
    assert after_cancel.get("error") is None


@pytest.mark.asyncio
async def test_cancel_fails_closed_when_response_and_winner_read_are_both_lost():
    store = AmbiguousCancelWinnerAndReadFailureStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-ambiguous-cancel-and-read")
    await manager.try_start(record.run_id)

    assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.unknown
    assert record.status == RunStatus.running
    assert record.abort_action == "interrupt"
    assert record.abort_event.is_set() is False

    stored = await store.get(record.run_id)
    assert stored is not None
    assert stored["status"] == RunStatus.running.value
    assert stored["cancel_action"] == "interrupt"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.timeout, RunStatus.interrupted])
async def test_terminal_eviction_waits_for_finalizing_barrier(status):
    manager = RunManager(store=MemoryRunStore())
    record = await manager.create(f"thread-finalizing-{status.value}")
    release_worker = asyncio.Event()
    record.task = asyncio.create_task(release_worker.wait())
    await manager.set_finalizing(record.run_id, True)
    await manager.set_status(record.run_id, status)
    newer = await manager.create(record.thread_id)
    wait_task = asyncio.create_task(manager.wait_for_prior_finalizing(record.thread_id, newer.run_id))

    try:
        task = manager.schedule_terminal_eviction(record.run_id, delay=0, retry_delay=0.01)
        assert task is not None
        await asyncio.sleep(0.03)

        assert record.run_id in manager._runs
        assert task.done() is False
        assert wait_task.done() is False

        await manager.set_finalizing(record.run_id, False)
        release_worker.set()
        await record.task
        await asyncio.wait_for(wait_task, timeout=1)
        await asyncio.wait_for(task, timeout=1)

        assert record.run_id not in manager._runs
    finally:
        release_worker.set()
        wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)
        await asyncio.gather(record.task, return_exceptions=True)
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_stranded_finalizing_barrier_does_not_block_later_run_or_eviction():
    manager = RunManager(store=MemoryRunStore())
    stranded = await manager.create("thread-stranded-finalizing")
    await manager.set_finalizing(stranded.run_id, True)
    await manager.set_status(stranded.run_id, RunStatus.error, error="late finalizer failure")
    stranded.task = asyncio.create_task(asyncio.sleep(0))
    await stranded.task

    newer = await manager.create(stranded.thread_id)
    eviction = manager.schedule_terminal_eviction(
        stranded.run_id,
        delay=0,
        retry_delay=0.01,
    )
    assert eviction is not None

    try:
        await asyncio.wait_for(
            manager.wait_for_prior_finalizing(stranded.thread_id, newer.run_id),
            timeout=1,
        )
        await asyncio.wait_for(eviction, timeout=1)

        assert stranded.run_id not in manager._runs
        assert newer.run_id in manager._runs
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_duplicate_eviction_schedules_share_one_task():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)

    first = manager.schedule_terminal_eviction(run_id, delay=3600)
    second = manager.schedule_terminal_eviction(run_id, delay=3600)

    assert first is not None
    assert second is first
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_terminal_eviction_retry_uses_capped_exponential_backoff_with_jitter():
    manager = RunManager(store=MemoryRunStore())
    manager._evict_if_durable_terminal = AsyncMock(side_effect=[False] * 6 + [True])  # type: ignore[method-assign]
    sleeps: list[float] = []
    jitter_bounds: list[tuple[float, float]] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def midpoint_jitter(low: float, high: float) -> float:
        jitter_bounds.append((low, high))
        return (low + high) / 2

    await manager._evict_terminal_when_safe(
        "run-backoff",
        delay=0,
        retry_delay=60,
        sleep=fake_sleep,
        jitter=midpoint_jitter,
    )

    assert sleeps == [60, 120, 240, 480, 600, 600]
    assert jitter_bounds[-1] == (480, 720)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failed_attempts", "expected_warning_count"),
    [
        (TERMINAL_RUN_EVICTION_WARNING_RETRY_COUNT - 1, 0),
        (TERMINAL_RUN_EVICTION_WARNING_RETRY_COUNT + 2, 1),
    ],
)
async def test_terminal_eviction_warns_once_after_repeated_non_convergence(
    caplog,
    failed_attempts,
    expected_warning_count,
):
    caplog.set_level(logging.DEBUG, logger="deerflow.runtime.runs.manager")
    manager = RunManager(store=MemoryRunStore())
    manager._evict_if_durable_terminal = AsyncMock(  # type: ignore[method-assign]
        side_effect=[False] * failed_attempts + [True]
    )

    async def fake_sleep(_delay: float) -> None:
        return None

    await manager._evict_terminal_when_safe(
        "run-non-convergent",
        delay=0,
        retry_delay=60,
        sleep=fake_sleep,
        jitter=lambda low, high: (low + high) / 2,
    )

    retry_logs = [entry for entry in caplog.records if "retained pending durable terminal state" in entry.getMessage()]
    warnings = [entry for entry in retry_logs if entry.levelno == logging.WARNING]
    assert len(retry_logs) == failed_attempts
    assert len(warnings) == expected_warning_count
    if warnings:
        assert f"retry={TERMINAL_RUN_EVICTION_WARNING_RETRY_COUNT}" in warnings[0].getMessage()
    assert manager._evict_if_durable_terminal.await_count == failed_attempts + 1


@pytest.mark.asyncio
async def test_terminal_eviction_initial_retry_is_capped():
    manager = RunManager(store=MemoryRunStore())
    manager._evict_if_durable_terminal = AsyncMock(side_effect=[False, True])  # type: ignore[method-assign]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    await manager._evict_terminal_when_safe(
        "run-initial-cap",
        delay=0,
        retry_delay=10_000,
        sleep=fake_sleep,
        jitter=lambda _low, high: high,
    )

    assert sleeps == [600]


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_evictions_and_rejects_new_ones():
    manager = RunManager(store=MemoryRunStore())
    run_id = await _terminal_run(manager)
    task = manager.schedule_terminal_eviction(run_id, delay=3600)
    assert task is not None

    await manager.shutdown(timeout=1)

    assert task.cancelled()
    assert manager._terminal_eviction_tasks == {}
    assert manager.schedule_terminal_eviction(run_id, delay=0) is None


@pytest.mark.asyncio
async def test_shutdown_caps_terminal_eviction_budget():
    manager = RunManager(store=MemoryRunStore())
    manager._stop_terminal_evictions = AsyncMock()  # type: ignore[method-assign]

    await manager.shutdown(timeout=5)

    budget = manager._stop_terminal_evictions.await_args.kwargs["timeout"]
    assert budget == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_shutdown_retains_pending_eviction_task_until_cancellation_is_observed():
    manager = RunManager(store=MemoryRunStore())
    started = asyncio.Event()
    release = asyncio.Event()

    async def stubborn_eviction() -> None:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(stubborn_eviction())
    manager._terminal_eviction_tasks["run-stubborn"] = task
    task.add_done_callback(lambda done: manager._terminal_eviction_done("run-stubborn", done))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await manager._stop_terminal_evictions(timeout=0)
        assert manager._terminal_eviction_tasks["run-stubborn"] is task
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)
    await asyncio.sleep(0)
    assert task.cancelled()
    assert manager._terminal_eviction_tasks == {}


@pytest.mark.asyncio
async def test_background_terminal_task_is_strongly_referenced_until_done():
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_cleanup() -> None:
        started.set()
        await release.wait()

    task = _spawn_background_terminal_task(delayed_cleanup())
    await asyncio.wait_for(started.wait(), timeout=1)

    assert task in _BACKGROUND_TERMINAL_TASKS

    release.set()
    await asyncio.wait_for(task, timeout=1)
    await asyncio.sleep(0)
    assert task not in _BACKGROUND_TERMINAL_TASKS


@pytest.mark.asyncio
async def test_background_terminal_task_failure_is_observed(caplog):
    caplog.set_level("WARNING", logger="deerflow.runtime.runs.worker")

    async def failed_cleanup() -> None:
        raise RuntimeError("cleanup failed")

    task = _spawn_background_terminal_task(failed_cleanup())
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert task not in _BACKGROUND_TERMINAL_TASKS
    assert "Background terminal task" in caplog.text
    assert "cleanup failed" in caplog.text


@pytest.mark.asyncio
async def test_worker_without_event_store_fences_hooks_after_same_status_takeover():
    class FailingAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            raise RuntimeError("identical failure")
            yield  # pragma: no cover

    store = PeerTakeoverDuringFinalizationStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create("thread-worker-peer-terminal")
    thread_store = SimpleNamespace(
        update_display_name=AsyncMock(),
        update_status=AsyncMock(),
    )
    on_run_completed = AsyncMock()
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    try:
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                thread_store=thread_store,
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: FailingAgent(),
            graph_input={"messages": []},
            config={},
        )

        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.error.value
        assert stored["error"] == "identical failure"
        assert stored["owner_worker_id"] is None
        assert record.ownership_lost is True
        thread_store.update_status.assert_awaited_once_with(
            record.thread_id,
            "running",
        )
        on_run_completed.assert_not_awaited()
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_worker_reuses_local_terminal_proof_when_authority_read_fails():
    class SuccessfulAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            return
            yield  # pragma: no cover

    store = AuthorityReadFailAfterFinalizeStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-authority-read-outage")
    thread_store = SimpleNamespace(
        update_display_name=AsyncMock(),
        update_status=AsyncMock(),
    )
    on_run_completed = AsyncMock()
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    try:
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                thread_store=thread_store,
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: SuccessfulAgent(),
            graph_input={"messages": []},
            config={},
        )

        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.success.value
        assert stored["owner_worker_id"] == "worker-local"
        assert record.ownership_lost is False
        assert record.durable_terminal_authority_status == RunStatus.success
        assert thread_store.update_status.await_args_list == [
            call(record.thread_id, "running"),
            call(record.thread_id, "idle"),
        ]
        on_run_completed.assert_awaited_once_with(record)
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_ambiguous_terminal_write_is_not_local_authority_proof():
    store = UnconfirmedTerminalWriteStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-ambiguous-status-write")

    try:
        await manager.set_status(
            record.run_id,
            RunStatus.error,
            error="local failure",
        )

        assert record.durable_terminal_authority_status is None
        assert await manager.verify_terminal_authority(record.run_id) is False
    finally:
        store.fail_reads = False
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_worker_suppresses_hooks_after_unconfirmed_legacy_finalize():
    class FailingAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            raise RuntimeError("local failure")
            yield  # pragma: no cover

    store = UnconfirmedTerminalWriteStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-unconfirmed-worker-finalize")
    thread_store = SimpleNamespace(
        update_display_name=AsyncMock(),
        update_status=AsyncMock(),
    )
    on_run_completed = AsyncMock()
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    try:
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                thread_store=thread_store,
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: FailingAgent(),
            graph_input={"messages": []},
            config={},
        )

        assert record.durable_terminal_authority_status is None
        thread_store.update_status.assert_awaited_once_with(
            record.thread_id,
            "running",
        )
        on_run_completed.assert_not_awaited()
    finally:
        store.fail_reads = False
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_worker_repairs_rollback_intermediate_before_completion_hook():
    class RollbackAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
            store.fail_next_terminal_status = True
            return
            yield  # pragma: no cover

    store = CancellationStatusWriteFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-worker-rollback-repair")
    thread_store = SimpleNamespace(
        update_display_name=AsyncMock(),
        update_status=AsyncMock(),
    )
    on_run_completed = AsyncMock()
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    try:
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                thread_store=thread_store,
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: RollbackAgent(),
            graph_input={"messages": []},
            config={},
        )

        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.error.value
        assert stored["cancel_action"] == "rollback"
        assert stored["error"] == "Rolled back by user"
        assert record.ownership_lost is False
        assert thread_store.update_status.await_args_list == [
            call(record.thread_id, "running"),
            call(record.thread_id, RunStatus.error.value),
        ]
        on_run_completed.assert_awaited_once_with(record)
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_raises", [False, True])
async def test_worker_handles_cancel_that_wins_during_terminal_finally(agent_raises):
    class SuccessfulAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            if agent_raises:
                raise RuntimeError("original worker failure")
            return
            yield  # pragma: no cover

    class CancelOnReceiptStore(MemoryRunEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled_during_receipt = False

        async def put_if_absent(self, *args, **kwargs):
            if kwargs.get("event_type") == "run.delivery" and not self.cancelled_during_receipt:
                self.cancelled_during_receipt = True
                assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
            return await super().put_if_absent(*args, **kwargs)

    store = MemoryRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
    )
    record = await manager.create(f"thread-late-finally-cancel-{agent_raises}")
    event_store = CancelOnReceiptStore()
    on_run_completed = AsyncMock()
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    worker_task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                event_store=event_store,
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: SuccessfulAgent(),
            graph_input={"messages": []},
            config={},
        )
    )
    record.task = worker_task

    try:
        await asyncio.wait_for(worker_task, timeout=5)

        assert event_store.cancelled_during_receipt is True
        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.error.value
        assert stored["cancel_action"] == "rollback"
        assert stored["error"] == "Rolled back by user"
        assert record.abort_action == "rollback"
        assert record.finalizing is False
        assert record.ownership_lost is False
        bridge.publish_end.assert_awaited_once_with(record.run_id)
        on_run_completed.assert_awaited_once_with(record)
        assert record.run_id in manager._terminal_eviction_tasks
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_late_rollback_fence_failure_still_releases_finalizing_and_schedules_cleanup(
    caplog,
):
    class SuccessfulAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            return
            yield  # pragma: no cover

    class CancelOnReceiptStore(MemoryRunEventStore):
        async def put_if_absent(self, *args, **kwargs):
            if kwargs.get("event_type") == "run.delivery":
                assert await manager.cancel(record.run_id, action="rollback") == CancelOutcome.cancelled
            return await super().put_if_absent(*args, **kwargs)

    caplog.set_level(logging.WARNING, logger="deerflow.runtime.runs.worker")
    store = CheckpointMutationFenceFailingRunStore()
    manager = RunManager(
        store=store,
        worker_id="worker-local",
        run_ownership_config=RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        ),
        persistence_retry_policy=PersistenceRetryPolicy(
            max_attempts=1,
            initial_delay=0,
        ),
    )
    record = await manager.create("thread-late-rollback-fence-outage")
    manager.schedule_terminal_eviction = MagicMock(return_value=None)  # type: ignore[method-assign]
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    on_run_completed = AsyncMock()

    worker_task = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(
                checkpointer=None,
                event_store=CancelOnReceiptStore(),
                on_run_completed=on_run_completed,
            ),
            agent_factory=lambda **_kwargs: SuccessfulAgent(),
            graph_input={"messages": []},
            config={},
        )
    )
    record.task = worker_task

    try:
        with pytest.raises(
            RuntimeError,
            match="simulated checkpoint mutation fence outage",
        ):
            await asyncio.wait_for(worker_task, timeout=5)

        assert record.status == RunStatus.error
        assert record.ownership_lost is True
        assert record.finalizing is False
        assert record.checkpoint_mutation_fence_active is False
        assert record.error == "Durable checkpoint mutation authority failed while held."
        assert "Failed to finish late cancellation" in caplog.text
        stored = await store.get(record.run_id)
        assert stored is not None
        assert stored["status"] == RunStatus.running.value
        assert stored["cancel_action"] == "rollback"
        on_run_completed.assert_not_awaited()
        manager.schedule_terminal_eviction.assert_called_once_with(record.run_id)
        bridge.publish_end.assert_awaited_once_with(record.run_id)
        await asyncio.sleep(0)
        bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_worker_schedules_eviction_even_when_publish_end_fails():
    class EmptyAgent:
        metadata: dict = {}
        checkpointer = None
        store = None
        interrupt_before_nodes: list[str] = []
        interrupt_after_nodes: list[str] = []

        async def astream(self, *_args, **_kwargs):
            return
            yield  # pragma: no cover

    manager = RunManager(store=MemoryRunStore())
    record = await manager.create("thread-publish-end-failure")
    manager.schedule_terminal_eviction = MagicMock(return_value=None)  # type: ignore[method-assign]
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(side_effect=RuntimeError("stream unavailable")),
        cleanup=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="stream unavailable"):
        await run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None),
            agent_factory=lambda **_kwargs: EmptyAgent(),
            graph_input={"messages": []},
            config={"configurable": {"thread_id": record.thread_id}},
        )

    assert record.status == RunStatus.success
    manager.schedule_terminal_eviction.assert_called_once_with(record.run_id)
    await asyncio.sleep(0)
    bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)
