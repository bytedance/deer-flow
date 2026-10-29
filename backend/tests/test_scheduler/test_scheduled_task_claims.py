from datetime import UTC, datetime, timedelta

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.mark.asyncio
async def test_claim_due_tasks_claims_only_due_rows(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    repo = ScheduledTaskRepository(sf)

    due = datetime.now(UTC) - timedelta(minutes=1)
    future = datetime.now(UTC) + timedelta(hours=1)

    await repo.create(
        task_id="due-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Due",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=due,
    )
    await repo.create(
        task_id="future-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Future",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=future,
    )

    claimed = await repo.claim_due_tasks(
        now=datetime.now(UTC),
        lease_owner="worker-1",
        lease_seconds=120,
        limit=10,
    )
    assert [task["id"] for task in claimed] == ["due-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_claim_reclaims_task_stuck_in_running_with_expired_lease(tmp_path):
    """A task whose claiming process died mid-dispatch must stay reclaimable.

    Regression for the lease dead-end bug: claim flips status to ``running``,
    and the old claim query only selected ``status == 'enabled'``, so a crash
    between claim and dispatch left the task permanently un-triggerable.
    """
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    repo = ScheduledTaskRepository(sf)

    now = datetime.now(UTC)
    due = now - timedelta(minutes=5)

    await repo.create(
        task_id="stuck-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Stuck",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=due,
    )

    first_claim = await repo.claim_due_tasks(
        now=now,
        lease_owner="dead-worker",
        lease_seconds=60,
        limit=10,
    )
    assert first_claim[0]["id"] == "stuck-1"
    assert first_claim[0]["status"] == "running"

    # Simulate the claiming process dying: lease expires, status stays "running".
    expired_now = now + timedelta(seconds=120)
    reclaimed = await repo.claim_due_tasks(
        now=expired_now,
        lease_owner="new-worker",
        lease_seconds=60,
        limit=10,
    )
    assert [task["id"] for task in reclaimed] == ["stuck-1"]
    assert reclaimed[0]["lease_owner"] == "new-worker"

    await close_engine()


@pytest.mark.asyncio
async def test_claim_skips_task_with_active_lease(tmp_path):
    """A task whose lease has not expired must not be reclaimed."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    repo = ScheduledTaskRepository(sf)

    now = datetime.now(UTC)
    due = now - timedelta(minutes=5)

    await repo.create(
        task_id="active-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Active",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=due,
    )

    await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=300,
        limit=10,
    )

    # Lease still valid — second claim within the same process must not re-grab it.
    reclaimed = await repo.claim_due_tasks(
        now=now + timedelta(seconds=10),
        lease_owner="worker-2",
        lease_seconds=300,
        limit=10,
    )
    assert reclaimed == []

    await close_engine()
