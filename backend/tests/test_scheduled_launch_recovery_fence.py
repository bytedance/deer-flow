"""Recovery must revalidate launch leases after acquiring the parent lock."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from support.postgres import asyncpg_test_url

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repositories(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real PostgreSQL launch recovery)")
        schema = f"launch_recovery_{uuid.uuid4().hex}"
        config = DatabaseConfig(backend="postgres", postgres_url=asyncpg_test_url(uri), postgres_schema=schema)
    else:
        config = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    await init_engine_from_config(config)
    try:
        factory = get_session_factory()
        assert factory is not None
        yield ScheduledTaskRepository(factory), ScheduledTaskRunRepository(factory), ScheduledTaskRunRepository(factory)
    finally:
        if schema is not None:
            async with get_engine().begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()


async def seed_occurrence(tasks, runs, *, now, suffix="1"):
    await tasks.create(
        task_id=f"task-{suffix}",
        user_id="user-1",
        thread_id=f"thread-{suffix}",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Recovery fence",
        prompt="Work",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    return await runs.create(
        run_record_id=f"occurrence-{suffix}",
        task_id=f"task-{suffix}",
        thread_id=f"thread-{suffix}",
        scheduled_for=now,
        trigger="manual",
        status="queued",
    )


@pytest.mark.parametrize("new_owner", ["same-worker", "peer-worker"])
async def test_expired_scan_cannot_requeue_a_fresh_claim(repositories, monkeypatch, new_owner):
    tasks, recovery, launcher = repositories
    now = datetime.now(UTC)
    await seed_occurrence(tasks, launcher, now=now)
    assert await launcher.claim_queued_run("occurrence-1", lease_owner="same-worker", now=now, lease_seconds=5, global_max_concurrent_runs=1)
    scan_time = now + timedelta(seconds=6)
    selected = asyncio.Event()
    release = asyncio.Event()
    lock_task = recovery._lock_task

    async def pause_before_parent_lock(session, task_id):
        # The scan has selected the expired row, but owns no write lock yet.
        selected.set()
        await release.wait()
        return await lock_task(session, task_id)

    monkeypatch.setattr(recovery, "_lock_task", pause_before_parent_lock)
    recovering = asyncio.create_task(recovery.recover_expired_launch_claims(error="expired", now=scan_time))
    try:
        await asyncio.wait_for(selected.wait(), timeout=5)
        # The original launch conflicts with an interactive run and requeues.
        # A later manual trigger claims the same occurrence before the old
        # recovery scan acquires its parent lock. No fabricated database rows.
        assert await launcher.requeue_claimed_run("occurrence-1", lease_owner="same-worker", error="thread busy")
        assert await launcher.claim_queued_run("occurrence-1", lease_owner=new_owner, now=scan_time, lease_seconds=120, global_max_concurrent_runs=1)
        before = (await launcher.list_by_task("task-1"))[0]
        release.set()
        assert await asyncio.wait_for(recovering, timeout=5) == 0
        assert (await launcher.list_by_task("task-1"))[0] == before
        # The fresh launch must keep its execution slot, not merely its label.
        await seed_occurrence(tasks, launcher, now=now, suffix="2")
        assert await launcher.claim_queued_run("occurrence-2", lease_owner="third-worker", now=scan_time, lease_seconds=120, global_max_concurrent_runs=1) is None
    finally:
        release.set()
        await asyncio.gather(recovering, return_exceptions=True)


async def test_late_launch_bookkeeping_cannot_release_a_reclaimed_claim(repositories):
    tasks, recovery, launcher = repositories
    now = datetime.now(UTC)
    await seed_occurrence(tasks, launcher, now=now)
    first = await launcher.claim_queued_run(
        "occurrence-1",
        lease_owner="same-worker",
        now=now,
        lease_seconds=5,
        global_max_concurrent_runs=1,
    )
    assert first is not None
    assert first["attempt_count"] == 1

    assert await recovery.recover_expired_launch_claims(error="expired", now=now + timedelta(seconds=6)) == 1
    fresh = await launcher.claim_queued_run(
        "occurrence-1",
        lease_owner="same-worker",
        now=now + timedelta(seconds=6),
        lease_seconds=120,
        global_max_concurrent_runs=1,
    )
    assert fresh is not None
    assert fresh["attempt_count"] == 2
    before = (await launcher.list_by_task("task-1"))[0]

    # The original attempt's late bookkeeping carries attempt 1. Neither the
    # busy-thread requeue nor the launch-failure path may touch the fresh
    # attempt-2 claim, even though both use the same process lease owner.
    assert (
        await launcher.requeue_claimed_run(
            "occurrence-1",
            lease_owner="same-worker",
            error="thread busy",
            expected_attempt_count=first["attempt_count"],
        )
        is False
    )
    assert (
        await launcher.fail_launching_run(
            "occurrence-1",
            task_id="task-1",
            lease_owner="same-worker",
            error="launch failed",
            now=now + timedelta(seconds=7),
            expected_attempt_count=first["attempt_count"],
        )
        is False
    )
    assert (await launcher.list_by_task("task-1"))[0] == before

    # The fresh claim still holds the only global execution slot.
    await seed_occurrence(tasks, launcher, now=now, suffix="2")
    assert (
        await launcher.claim_queued_run(
            "occurrence-2",
            lease_owner="third-worker",
            now=now + timedelta(seconds=7),
            lease_seconds=120,
            global_max_concurrent_runs=1,
        )
        is None
    )

    # The current generation can still release its own claim.
    assert await launcher.requeue_claimed_run(
        "occurrence-1",
        lease_owner="same-worker",
        error="thread busy",
        expected_attempt_count=fresh["attempt_count"],
    )
    assert (
        await launcher.claim_queued_run(
            "occurrence-2",
            lease_owner="third-worker",
            now=now + timedelta(seconds=8),
            lease_seconds=120,
            global_max_concurrent_runs=1,
        )
        is not None
    )


@pytest.mark.parametrize("lease_age", [5, 6])
async def test_recovery_keeps_boundary_lease_and_requeues_expired_claim(repositories, lease_age):
    tasks, recovery, launcher = repositories
    now = datetime.now(UTC)
    await seed_occurrence(tasks, launcher, now=now)
    assert await launcher.claim_queued_run("occurrence-1", lease_owner="worker", now=now, lease_seconds=5, global_max_concurrent_runs=1)
    before = (await launcher.list_by_task("task-1"))[0]
    recovered = await recovery.recover_expired_launch_claims(error="expired", now=now + timedelta(seconds=lease_age))
    after = (await launcher.list_by_task("task-1"))[0]
    if lease_age == 5:
        assert recovered == 0
        assert after == before
    else:
        assert recovered == 1
        assert after["status"] == "queued"
        assert after["lease_owner"] is None
        assert after["lease_expires_at"] is None
        assert after["attempt_count"] == 1


async def test_recovery_requeues_legacy_launch_without_a_lease(repositories):
    tasks, recovery, launcher = repositories
    now = datetime.now(UTC)
    await seed_occurrence(tasks, launcher, now=now)
    # The unguarded repository API also supports historical launching rows
    # whose lease fields were never populated. They must remain recoverable.
    assert await launcher.update_status("occurrence-1", status="launching")
    assert (await launcher.list_by_task("task-1"))[0]["lease_expires_at"] is None

    assert await recovery.recover_expired_launch_claims(error="expired", now=now) == 1

    after = (await launcher.list_by_task("task-1"))[0]
    assert after["status"] == "queued"
    assert after["lease_owner"] is None
    assert after["lease_expires_at"] is None
    assert after["attempt_count"] == 0
