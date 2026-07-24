"""Tests for multi-worker run ownership (work items 2–3).

Coverage:
- create_or_reject with reject strategy blocks duplicate active runs
- create_or_reject with interrupt strategy claims and cancels old runs
- create_run_atomic refuses to interrupt a run owned by another live worker
- reconcile_orphaned_inflight_runs uses lease-based detection
- Worker reconciliation skips runs with unexpired leases
- Lease heartbeat renews active run leases
- GATEWAY_WORKERS=1 + heartbeat_enabled=false behaviour unchanged
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.manager import CancelOutcome, ConflictError, _generate_worker_id
from deerflow.runtime.runs.store.memory import MemoryRunStore

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
        """MemoryRunStore whose ``create_run_atomic`` always raises a
        real-flavoured unique-violation IntegrityError, simulating a worker
        that keeps losing the cross-worker race for the same thread."""

        def __init__(self):
            super().__init__()
            self.atomic_call_count = 0

        async def create_run_atomic(self, *args, **kwargs):
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
async def test_heartbeat_renews_pending_run_before_task_is_spawned():
    """A run sitting in ``pending`` between ``create_run_atomic`` and task
    spawn must still have its lease renewed.

    Pre-fix the renewal filter required ``record.task is not None``, so a
    pending run with no task yet (the brief window after
    ``create_run_atomic`` inserts the row before the worker layer spawns
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
async def test_create_run_atomic_reject_prevents_duplicate():
    """store.create_run_atomic with reject must raise ConflictError on duplicate."""
    store = MemoryRunStore()
    config = _lease_config()

    store.create_run_atomic = AsyncMock(wraps=store.create_run_atomic)

    await store.create_run_atomic(
        run_id="run-1",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="already has an active run"):
        await store.create_run_atomic(
            run_id="run-2",
            thread_id="thread-1",
            owner_worker_id="w2",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            multitask_strategy="reject",
            grace_seconds=config.grace_seconds,
        )


@pytest.mark.anyio
async def test_create_run_atomic_interrupt_claims_and_creates():
    """store.create_run_atomic with interrupt must claim old and create new."""
    store = MemoryRunStore()
    config = _lease_config()
    # Create an active run with an expired lease (simulating a crashed worker)
    expired_lease = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()

    await store.create_run_atomic(
        run_id="run-old",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=expired_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_run_atomic(
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
async def test_create_run_atomic_interrupt_rejects_other_worker_valid_lease():
    """Interrupt must raise ConflictError when a valid-lease run is owned by another worker.

    The partial unique index ``uq_runs_thread_active`` would reject the INSERT
    anyway; surfacing ConflictError here gives the caller a clean signal
    instead of a futile retry loop on IntegrityError.
    """
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_run_atomic(
        run_id="valid-lease-run",
        thread_id="thread-1",
        owner_worker_id="other-worker",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    with pytest.raises(ConflictError, match="another worker"):
        await store.create_run_atomic(
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
async def test_create_run_atomic_interrupt_allows_self_owned_valid_lease():
    """Interrupt must succeed when the existing valid-lease run is owned by this worker."""
    store = MemoryRunStore()
    config = _lease_config(grace_seconds=10)
    valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    await store.create_run_atomic(
        run_id="self-run",
        thread_id="thread-1",
        owner_worker_id="w1",
        lease_expires_at=valid_lease,
        multitask_strategy="reject",
        grace_seconds=config.grace_seconds,
    )

    new_row, claimed = await store.create_run_atomic(
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
async def test_create_run_atomic_interrupt_rolls_back_earlier_mutations_on_conflict():
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

    # Seed both active rows directly via ``put`` (bypassing create_run_atomic's
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
        await store.create_run_atomic(
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

    ok = await store.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
    assert ok is True

    row = await store.get("run-1")
    assert row is not None
    assert row["status"] == "error"
    assert row["error"] == "claimed"


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


@pytest.mark.anyio
async def test_cancel_refuses_active_lease_from_other_worker():
    """cancel must return lease_valid_elsewhere when the run is owned by another worker with a valid lease."""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    await store.put("run-alive", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="alive-worker", lease_expires_at=valid_lease)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-alive")
    assert outcome == CancelOutcome.lease_valid_elsewhere

    row = await store.get("run-alive")
    assert row is not None
    assert row["status"] == "running"  # untouched


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
    """When the owner heartbeats between our read and the conditional UPDATE, cancel must return lease_valid_elsewhere."""
    store = MemoryRunStore()
    grace = 10
    expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
    await store.put("run-race", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=expired_lease)

    # Simulate the race: right before claim_for_takeover writes, another
    # heartbeat renews the lease.  We monkey-patch claim_for_takeover to
    # simulate the lease having been renewed.
    original = store.claim_for_takeover

    async def race_lost(run_id, *, grace_seconds, error):
        # Simulate a heartbeat renewal between the read and the write
        run = store._runs.get(run_id)
        if run and run["status"] in ("pending", "running"):
            run["lease_expires_at"] = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        return await original(run_id, grace_seconds=grace_seconds, error=error)

    store.claim_for_takeover = race_lost
    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))

    outcome = await manager.cancel("run-race")
    assert outcome == CancelOutcome.lease_valid_elsewhere


@pytest.mark.anyio
async def test_cancel_takeover_respects_grace_seconds():
    """Cancel must not take over when the lease is within the grace window."""
    store = MemoryRunStore()
    grace = 10
    # Lease expired, but only by 3s — still within the 10s grace window
    just_expired = (datetime.now(UTC) - timedelta(seconds=3)).isoformat()
    await store.put("run-grace", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat(), owner_worker_id="w-a", lease_expires_at=just_expired)

    manager = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    outcome = await manager.cancel("run-grace")
    assert outcome == CancelOutcome.lease_valid_elsewhere


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


def _make_cancel_test_app(mgr: RunManager):
    """Build a TestClient wired with the thread_runs router + memory bridge."""
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.routers import thread_runs
    from deerflow.runtime import MemoryStreamBridge

    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    app.state.stream_bridge = MemoryStreamBridge()
    return TestClient(app, raise_server_exceptions=False)


def test_http_cancel_non_owner_valid_lease_returns_409_with_retry_after():
    """POST /cancel on a non-owning worker with a valid lease must return 409 + Retry-After."""
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
    assert resp.status_code == 409
    assert "Retry-After" in resp.headers
    # Retry-After = remaining lease (≈60s) + grace (10s) = ≈70s
    retry_after = int(resp.headers["Retry-After"])
    assert 50 <= retry_after <= 75

    # Store row must be untouched
    row = asyncio.run(store.get("run-alive"))
    assert row["status"] == "running"


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

    # Simulate takeover: directly flip the store row to error
    await store.update_status(record.run_id, "error")

    # Run a single heartbeat tick — it should see update_lease return False
    # and cancel the task
    await mgr._renew_leases()

    # Let the event loop process the cancellation (task.cancel() schedules,
    # doesn't await).
    await asyncio.sleep(0)
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

    async def race_claim(run_id, *, grace_seconds, error):
        store._runs[run_id]["status"] = "success"
        return await original(run_id, grace_seconds=grace_seconds, error=error)

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

    async def race_takeover(run_id, *, grace_seconds, error):
        store._runs[run_id]["status"] = "error"
        store._runs[run_id]["error"] = "peer claim"
        return await original(run_id, grace_seconds=grace_seconds, error=error)

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


# ---------------------------------------------------------------------------
# HTTP — stream endpoint cross-worker 409
# ---------------------------------------------------------------------------


def test_http_stream_action_interrupt_non_owner_returns_409_with_retry_after():
    """POST /stream?action=interrupt on a non-owner with valid lease must
    return 409 + Retry-After, not hang on SSE."""
    store = MemoryRunStore()
    grace = 10
    valid_lease = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    asyncio.run(
        store.put(
            "run-alive-stream",
            thread_id="t1",
            status="running",
            owner_worker_id="alive-worker",
            lease_expires_at=valid_lease,
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    mgr = _make_manager(store=store, run_ownership_config=_lease_config(heartbeat_enabled=True, grace_seconds=grace))
    client = _make_cancel_test_app(mgr)

    resp = client.post("/api/threads/t1/runs/run-alive-stream/stream", params={"action": "interrupt"})
    assert resp.status_code == 409
    assert "Retry-After" in resp.headers
    retry_after = int(resp.headers["Retry-After"])
    assert 50 <= retry_after <= 75
