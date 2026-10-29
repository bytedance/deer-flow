"""Migration 0031 adds two nullable scheduled_tasks columns and removes them again."""

from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0031_scheduled_streak_boundary"
PREVIOUS = "0030_notification_claim_tokens"
NEXT = "0032_activity_and_task_events"
COLUMNS = {"unmet_streak_after_seq", "stop_condition"}
pytestmark = pytest.mark.asyncio


async def test_0031_follows_0030_and_precedes_0032():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(NEXT).down_revision == REVISION
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres scheduler migration)")
    parts = urlsplit(uri)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    schema = f"streak_boundary_{uuid.uuid4().hex}"
    return create_async_engine(urlunsplit(parts._replace(scheme=scheme, query=query)), connect_args=build_asyncpg_connect_args(schema)), schema


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0031_upgrade_keeps_rows_and_downgrade_drops_both_columns(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
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
                    "VALUES ('existing','owner','fresh_thread_per_run','Checklist','Check the list','cron','{}','UTC','paused','enqueue',4,4,'all checked',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )

        async def task_columns():
            async with engine.connect() as conn:
                return await conn.run_sync(lambda sync: {col["name"]: col for col in sa.inspect(sync).get_columns("scheduled_tasks")})

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        columns = await task_columns()
        assert all(columns[name]["nullable"] and columns[name]["default"] is None for name in COLUMNS)
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT run_count, goal_objective, prompt, unmet_streak_after_seq, stop_condition FROM scheduled_tasks WHERE id='existing'"))).one()
        assert tuple(row) == (4, "all checked", "Check the list", None, None)

        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE scheduled_tasks SET stop_condition='every item is checked', unmet_streak_after_seq=4 WHERE id='existing'"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert COLUMNS.isdisjoint(await task_columns())
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT run_count, prompt FROM scheduled_tasks WHERE id='existing'"))).one() == (4, "Check the list")
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert COLUMNS <= set(await task_columns())
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
