"""Cross-backend regressions for terminal fencing and cancellation recovery."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.runs.store.base import LOCAL_FINALIZER_PENDING_STOP_REASON, RunStore
from deerflow.runtime.runs.store.memory import MemoryRunStore

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'terminal.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(RunRow.__table__.create)
            await connection.run_sync(RunChangeClockRow.__table__.create)
        yield RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)

    class FixedDatetimeMeta(type):
        def __instancecheck__(cls, instance):
            return isinstance(instance, datetime)

    class FixedDatetime(datetime, metaclass=FixedDatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr("deerflow.runtime.runs.store.memory.datetime", FixedDatetime)
    monkeypatch.setattr("deerflow.persistence.run.sql.datetime", FixedDatetime)
    monkeypatch.setattr("deerflow.utils.time.datetime", FixedDatetime)
    return now


async def _put(store, clock, *, status="running", lease_seconds=30, stop_reason=None):
    await store.put(
        "run-1",
        thread_id="thread-1",
        user_id="alice",
        status=status,
        owner_worker_id="worker-a",
        lease_expires_at=(clock + timedelta(seconds=lease_seconds)).isoformat() if lease_seconds is not None else None,
        stop_reason=stop_reason,
    )


async def _finalize(store, method, *, grace_seconds):
    if method == "completion":
        result = await store.finalize_if_owned_and_not_cancelled("run-1", owner_worker_id="worker-a", status="success", grace_seconds=grace_seconds)
        return result.finalized
    return await store.update_status_if_owned("run-1", "interrupted", owner_worker_id="worker-a", grace_seconds=grace_seconds)


@pytest.mark.parametrize("method", ["completion", "interruption"])
async def test_terminal_commit_uses_takeover_grace_without_renewing_execution(store, clock, method):
    await _put(store, clock, status="pending", lease_seconds=-2)
    # The lease has expired, so no new Agent work may begin; a peer cannot yet
    # take over either. This interval still permits committing the real result.
    assert not await store.start_run_if_owned("run-1", owner_worker_id="worker-a")
    assert not await store.claim_for_takeover_as("run-1", owner_worker_id="worker-b", grace_seconds=10, error="orphan")
    assert await _finalize(store, method, grace_seconds=10)
    row = await store.get("run-1", user_id="alice")
    assert row["status"] == ("success" if method == "completion" else "interrupted")
    assert datetime.fromisoformat(row["lease_expires_at"]) == clock - timedelta(seconds=2)


@pytest.mark.parametrize("method", ["completion", "interruption"])
@pytest.mark.parametrize("lease_seconds", [-11, None])
async def test_terminal_commit_rejects_missing_or_beyond_grace_lease(store, clock, method, lease_seconds):
    await _put(store, clock, lease_seconds=lease_seconds)
    assert not await _finalize(store, method, grace_seconds=10)
    assert (await store.get("run-1", user_id="alice"))["status"] == "running"


async def test_grace_completion_preserves_first_cancel_request(store, clock):
    await _put(store, clock, lease_seconds=-2)
    assert await store.request_cancel("run-1", action="rollback") == "rollback"
    assert await store.request_cancel("run-1", action="interrupt") == "rollback"
    result = await store.finalize_if_owned_and_not_cancelled("run-1", owner_worker_id="worker-a", status="success", grace_seconds=10)
    assert not result.finalized
    assert result.cancel_action == "rollback"
    assert (await store.get("run-1", user_id="alice"))["status"] == "running"


@pytest.mark.parametrize("method", ["completion", "interruption"])
async def test_peer_takeover_fences_old_owner_even_with_grace(store, clock, method):
    await _put(store, clock, lease_seconds=-2)
    assert await store.claim_for_takeover_as("run-1", owner_worker_id="worker-b", grace_seconds=0, error="orphan")
    assert not await _finalize(store, method, grace_seconds=10)
    row = await store.get("run-1", user_id="alice")
    assert row["status"] == "error"
    assert row["owner_worker_id"] == "worker-b"


@pytest.mark.parametrize("status", ["success", "error", "timeout", "interrupted"])
@pytest.mark.parametrize("owned", [False, True])
async def test_local_finalizer_can_clear_marker_for_each_terminal_outcome(store, clock, status, owned):
    await _put(store, clock, status=status, stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON)
    before = dict(await store.get("run-1", user_id="alice"))
    if owned:
        assert await store.update_status_if_owned("run-1", status, owner_worker_id="worker-a")
    else:
        assert await store.update_status("run-1", status)
    changed = await store.list_changed(after_change_seq=before["change_seq"], after_run_id="run-1", user_id="alice")
    assert len(changed) == 1
    assert changed[0]["status"] == status
    assert changed[0]["stop_reason"] is None


@pytest.mark.parametrize("owned", [False, True])
async def test_omitting_stop_reason_preserves_real_stop_reason(store, clock, owned):
    await _put(store, clock, stop_reason="user_cancelled")
    if owned:
        assert await store.update_status_if_owned("run-1", "interrupted", owner_worker_id="worker-a")
    else:
        assert await store.update_status("run-1", "interrupted")
    assert (await store.get("run-1", user_id="alice"))["stop_reason"] == "user_cancelled"


async def test_expired_local_finalizer_cannot_bypass_fence_as_rollback_refinement(store, clock):
    await _put(store, clock, status="interrupted", lease_seconds=-11, stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON)
    assert not await store.update_status_if_owned("run-1", "error", owner_worker_id="worker-a", grace_seconds=10)
    assert (await store.get("run-1", user_id="alice"))["status"] == "interrupted"


@pytest.mark.parametrize("action", [None, "interrupt", "rollback"])
@pytest.mark.parametrize("transfer_owner", [False, True])
async def test_takeover_recovers_accepted_cancellation_as_interrupted(store, clock, action, transfer_owner):
    await _put(store, clock, lease_seconds=-11)
    if action is not None:
        assert await store.request_cancel("run-1", action=action) == action
    before = dict(await store.get("run-1", user_id="alice"))
    kwargs = {"grace_seconds": 10, "error": "Owner stopped", "stop_reason": "orphan_recovered"}
    if transfer_owner:
        claimed = await store.claim_for_takeover_as("run-1", owner_worker_id="worker-b", **kwargs)
    else:
        claimed = await store.claim_for_takeover("run-1", **kwargs)
    assert claimed
    row = await store.get("run-1", user_id="alice")
    assert row["status"] == ("interrupted" if action else "error")
    assert row["cancel_action"] == action
    assert row["stop_reason"] == "orphan_recovered"
    assert row["owner_worker_id"] == ("worker-b" if transfer_owner else "worker-a")
    changed = await store.list_changed(after_change_seq=before["change_seq"], after_run_id="run-1", user_id="alice")
    assert len(changed) == 1
    assert changed[0]["status"] == row["status"]


async def test_local_replacement_retains_explicit_finalizer_lease(store, clock):
    await _put(store, clock)
    deadline = (clock + timedelta(seconds=30)).isoformat()
    _, claimed = await store.create_thread_operation_atomic(
        "run-2",
        thread_id="thread-1",
        user_id="alice",
        owner_worker_id="worker-a",
        lease_expires_at=deadline,
        multitask_strategy="interrupt",
        local_finalizer_run_ids={"run-1"},
        local_finalizer_stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON,
    )
    assert len(claimed) == 1
    assert claimed[0]["lease_expires_at"] is not None
    assert datetime.fromisoformat(claimed[0]["lease_expires_at"]) == datetime.fromisoformat(deadline)
    assert await store.claim_expired_local_finalizer("run-1", owner_worker_id="worker-b", recovery_stop_reason="orphan_recovered", grace_seconds=10) is None


@pytest.mark.parametrize("operation", ["start", "finalize", "recover_finalizer"])
async def test_owner_lifecycle_writes_advance_changed_run_discovery(store, clock, operation):
    if operation == "recover_finalizer":
        await _put(store, clock, status="success", lease_seconds=-20, stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON)
    else:
        await _put(store, clock, status="pending")
    before = dict(await store.get("run-1", user_id="alice"))
    if operation == "start":
        assert await store.start_run_if_owned("run-1", owner_worker_id="worker-a")
        expected = "running"
    elif operation == "finalize":
        assert (await store.finalize_if_owned_and_not_cancelled("run-1", owner_worker_id="worker-a", status="success")).finalized
        expected = "success"
    else:
        assert await store.claim_expired_local_finalizer("run-1", owner_worker_id="worker-b", recovery_stop_reason="orphan_recovered", grace_seconds=10)
        expected = "success"
    changed = await store.list_changed(after_change_seq=before["change_seq"], after_run_id="run-1", user_id="alice")
    assert len(changed) == 1
    assert changed[0]["status"] == expected


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("start_run_if_owned", {"owner_worker_id": "worker-a"}),
        ("update_status_if_owned", {"owner_worker_id": "worker-a", "status": "success"}),
        ("finalize_if_owned_and_not_cancelled", {"owner_worker_id": "worker-a", "status": "success"}),
        ("claim_expired_local_finalizer", {"owner_worker_id": "worker-a", "recovery_stop_reason": "orphan_recovered", "grace_seconds": 10}),
        ("claim_for_takeover_as", {"owner_worker_id": "worker-a", "error": "orphan", "grace_seconds": 10}),
    ],
)
async def test_unimplemented_fencing_primitive_names_required_capability(method, kwargs):
    # Invoke the base implementation directly to model a custom store that has
    # not implemented the new atomic primitive, without an unsafe fallback.
    with pytest.raises(NotImplementedError, match=rf"RunStore\.{method}\(\)"):
        await getattr(RunStore, method)(object(), "run-1", **kwargs)
