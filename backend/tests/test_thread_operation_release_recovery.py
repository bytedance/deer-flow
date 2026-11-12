"""Finished thread operations remain recoverable after a failed SQL release."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.gateway.services import reserve_checkpoint_write
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime import RunManager, RunStatus, ThreadOperationKind
from deerflow.runtime.runs.manager import ConflictError, PersistenceRetryPolicy
from deerflow.runtime.user_context import reset_current_user, set_current_user


@asynccontextmanager
async def database(tmp_path, *, run_ownership_config=None):
    path = tmp_path / "runs.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 0.01})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: RunRow.metadata.create_all(c, tables=[RunRow.__table__, RunChangeClockRow.__table__, CompletedRunSnapshotRow.__table__]))
        repository = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        manager = RunManager(
            store=repository,
            persistence_retry_policy=PersistenceRetryPolicy(max_attempts=2, initial_delay=0),
            run_ownership_config=run_ownership_config,
        )
        with sqlite3.connect(path) as blocker:
            yield manager, repository, blocker
    finally:
        await engine.dispose()


async def fail_release(manager, blocker, *, kind=ThreadOperationKind.checkpoint_write, body_error=False):
    try:
        async with manager.reserve_thread_operation("thread", kind=kind, user_id="alice") as record:
            blocker.execute("BEGIN IMMEDIATE")
            if body_error:
                raise ValueError("original body failure")
    except ValueError:
        if not body_error:
            raise
    return record


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [kind for kind in ThreadOperationKind if kind != ThreadOperationKind.run])
@pytest.mark.parametrize("strategy", ["reject", "interrupt", "rollback"])
async def test_unlock_recovers_finished_reservation_before_new_run(tmp_path, kind, strategy):
    async with database(tmp_path) as (manager, repository, blocker):
        assert not manager.heartbeat_enabled
        finished = await fail_release(manager, blocker, kind=kind)
        blocker.rollback()
        assert (await repository.get(finished.run_id, user_id="alice"))["status"] == "pending"
        token = set_current_user(SimpleNamespace(id="different-context"))
        try:
            successor = await manager.create_or_reject("thread", user_id="alice", multitask_strategy=strategy)
        finally:
            reset_current_user(token)
        assert successor.status.value == "pending"
        assert await repository.get(finished.run_id, user_id="alice") is None
        assert [row["run_id"] for row in await repository.list_inflight()] == [successor.run_id]


@pytest.mark.asyncio
async def test_gateway_checkpoint_boundary_can_retry_after_body_and_release_fail(tmp_path):
    async with database(tmp_path) as (manager, repository, blocker):
        app = SimpleNamespace(state=SimpleNamespace(run_manager=manager))
        request = Request({"type": "http", "app": app})
        with pytest.raises(ValueError, match="original body failure"):
            async with reserve_checkpoint_write(request, "thread", user_id="alice"):
                blocker.execute("BEGIN IMMEDIATE")
                raise ValueError("original body failure")
        blocker.rollback()
        async with reserve_checkpoint_write(request, "thread", user_id="alice"):
            rows = await repository.list_inflight()
            assert len(rows) == 1
            assert rows[0]["operation_kind"] == "checkpoint_write"
        assert await repository.list_inflight() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["reject", "interrupt", "rollback"])
async def test_active_reservation_remains_exclusive(tmp_path, strategy):
    async with database(tmp_path) as (manager, repository, _blocker):
        peer = RunManager(store=repository)
        async with manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as active:
            for contender in (manager, peer):
                with pytest.raises(ConflictError):
                    await contender.create_or_reject("thread", user_id="alice", multitask_strategy=strategy)
            assert (await repository.get(active.run_id, user_id="alice"))["status"] == "pending"
        assert await repository.list_inflight() == []


@pytest.mark.asyncio
async def test_recovery_and_concurrent_admission_share_the_thread_gate(tmp_path):
    async with database(tmp_path) as (manager, repository, blocker):
        finished = await fail_release(manager, blocker)
        blocker.rollback()
        results = await asyncio.gather(*(manager.create_or_reject("thread", user_id="alice") for _ in range(2)), return_exceptions=True)
        admitted = [result for result in results if not isinstance(result, BaseException)]
        assert len(admitted) == 1
        assert sum(isinstance(result, ConflictError) for result in results) == 1
        assert await repository.get(finished.run_id, user_id="alice") is None
        assert [row["run_id"] for row in await repository.list_inflight()] == [admitted[0].run_id]


@pytest.mark.asyncio
async def test_persistent_failure_is_bounded_and_does_not_schedule_retries(tmp_path, monkeypatch):
    async with database(tmp_path) as (manager, repository, blocker):
        original = repository.delete_thread_operation
        attempts = []

        async def release(run_id, *, user_id):
            attempts.append((run_id, user_id))
            await original(run_id, user_id=user_id)

        monkeypatch.setattr(repository, "delete_thread_operation", release)
        finished = await fail_release(manager, blocker)
        tasks_before = asyncio.all_tasks()
        assert len(attempts) == 2
        for attempt in range(2):
            with pytest.raises(ConflictError):
                await asyncio.wait_for(manager.create_or_reject("thread", user_id="alice"), timeout=1)
            assert len(attempts) == 4 + 2 * attempt
        assert asyncio.all_tasks() == tasks_before
        blocker.rollback()
        successor = await manager.create_or_reject("thread", user_id="alice")
        assert await repository.get(finished.run_id, user_id="alice") is None
        assert successor.status.value == "pending"
        assert all(owner == "alice" for _run_id, owner in attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial_release", "retry", "after_commit"])
async def test_cancelled_release_remains_owned_until_a_later_admission(tmp_path, monkeypatch, phase):
    async with database(tmp_path) as (manager, repository, blocker):
        if phase == "retry":
            finished = await fail_release(manager, blocker)
            blocker.rollback()
        entered = asyncio.Event()
        original = repository.delete_thread_operation
        calls = 0

        async def pause_once(run_id, *, user_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                if phase == "after_commit":
                    await original(run_id, user_id=user_id)
                entered.set()
                await asyncio.Event().wait()
            await original(run_id, user_id=user_id)

        monkeypatch.setattr(repository, "delete_thread_operation", pause_once)

        async def operation():
            nonlocal finished
            if phase == "retry":
                return await manager.create_or_reject("thread", user_id="alice")
            async with manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as finished:
                pass

        pending = asyncio.create_task(operation())
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
        finally:
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, ConflictError):
                pass
        successor = await manager.create_or_reject("thread", user_id="alice")
        assert await repository.get(finished.run_id, user_id="alice") is None
        assert [row["run_id"] for row in await repository.list_inflight()] == [successor.run_id]


@pytest.mark.asyncio
async def test_shutdown_is_bounded_with_failed_release_and_startup_can_reconcile(tmp_path):
    async with database(tmp_path) as (manager, repository, blocker):
        finished = await fail_release(manager, blocker)
        tasks_before = asyncio.all_tasks()
        await asyncio.wait_for(manager.shutdown(timeout=0.01), timeout=0.2)
        assert asyncio.all_tasks() == tasks_before
        assert (await repository.get(finished.run_id, user_id="alice"))["status"] == "pending"
        blocker.rollback()
        restarted = RunManager(store=repository)
        assert await restarted.reconcile_orphaned_inflight_runs(error="startup recovery") == []
        successor = await restarted.create_or_reject("thread", user_id="alice")
        assert successor.status.value == "pending"


@pytest.mark.asyncio
async def test_new_lease_starts_after_slow_release_retry(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from deerflow.runtime.runs import manager as manager_module

    async with database(tmp_path) as (manager, repository, blocker):
        # Use heartbeat admission semantics; the background timer is unnecessary
        # for testing the initial durable deadline after delayed recovery.
        manager._run_ownership_config = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=5)
        finished = await fail_release(manager, blocker)
        blocker.rollback()
        original = repository.delete_thread_operation
        clock_time = datetime.now(UTC)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock_time.astimezone(tz)

        async def delayed_release(run_id, *, user_id):
            nonlocal clock_time
            await asyncio.sleep(0)
            clock_time += timedelta(seconds=10)
            await original(run_id, user_id=user_id)

        monkeypatch.setattr(manager_module, "datetime", Clock)
        monkeypatch.setattr(repository, "delete_thread_operation", delayed_release)
        try:
            successor = await manager.create_or_reject("thread", user_id="alice")
            row = await repository.get(successor.run_id, user_id="alice")
            deadline = datetime.fromisoformat(row["lease_expires_at"])
            assert deadline >= clock_time + timedelta(seconds=5)
            assert successor.lease_expires_at == row["lease_expires_at"]
            assert await repository.get(finished.run_id, user_id="alice") is None
        finally:
            for handle in manager._lease_deadlines.values():
                handle.cancel()


@pytest.mark.asyncio
async def test_pending_release_conflict_remains_an_im_busy_response(tmp_path):
    import httpx
    from langgraph_sdk.errors import ConflictError as SDKConflictError

    from app.channels.manager import _is_thread_busy_error

    async with database(tmp_path) as (manager, _repository, blocker):
        await fail_release(manager, blocker)
        with pytest.raises(ConflictError) as failure:
            await manager.create_or_reject("thread", user_id="alice")
        detail = str(failure.value)
        response = httpx.Response(409, request=httpx.Request("POST", "http://gateway/threads/thread/runs"))
        assert _is_thread_busy_error(SDKConflictError(detail, response=response, body={"detail": detail}))
        blocker.rollback()


@pytest.mark.asyncio
async def test_completed_key_replays_while_later_reservation_awaits_release(tmp_path):
    async with database(tmp_path) as (manager, repository, blocker):
        original = await manager.create_or_reject("thread", user_id="alice", idempotency_key="completed-request")
        await manager.set_status(original.run_id, RunStatus.success)
        finished = await fail_release(manager, blocker)
        try:
            replay = await manager.create_or_reject("thread", user_id="alice", idempotency_key="completed-request")
            assert replay is original
            assert replay.status == RunStatus.success
            assert replay.idempotency_reused
            assert (await repository.get(finished.run_id, user_id="alice"))["status"] == "pending"
        finally:
            blocker.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["reject", "interrupt", "rollback"])
async def test_evicted_completed_key_replays_while_later_release_fails(monkeypatch, strategy):
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore()
    manager = RunManager(store=store)
    original = await manager.create_or_reject("thread", user_id="alice", idempotency_key="completed-request")
    await manager.set_status(original.run_id, RunStatus.success)
    await manager.cleanup(original.run_id, delay=0)

    async def unavailable_release(run_id, *, user_id):
        raise RuntimeError("release unavailable")

    monkeypatch.setattr(store, "delete_thread_operation", unavailable_release)
    async with manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as finished:
        pass
    replay = await manager.create_or_reject("thread", user_id="alice", idempotency_key="completed-request", multitask_strategy=strategy)
    assert replay.run_id == original.run_id
    assert replay.status == RunStatus.success
    assert replay.idempotency_reused and replay.store_only
    assert (await store.get(finished.run_id))["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["reject", "interrupt", "rollback"])
async def test_new_key_recovers_after_release_failure(tmp_path, strategy):
    async with database(tmp_path) as (manager, repository, blocker):
        finished = await fail_release(manager, blocker)
        blocker.rollback()
        successor = await manager.create_or_reject("thread", user_id="alice", idempotency_key="new-request", multitask_strategy=strategy)
        replay = await manager.create_or_reject("thread", user_id="alice", idempotency_key="new-request", multitask_strategy=strategy)
        assert replay.run_id == successor.run_id
        assert replay.idempotency_reused
        assert await repository.get(finished.run_id, user_id="alice") is None
        assert [row["run_id"] for row in await repository.list_inflight()] == [successor.run_id]


@pytest.mark.asyncio
async def test_uncertain_release_keeps_an_active_peer_reservation(tmp_path, monkeypatch):
    async with database(tmp_path) as (manager, repository, _blocker):
        original = repository.delete_thread_operation
        first = True

        async def lose_first_acknowledgement(run_id, *, user_id):
            nonlocal first
            await original(run_id, user_id=user_id)
            if first:
                first = False
                raise RuntimeError("release acknowledgement lost")

        monkeypatch.setattr(repository, "delete_thread_operation", lose_first_acknowledgement)
        async with manager.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as finished:
            pass
        assert await repository.get(finished.run_id, user_id="alice") is None
        peer = RunManager(store=repository)
        async with peer.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as active:
            with pytest.raises(ConflictError):
                await manager.create_or_reject("thread", user_id="alice")
            assert [row["run_id"] for row in await repository.list_inflight()] == [active.run_id]
        assert await repository.list_inflight() == []


@pytest.mark.asyncio
async def test_release_retry_after_peer_takeover_preserves_its_new_reservation(tmp_path):
    ownership = RunOwnershipConfig(heartbeat_enabled=True, grace_seconds=0)
    async with database(tmp_path, run_ownership_config=ownership) as (manager, repository, blocker):
        peer = RunManager(store=repository, run_ownership_config=ownership)
        finished = await fail_release(manager, blocker)
        blocker.rollback()

        assert await peer.reconcile_orphaned_inflight_runs(error="peer takeover") == []
        pending = await repository.get(finished.run_id, user_id="alice")
        assert pending["status"] == "pending"
        assert pending["lease_expires_at"] is not None

        # Expire the durable lease without waiting for the heartbeat interval.
        blocker.execute("UPDATE runs SET lease_expires_at = datetime('now', '-1 minute') WHERE run_id = ?", (finished.run_id,))
        blocker.commit()
        assert await peer.reconcile_orphaned_inflight_runs(error="peer takeover") == []
        reclaimed = await repository.get(finished.run_id, user_id="alice")
        assert reclaimed["status"] == "error"
        assert reclaimed["error"] == "peer takeover"

        async with peer.reserve_thread_operation("thread", kind=ThreadOperationKind.checkpoint_write, user_id="alice") as active:
            with pytest.raises(ConflictError):
                await manager.create_or_reject("thread", user_id="alice")
            assert await repository.get(finished.run_id, user_id="alice") is None
            assert [row["run_id"] for row in await repository.list_inflight()] == [active.run_id]
