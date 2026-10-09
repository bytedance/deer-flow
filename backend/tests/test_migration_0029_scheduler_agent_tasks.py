"""Additive scheduler upgrade and meaningful unmet downgrade compatibility."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

REVISION = "0029_scheduler_agent_tasks"
CURRENT_HEAD = "0036_run_idempotency_request"
NEXT = "0030_notification_claim_tokens"
PREVIOUS = "0028_parked_attempts"
TASK_FIELDS = {"origin_thread_id", "goal_objective", "max_runs", "end_at", "standing_notes"}
OCCURRENCE_FIELDS = {"goal_objective", "goal_verdict", "stop_requested_run_id"}
pytestmark = pytest.mark.asyncio


async def test_0029_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(NEXT).down_revision == REVISION
    assert len(REVISION) <= 32


@pytest.mark.parametrize("migration_backend", ["sqlite", "postgres"])
async def test_0029_preserves_legacy_fields_and_downgrades_unmet(tmp_path, migration_backend):
    schema = None
    if migration_backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres scheduler migration)")
        parts = urlsplit(uri)
        scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        uri = urlunsplit(parts._replace(scheme=scheme, query=query))
        schema = f"scheduler_migration_{uuid.uuid4().hex}"
        engine = create_async_engine(uri, connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO scheduled_tasks (id,user_id,context_mode,title,prompt,schedule_type,schedule_spec,timezone,status,overlap_policy,run_count,created_at,updated_at) "
                    "VALUES ('legacy','owner','fresh_thread_per_run','Legacy','Prompt','cron','{}','UTC','enabled','enqueue',7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(sa.text("INSERT INTO scheduled_task_runs (id,task_id,thread_id,scheduled_for,trigger,status,created_at) VALUES ('old-occurrence','legacy','thread',CURRENT_TIMESTAMP,'scheduled','success',CURRENT_TIMESTAMP)"))
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: {table: {col["name"]: col for col in sa.inspect(sync).get_columns(table)} for table in ("runs", "scheduled_tasks", "scheduled_task_runs")})
        for table, fields in [("runs", {"goal_verdict"}), ("scheduled_tasks", TASK_FIELDS), ("scheduled_task_runs", OCCURRENCE_FIELDS)]:
            assert all(columns[table][field]["nullable"] and columns[table][field]["default"] is None for field in fields)
        # Compare with the ORM at the current head: later revisions add
        # scheduled_tasks columns (0031) that the model already declares.
        await asyncio.to_thread(command.upgrade, cfg, CURRENT_HEAD)
        async with engine.connect() as conn:

            def scheduler_schema_diff(sync):
                targets = {"runs", "scheduled_tasks", "scheduled_task_runs"}

                def include_object(obj, name, type_, reflected, compare_to):
                    return name in targets if type_ == "table" else obj.table.name in targets

                def compare_default(context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_default):
                    if isinstance(metadata_column.type, sa.JSON):
                        # PostgreSQL JSON has no equality operator. Compare
                        # decoded defaults without executing JSON '=' in SQL.
                        def decoded(value):
                            return None if value is None else json.loads(value.rsplit("::", 1)[0].strip().strip("'"))

                        return decoded(inspected_default) != decoded(rendered_default)
                    return None

                context = MigrationContext.configure(sync, opts={"include_object": include_object, "compare_type": True, "compare_server_default": compare_default})
                return compare_metadata(context, Base.metadata)

            assert await conn.run_sync(scheduler_schema_diff) == []
        repo = ScheduledTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
        legacy = await repo.get("legacy", user_id="owner")
        assert legacy["run_count"] == 7
        assert all(legacy[field] is None for field in TASK_FIELDS)
        await repo.create(
            task_id="new",
            user_id="owner",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id=None,
            title="new",
            prompt="test",
            schedule_type="interval",
            schedule_spec={"every_seconds": 3600},
            timezone="UTC",
            next_run_at=datetime.now(UTC),
            origin_thread_id="origin",
            goal_objective="deliver",
            max_runs=2,
            standing_notes=["develop branch"],
        )
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE scheduled_task_runs SET status = 'unmet', error = 'no_verdict' WHERE id = 'old-occurrence'"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT status,error FROM scheduled_task_runs WHERE id='old-occurrence'"))).one()
            assert row == ("failed", "no_verdict")
            remaining = await conn.run_sync(lambda sync: {col["name"] for col in sa.inspect(sync).get_columns("scheduled_tasks")})
            assert TASK_FIELDS.isdisjoint(remaining)
            assert (await conn.execute(sa.text("SELECT run_count FROM scheduled_tasks WHERE id='legacy'"))).scalar_one() == 7
        # The ORM model carries later scheduled_tasks columns (0031), so read
        # it back at the current head.
        await asyncio.to_thread(command.upgrade, cfg, CURRENT_HEAD)
        assert (await repo.get("new", user_id="owner"))["origin_thread_id"] is None
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
