from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import bootstrap_schema

pytestmark = pytest.mark.asyncio


async def test_migration_interrupts_legacy_queue_and_adds_claim_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "deer.db"
    sync = sa.create_engine(f"sqlite:///{db_path}")
    try:
        Base.metadata.create_all(sync)
        with sync.begin() as conn:
            conn.execute(sa.text("DROP INDEX uq_scheduled_task_run_active"))
            conn.execute(sa.text("ALTER TABLE scheduled_task_runs DROP COLUMN attempt_count"))
            conn.execute(sa.text("ALTER TABLE scheduled_task_runs DROP COLUMN lease_expires_at"))
            conn.execute(sa.text("ALTER TABLE scheduled_task_runs DROP COLUMN lease_owner"))
            conn.execute(sa.text("CREATE UNIQUE INDEX uq_scheduled_task_run_active ON scheduled_task_runs (task_id) WHERE status IN ('queued', 'running')"))
            conn.execute(
                sa.text(
                    "INSERT INTO scheduled_tasks "
                    "(id, user_id, thread_id, context_mode, assistant_id, title, prompt, "
                    "schedule_type, schedule_spec, timezone, status, overlap_policy, run_count, created_at, updated_at) "
                    "VALUES ('task-legacy', 'user-1', 'thread-1', 'reuse_thread', 'lead_agent', "
                    "'Legacy', 'Prompt', 'cron', '{\"cron\":\"0 9 * * *\"}', 'UTC', "
                    "'enabled', 'skip', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO scheduled_task_runs (id, task_id, thread_id, scheduled_for, trigger, status, created_at) VALUES ('run-legacy-queued', 'task-legacy', 'thread-1', CURRENT_TIMESTAMP, 'scheduled', 'queued', CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0013_mcp_task_notifications')"))
    finally:
        sync.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            columns = {column["name"]: column for column in await conn.run_sync(lambda connection: sa.inspect(connection).get_columns("scheduled_task_runs"))}
            version = await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
            overlap_policy = await conn.scalar(sa.text("SELECT overlap_policy FROM scheduled_tasks WHERE id = 'task-legacy'"))
            legacy_run = (await conn.execute(sa.text("SELECT status, error, finished_at FROM scheduled_task_runs WHERE id = 'run-legacy-queued'"))).one()
            index_sql = await conn.scalar(sa.text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'uq_scheduled_task_run_active'"))

        # Bootstrap always advances to the repository head after exercising
        # the 0015 migration behavior below.
        assert version == "0018_oauth_identity_pg_partial"
        assert {"lease_owner", "lease_expires_at", "attempt_count"} <= columns.keys()
        assert columns["attempt_count"]["nullable"] is False
        assert overlap_policy == "enqueue"
        assert legacy_run.status == "interrupted"
        assert "gateway upgraded" in legacy_run.error
        assert legacy_run.finished_at is not None
        assert "'launching'" in index_sql
    finally:
        await engine.dispose()
