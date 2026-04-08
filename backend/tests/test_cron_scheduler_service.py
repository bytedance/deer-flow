"""Tests for deerflow.runtime.scheduler.service."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp()


@pytest.mark.anyio
async def test_manual_trigger_creates_run():
    from deerflow.runtime.scheduler import CronJobCreate, CronSchedulerService, create_cron_job

    store = InMemoryStore()
    launched: list[tuple[str, object]] = []

    async def fake_run_launcher(thread_id, payload):
        launched.append((thread_id, payload))
        return SimpleNamespace(run_id="run-manual")

    await create_cron_job(
        store,
        CronJobCreate(
            thread_id="thread-1",
            cron="*/30 * * * *",
            timezone="UTC",
            input={"messages": [{"role": "user", "content": "manual"}]},
        ),
        job_id="job-1",
        now=_ts(2026, 4, 8, 10, 0),
    )
    service = CronSchedulerService(store, fake_run_launcher)

    record = await service.trigger_job("job-1")

    assert record.run_id == "run-manual"
    assert len(launched) == 1
    assert launched[0][0] == "thread-1"
    assert launched[0][1].input["messages"][0]["content"] == "manual"


@pytest.mark.anyio
async def test_disabled_job_is_not_dispatched():
    from deerflow.runtime.scheduler import CronJobCreate, CronSchedulerService, create_cron_job

    store = InMemoryStore()
    launched: list[tuple[str, object]] = []

    async def fake_run_launcher(thread_id, payload):
        launched.append((thread_id, payload))
        return SimpleNamespace(run_id="run-disabled")

    await create_cron_job(
        store,
        CronJobCreate(
            thread_id="thread-1",
            cron="*/30 * * * *",
            timezone="UTC",
            enabled=False,
        ),
        job_id="job-1",
        now=_ts(2026, 4, 8, 10, 0),
    )
    service = CronSchedulerService(store, fake_run_launcher)

    records = await service.dispatch_due_jobs(now=_ts(2026, 4, 8, 11, 0))

    assert records == []
    assert launched == []


@pytest.mark.anyio
async def test_scheduler_dispatch_respects_enqueue_strategy():
    from deerflow.runtime.scheduler import CronJobCreate, CronSchedulerService, create_cron_job, get_cron_job

    store = InMemoryStore()
    launched: list[tuple[str, object]] = []

    async def fake_run_launcher(thread_id, payload):
        launched.append((thread_id, payload))
        return SimpleNamespace(run_id="run-enqueue")

    await create_cron_job(
        store,
        CronJobCreate(
            thread_id="thread-1",
            cron="*/30 * * * *",
            timezone="UTC",
            multitask_strategy="enqueue",
        ),
        job_id="job-1",
        now=_ts(2026, 4, 8, 10, 0),
    )
    service = CronSchedulerService(store, fake_run_launcher)

    records = await service.dispatch_due_jobs(now=_ts(2026, 4, 8, 10, 30))
    stored = await get_cron_job(store, "job-1")

    assert len(records) == 1
    assert len(launched) == 1
    assert launched[0][1].multitask_strategy == "enqueue"
    assert stored is not None
    assert stored.last_run_id == "run-enqueue"
    assert stored.next_fire_at == _ts(2026, 4, 8, 11, 0)


@pytest.mark.anyio
async def test_scheduler_run_loop_can_start_and_stop():
    from deerflow.runtime.scheduler import CronSchedulerService

    store = InMemoryStore()
    wake_count = 0

    async def fake_run_launcher(thread_id, payload):
        return SimpleNamespace(run_id="run-loop")

    service = CronSchedulerService(store, fake_run_launcher, poll_interval=0.01)
    original_dispatch = service.dispatch_due_jobs

    async def counted_dispatch(*, now=None, limit=100):
        nonlocal wake_count
        wake_count += 1
        return await original_dispatch(now=now, limit=limit)

    service.dispatch_due_jobs = counted_dispatch  # type: ignore[method-assign]

    service.start()
    await pytest.importorskip("asyncio").sleep(0.03)
    await service.stop()

    assert wake_count >= 1
    assert service.task is None
