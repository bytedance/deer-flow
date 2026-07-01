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
