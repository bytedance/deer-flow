"""Verify that enabling scheduled delegation is opt-in after a database upgrade."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

PREVIOUS = "0055_thread_shares"
REVISION = "0056_scheduled_task_subagents"


@pytest.mark.asyncio
async def test_scheduled_subagent_migration_preserves_existing_tasks(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, config, PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO scheduled_tasks (id,user_id,context_mode,title,prompt,schedule_type,schedule_spec,timezone,status,overlap_policy,run_count,last_occurrence_seq,created_at,updated_at) "
                    "VALUES ('existing','owner','fresh_thread_per_run','Report','Write report','cron','{}','UTC','paused','enqueue',4,4,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )

        await asyncio.to_thread(command.upgrade, config, REVISION)
        repo = ScheduledTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
        existing = await repo.get("existing", user_id="owner")
        assert existing["subagent_enabled"] is False
        assert existing["run_count"] == 4

        await repo.update("existing", user_id="owner", updates={"subagent_enabled": True})
        await asyncio.to_thread(command.stamp, config, PREVIOUS)
        await asyncio.to_thread(command.upgrade, config, REVISION)
        assert (await repo.get("existing", user_id="owner"))["subagent_enabled"] is True

        await asyncio.to_thread(command.downgrade, config, PREVIOUS)
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: inspect(sync).get_columns("scheduled_tasks"))
            assert "subagent_enabled" not in {column["name"] for column in columns}
            assert (await conn.execute(text("SELECT title FROM scheduled_tasks WHERE id='existing'"))).scalar_one() == "Report"
    finally:
        await engine.dispose()
