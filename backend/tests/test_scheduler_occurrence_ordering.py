"""Late launches must preserve the latest occurrence's parent projection.

The scheduler and repositories are real. Only the external run lifecycle and
barriers between its launch return and scheduler bookkeeping are controlled.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["sqlite", "postgres-single", "postgres-multi"])
async def occurrence_databases(request, tmp_path):
    backend = request.param
    postgres_uri = os.environ.get("TEST_POSTGRES_URI")
    if backend != "sqlite" and not postgres_uri:
        pytest.skip("TEST_POSTGRES_URI is not set")
    schema = "scheduler_order_" + uuid.uuid4().hex
    admin = None
    engines = []
    try:
        if backend != "sqlite":
            admin = create_async_engine(postgres_uri)
            async with admin.begin() as connection:
                await connection.execute(CreateSchema(schema))
        for _ in range(3):
            if backend == "sqlite":
                engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")

                @event.listens_for(engine.sync_engine, "connect")
                def configure_sqlite(connection, _record):
                    cursor = connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=10000")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
            else:
                engine = create_async_engine(postgres_uri, connect_args={"server_settings": {"search_path": schema}})
            engines.append(engine)
        async with engines[0].begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[ScheduledTaskRow.__table__, ScheduledTaskRunRow.__table__, RunRow.__table__]))
        yield [async_sessionmaker(engine, expire_on_commit=False) for engine in engines], backend == "postgres-multi"
    finally:
        for engine in engines:
            await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            await admin.dispose()


class _RevivalBarrierRepository(ScheduledTaskRunRepository):
    def __init__(self, factory, durable, revived, resume):
        super().__init__(factory, run_repository=durable)
        self.revived = revived
        self.resume = resume

    async def reconcile_launched_run(self, *args, **kwargs):
        result = await super().reconcile_launched_run(*args, **kwargs)
        assert result is True
        self.revived.set()
        await self.resume.wait()
        return result


def _service(tasks, occurrences, launcher, multi):
    return ScheduledTaskService(
        task_repo=tasks,
        task_run_repo=occurrences,
        launch_run=launcher,
        poll_interval_seconds=3600,
        lease_seconds=5,
        max_concurrent_runs=3,
        queue_timeout_seconds=10,
        multi_instance=multi,
        run_lease_grace_seconds=0,
    )


async def _parent_projection(factory, task_id):
    async with factory() as session:
        parent = await session.get(ScheduledTaskRow, task_id)
        return {key: getattr(parent, key) for key in ("status", "last_error", "last_run_id", "last_thread_id", "last_run_at", "next_run_at", "lease_owner", "lease_expires_at", "run_count")}


def _completion(run_id, launch_args, status, error=None):
    return RunRecord(
        run_id=run_id,
        thread_id=launch_args["thread_id"],
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        user_id="user-order",
        metadata=launch_args["metadata"],
        error=error,
    )


@pytest.mark.parametrize("interrupt_before_parent", [True, False], ids=["restart-after-revival", "late-completion-callback"])
@pytest.mark.parametrize("newer_occurrence", [True, False], ids=["newer-failed-occurrence", "single-occurrence-control"])
async def test_late_launch_preserves_newer_result_and_counts_once(occurrence_databases, interrupt_before_parent, newer_occurrence):
    factories, multi = occurrence_databases
    durable_a, durable_b, durable_recovery = [RunRepository(factory) for factory in factories]
    tasks_a, tasks_b, tasks_recovery = [ScheduledTaskRepository(factory, run_repository=durable) for factory, durable in zip(factories, (durable_a, durable_b, durable_recovery), strict=True)]
    entered, release, revived, resume = [asyncio.Event() for _ in range(4)]
    occurrences_a = _RevivalBarrierRepository(factories[0], durable_a, revived, resume)
    occurrences_b = ScheduledTaskRunRepository(factories[1], run_repository=durable_b)
    occurrences_recovery = ScheduledTaskRunRepository(factories[2], run_repository=durable_recovery)
    now = datetime.now(UTC)
    task_id, run_a, run_b = "task-order", "run-order-a", "run-order-b"
    launches = {}

    async def launch_a(**kwargs):
        launches["a"] = kwargs
        entered.set()
        await release.wait()
        # Model a real run becoming terminal before its slow launch call
        # returns. Scheduled occurrence states are only changed by the service.
        await durable_a.put(run_a, thread_id=kwargs["thread_id"], user_id="user-order", status="running", metadata=kwargs["metadata"])
        await durable_a.update_status(run_a, "success")
        return {"run_id": run_a, "thread_id": kwargs["thread_id"]}

    async def launch_b(**kwargs):
        launches["b"] = kwargs
        await durable_b.put(run_b, thread_id=kwargs["thread_id"], user_id="user-order", status="running", metadata=kwargs["metadata"])
        return {"run_id": run_b, "thread_id": kwargs["thread_id"]}

    async def singleton_launcher(**kwargs):
        if "a" not in launches:
            return await launch_a(**kwargs)
        assert "b" not in launches
        return await launch_b(**kwargs)

    async def unexpected_launch(**_kwargs):
        pytest.fail("recovery must not launch another occurrence")

    service_a = _service(tasks_a, occurrences_a, launch_a if multi else singleton_launcher, multi)
    service_b = _service(tasks_b, occurrences_b, launch_b, multi) if multi else service_a
    peer = _service(tasks_recovery, occurrences_recovery, unexpected_launch, multi) if multi else service_a
    scheduled_at = now - timedelta(seconds=1) if multi else now + timedelta(days=1)
    await tasks_a.create(
        task_id=task_id,
        user_id="user-order",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="occurrence order",
        prompt="test",
        schedule_type="once",
        schedule_spec={"run_at": scheduled_at.isoformat()},
        timezone="UTC",
        next_run_at=scheduled_at,
    )
    initial_task = await tasks_a.get(task_id, user_id="user-order")
    dispatch = asyncio.create_task(service_a.run_once(now=now) if multi else service_a.dispatch_task(initial_task, now=now, trigger="manual"))
    restarted = _service(tasks_recovery, occurrences_recovery, unexpected_launch, multi)

    async def parked_poll_loop():
        await restarted._stop.wait()

    restarted._run_loop = parked_poll_loop
    try:
        await asyncio.wait_for(entered.wait(), 10)
        assert (await occurrences_b.list_by_task(task_id))[0]["status"] == "launching"
        # Explicit scheduler time expires the launch claim and then the queue;
        # no sleeps or direct terminal occurrence writes are needed.
        await peer.run_once(now=now + timedelta(seconds=30))
        expired = (await occurrences_b.list_by_task(task_id))[0]
        assert expired["status"] == "failed"
        assert expired["run_id"] is None

        if newer_occurrence:
            result = await service_b.dispatch_task(await tasks_b.get(task_id, user_id="user-order"), now=now + timedelta(seconds=31), trigger="manual")
            assert result["outcome"] == "launched"
            await durable_b.update_status(run_b, "error", error="newer run failed")
            await service_b.handle_run_completion(_completion(run_b, launches["b"], RunStatus.error, "newer run failed"))
            expected = await _parent_projection(factories[1], task_id)
            assert expected["status"] == "failed"
            assert expected["last_run_id"] == run_b
            assert expected["run_count"] == 1
            expected["run_count"] = 2

        release.set()
        await asyncio.wait_for(revived.wait(), 10)
        if interrupt_before_parent:
            # The revival transaction committed, but dispatch has not yet
            # performed the parent launch accounting.
            dispatch.cancel()
            with suppress(asyncio.CancelledError):
                await dispatch
        else:
            resume.set()
            await asyncio.wait_for(dispatch, 10)
            await service_a.handle_run_completion(_completion(run_a, launches["a"], RunStatus.success))
            if newer_occurrence:
                assert await _parent_projection(factories[1], task_id) == expected

        await restarted.start()
        await restarted.stop()
        after = await _parent_projection(factories[1], task_id)
        if newer_occurrence:
            assert after == expected
        else:
            assert after["status"] == "completed"
            assert after["last_run_id"] == run_a
            assert after["run_count"] == 1
        async with factories[1]() as session:
            statuses = dict((await session.execute(select(ScheduledTaskRunRow.run_id, ScheduledTaskRunRow.status).where(ScheduledTaskRunRow.task_id == task_id))).all())
        assert statuses == ({run_a: "success", run_b: "failed"} if newer_occurrence else {run_a: "success"})

        # Repeated completion and recovery must neither re-project old state
        # nor account either successful launch a second time.
        await service_a.handle_run_completion(_completion(run_a, launches["a"], RunStatus.success))
        assert await _parent_projection(factories[1], task_id) == after
        if newer_occurrence:
            await service_b.handle_run_completion(_completion(run_b, launches["b"], RunStatus.error, "newer run failed"))
            assert await _parent_projection(factories[1], task_id) == after
        await restarted.start()
        await restarted.stop()
        assert await _parent_projection(factories[1], task_id) == after
    finally:
        release.set()
        resume.set()
        if not dispatch.done():
            dispatch.cancel()
        with suppress(asyncio.CancelledError):
            await dispatch
        await restarted.stop()


@pytest.mark.parametrize("interrupt_before_return", [True, False], ids=["crash-before-launch-return", "normal-launch-return"])
async def test_completion_before_launch_return_accounts_once(occurrence_databases, interrupt_before_return):
    factories, multi = occurrence_databases
    durable = RunRepository(factories[0])
    tasks = ScheduledTaskRepository(factories[0], run_repository=durable)
    occurrences = ScheduledTaskRunRepository(factories[0], run_repository=durable)
    completed, release = asyncio.Event(), asyncio.Event()
    run_id, task_id = "run-fast-completion", "task-fast-completion"
    now = datetime.now(UTC)
    record = None

    async def launcher(**kwargs):
        nonlocal record
        await durable.put(run_id, thread_id=kwargs["thread_id"], user_id="user-order", status="running", metadata=kwargs["metadata"])
        await durable.update_status(run_id, "success")
        record = _completion(run_id, kwargs, RunStatus.success)
        await service.handle_run_completion(record)
        completed.set()
        await release.wait()
        return {"run_id": run_id, "thread_id": kwargs["thread_id"]}

    async def unexpected_launch(**_kwargs):
        pytest.fail("completed occurrence must not launch again")

    service = _service(tasks, occurrences, launcher, multi)
    await tasks.create(
        task_id=task_id,
        user_id="user-order",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="fast completion",
        prompt="test",
        schedule_type="once",
        schedule_spec={"run_at": now.isoformat()},
        timezone="UTC",
        next_run_at=now,
    )
    dispatch = asyncio.create_task(service.dispatch_task(await tasks.get(task_id, user_id="user-order"), now=now, trigger="manual"))
    recovery_durable = RunRepository(factories[1])
    restarted = _service(
        ScheduledTaskRepository(factories[1], run_repository=recovery_durable),
        ScheduledTaskRunRepository(factories[1], run_repository=recovery_durable),
        unexpected_launch,
        multi,
    )

    async def parked_poll_loop():
        await restarted._stop.wait()

    restarted._run_loop = parked_poll_loop
    try:
        await asyncio.wait_for(completed.wait(), 10)
        before_return = await _parent_projection(factories[1], task_id)
        assert before_return["status"] == "completed"
        assert before_return["run_count"] == 1
        assert before_return["last_run_id"] == run_id
        assert before_return["last_thread_id"] == record.thread_id
        if interrupt_before_return:
            dispatch.cancel()
            with suppress(asyncio.CancelledError):
                await dispatch
        else:
            release.set()
            await asyncio.wait_for(dispatch, 10)

        await restarted.start()
        await restarted.stop()
        after = await _parent_projection(factories[1], task_id)
        assert after["status"] == "completed"
        assert after["last_run_id"] == run_id
        assert after["run_count"] == 1
        assert (await occurrences.list_by_task(task_id))[0]["status"] == "success"
        await service.handle_run_completion(record)
        await restarted.start()
        await restarted.stop()
        assert await _parent_projection(factories[1], task_id) == after
    finally:
        release.set()
        if not dispatch.done():
            dispatch.cancel()
        with suppress(asyncio.CancelledError):
            await dispatch
        await restarted.stop()
