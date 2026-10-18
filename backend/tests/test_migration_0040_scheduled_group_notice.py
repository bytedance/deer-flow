"""The explicit group destination is additive and retains disconnected targets."""

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0040_scheduled_group_notice"
PREVIOUS = "0039_user_disabled"
CURRENT_HEAD = "0044_channel_runtime_configs"
COLUMN = "notification_group_connection_id"


def test_group_notification_revision_has_one_head_after_0039():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision("0041_im_notice_preferences").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(REVISION) <= 32


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_group_notification_migration_preserves_legacy_rows_and_retries(tmp_path, backend):
    schema = None
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration)")
        schema = f"group_notice_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO scheduled_tasks (id,user_id,context_mode,title,prompt,schedule_type,schedule_spec,timezone,status,overlap_policy,run_count,last_occurrence_seq,goal_objective,created_at,updated_at) "
                    "VALUES ('existing','owner','fresh_thread_per_run','Report','Write report','cron','{}','UTC','paused','enqueue',4,4,'report ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.begin() as conn:
            columns = await conn.run_sync(lambda sync: {col["name"]: col for col in sa.inspect(sync).get_columns("scheduled_tasks")})
            assert columns[COLUMN]["nullable"] and columns[COLUMN]["default"] is None
            foreign_keys = await conn.run_sync(lambda sync: sa.inspect(sync).get_foreign_keys("scheduled_tasks"))
            assert all(COLUMN not in fk["constrained_columns"] for fk in foreign_keys)
            row = (await conn.execute(sa.text(f"SELECT run_count,goal_objective,{COLUMN} FROM scheduled_tasks WHERE id='existing'"))).one()
            assert tuple(row) == (4, "report ready", None)
            await conn.execute(sa.text(f"UPDATE scheduled_tasks SET {COLUMN}='disconnected-group' WHERE id='existing'"))

        # Retry upgrade over an already-added column without changing its value.
        await asyncio.to_thread(command.stamp, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT {COLUMN} FROM scheduled_tasks WHERE id='existing'"))).scalar_one() == "disconnected-group"

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("scheduled_tasks")})
            assert COLUMN not in names
            assert (await conn.execute(sa.text("SELECT run_count,goal_objective FROM scheduled_tasks WHERE id='existing'"))).one() == (4, "report ready")
        # Retry downgrade after the column is gone, then upgrade once more.
        await asyncio.to_thread(command.stamp, cfg, REVISION)
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT {COLUMN} FROM scheduled_tasks WHERE id='existing'"))).scalar_one() is None
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
