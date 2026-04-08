"""Tests for deerflow.runtime.scheduler.store."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError


@pytest.mark.anyio
async def test_create_job_persists_next_fire_at():
    from deerflow.runtime.scheduler import CronJobCreate, create_cron_job, get_cron_job

    store = InMemoryStore()
    now = datetime(2026, 4, 8, 10, 5, tzinfo=UTC).timestamp()

    record = await create_cron_job(
        store,
        CronJobCreate(
            thread_id="thread-1",
            cron="*/15 * * * *",
            timezone="UTC",
            input={"messages": [{"role": "user", "content": "hi"}]},
        ),
        job_id="job-1",
        now=now,
    )

    persisted = await get_cron_job(store, "job-1")

    assert persisted is not None
    assert persisted.job_id == "job-1"
    assert persisted.next_fire_at == datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp()
    assert persisted.model_dump(mode="python") == record.model_dump(mode="python")


@pytest.mark.anyio
async def test_update_job_recomputes_next_fire_at():
    from deerflow.runtime.scheduler import CronJobCreate, CronJobUpdate, create_cron_job, update_cron_job

    store = InMemoryStore()
    created_at = datetime(2026, 4, 8, 8, 0, tzinfo=UTC).timestamp()
    updated_at = datetime(2026, 4, 8, 8, 5, tzinfo=UTC).timestamp()

    created = await create_cron_job(
        store,
        CronJobCreate(thread_id="thread-1", cron="0 9 * * *", timezone="UTC"),
        job_id="job-1",
        now=created_at,
    )
    updated = await update_cron_job(
        store,
        "job-1",
        CronJobUpdate(cron="0 10 * * *"),
        now=updated_at,
    )

    assert created.next_fire_at == datetime(2026, 4, 8, 9, 0, tzinfo=UTC).timestamp()
    assert updated.next_fire_at == datetime(2026, 4, 8, 10, 0, tzinfo=UTC).timestamp()
    assert updated.updated_at == updated_at


@pytest.mark.anyio
async def test_due_jobs_ignore_disabled_records():
    from deerflow.runtime.scheduler import CronJobCreate, create_cron_job, list_due_cron_jobs

    store = InMemoryStore()
    now = datetime(2026, 4, 8, 10, 0, tzinfo=UTC).timestamp()
    due_at = datetime(2026, 4, 8, 10, 30, tzinfo=UTC).timestamp()

    await create_cron_job(
        store,
        CronJobCreate(thread_id="thread-1", cron="*/30 * * * *", timezone="UTC", enabled=True),
        job_id="job-enabled",
        now=now,
    )
    await create_cron_job(
        store,
        CronJobCreate(thread_id="thread-1", cron="*/30 * * * *", timezone="UTC", enabled=False),
        job_id="job-disabled",
        now=now,
    )

    jobs = await list_due_cron_jobs(store, now=due_at, limit=10)

    assert [job.job_id for job in jobs] == ["job-enabled"]


@pytest.mark.anyio
async def test_mark_job_fired_advances_next_fire_at_and_last_run_id():
    from deerflow.runtime.scheduler import CronJobCreate, create_cron_job, mark_cron_job_fired

    store = InMemoryStore()
    created_at = datetime(2026, 4, 8, 10, 0, tzinfo=UTC).timestamp()
    fired_at = datetime(2026, 4, 8, 10, 30, tzinfo=UTC).timestamp()

    await create_cron_job(
        store,
        CronJobCreate(thread_id="thread-1", cron="*/30 * * * *", timezone="UTC"),
        job_id="job-1",
        now=created_at,
    )
    updated = await mark_cron_job_fired(store, "job-1", fired_at=fired_at, run_id="run-123")

    assert updated.last_fire_at == fired_at
    assert updated.last_run_id == "run-123"
    assert updated.next_fire_at == datetime(2026, 4, 8, 11, 0, tzinfo=UTC).timestamp()


def test_invalid_cron_expression_is_rejected():
    from deerflow.runtime.scheduler import CronJobCreate

    with pytest.raises(ValidationError):
        CronJobCreate(thread_id="thread-1", cron="not a cron", timezone="UTC")
