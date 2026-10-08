"""Native C admission keeps one durable run across Gateway instances."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.runtime import DisconnectMode, RunManager
from deerflow.runtime.runs.manager import RunStartOutcome, RunStartupError


@pytest.mark.asyncio
async def test_pending_handoff_adopts_same_run_and_fences_stale_owner(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        central = RunManager(store, worker_id="central", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        worker = RunManager(store, worker_id="worker", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        record = await central.create_or_reject("thread", None, on_disconnect=DisconnectMode.continue_, user_id="owner", kwargs={"input": {"messages": []}})
        await central.handoff_pending(record.run_id, owner_worker_id="dispatch:job")
        adopted = await worker.adopt_pending(record.run_id, thread_id="thread", user_id="owner", expected_owner_worker_id="dispatch:job")
        assert adopted.run_id == record.run_id
        assert not adopted.store_only
        assert adopted.lease_expires_at is not None
        assert adopted.kwargs == record.kwargs
        assert not await store.start_run(record.run_id, owner_worker_id="central")
        assert await worker.try_start(record.run_id) == RunStartOutcome.started
        with pytest.raises(RunStartupError):
            await RunManager(store, worker_id="other", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True)).adopt_pending(record.run_id, thread_id="thread", user_id="owner", expected_owner_worker_id="dispatch:job")
        assert (await central.get(record.run_id, user_id="owner")).status.value == "running"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_admission_host_hands_off_without_attaching_local_worker(tmp_path):
    from types import SimpleNamespace

    from app.gateway.native_admission import attach_native_admission

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'host.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        manager = RunManager(store, worker_id="central", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        record = await manager.create_or_reject("thread", user_id="owner")
        executed = []

        async def local_worker(run):
            executed.append(run.run_id)

        class Host:
            async def admit(self, run):
                await manager.handoff_pending(run.run_id, owner_worker_id="dispatch:job")
                return True

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(native_run_admission_host=Host())))
        await attach_native_admission(request, manager, record, local_worker)
        assert record.task is None
        assert executed == []
        assert (await store.get(record.run_id, user_id="owner"))["status"] == "pending"
        await store.request_cancel(record.run_id, action="interrupt")
        with pytest.raises(RunStartupError):
            await RunManager(store, worker_id="worker", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True)).adopt_pending(record.run_id, thread_id="thread", user_id="owner", expected_owner_worker_id="dispatch:job")
        assert not await store.start_run(record.run_id, owner_worker_id="dispatch:job")
        failed = await manager.create_or_reject("other-thread", user_id="owner")

        class BrokenHost:
            async def admit(self, run):
                raise RuntimeError("host unavailable")

        request.app.state.native_run_admission_host = BrokenHost()
        with pytest.raises(RuntimeError, match="host unavailable"):
            await attach_native_admission(request, manager, failed, local_worker)
        assert (await store.get(failed.run_id, user_id="owner"))["status"] == "error"
    finally:
        await engine.dispose()
