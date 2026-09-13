"""Upgrade existing scheduler history without guessing occurrence order or counts."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository

pytestmark = pytest.mark.asyncio

REVISION = "0022_scheduled_occurrence_seq"
PREVIOUS = "0021_batch_acceptance"
INDEX = "uq_scheduled_task_run_occurrence_seq"


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def migration_database(request, tmp_path):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration)")
        parts = urlsplit(uri)
        # CI passes a sync ``postgresql://...?sslmode=disable`` URL; the async
        # engine needs the asyncpg driver and rejects libpq-only query keys.
        scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
        query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
        uri = urlunsplit(parts._replace(scheme=scheme, query=query))
        schema = f"occurrence_migration_{uuid.uuid4().hex}"
        engine = create_async_engine(uri, connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO scheduled_tasks "
                    "(id, user_id, thread_id, context_mode, assistant_id, title, prompt, "
                    "schedule_type, schedule_spec, timezone, status, overlap_policy, run_count, created_at, updated_at) "
                    "VALUES ('task-legacy', 'user-1', 'thread-1', 'reuse_thread', 'lead_agent', "
                    "'Legacy', 'Prompt', 'cron', '{\"cron\":\"0 9 * * *\"}', 'UTC', "
                    "'enabled', 'enqueue', 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            for run_id in ("legacy-a", "legacy-b"):
                await connection.execute(
                    sa.text("INSERT INTO scheduled_task_runs (id, task_id, thread_id, scheduled_for, trigger, status, created_at) VALUES (:run_id, 'task-legacy', 'thread-1', CURRENT_TIMESTAMP, 'manual', 'success', CURRENT_TIMESTAMP)"),
                    {"run_id": run_id},
                )
        yield engine, cfg
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def _schema(engine):
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda conn: (
                {column["name"]: column for column in sa.inspect(conn).get_columns("scheduled_tasks")},
                {column["name"]: column for column in sa.inspect(conn).get_columns("scheduled_task_runs")},
                {index["name"]: index for index in sa.inspect(conn).get_indexes("scheduled_task_runs")},
            )
        )


async def test_occurrence_revision_is_single_head():
    # The conversation-shares series (0024/0025) chains after this revision
    # per the second-to-land rule, so the merged tree's single head is the
    # shares quota revision. The pin still fails on any branching.
    assert _get_head_revision() == "0025_conversation_share_quotas"


async def test_upgrade_preserves_legacy_rows_and_allocates_from_one(migration_database):
    engine, cfg = migration_database
    before_task, before_run, _before_indexes = await _schema(engine)
    assert "last_occurrence_seq" not in before_task
    assert {"occurrence_seq", "launch_accounted"}.isdisjoint(before_run)
    await asyncio.to_thread(command.upgrade, cfg, REVISION)
    task_columns, run_columns, indexes = await _schema(engine)
    assert task_columns["last_occurrence_seq"]["nullable"] is False
    assert run_columns["occurrence_seq"]["nullable"] is True
    assert run_columns["occurrence_seq"]["default"] is None
    assert run_columns["launch_accounted"]["nullable"] is True
    assert run_columns["launch_accounted"]["default"] is None
    assert indexes[INDEX]["column_names"] == ["task_id", "occurrence_seq"]
    assert indexes[INDEX]["unique"]
    async with engine.connect() as connection:
        legacy = (await connection.execute(sa.text("SELECT occurrence_seq, launch_accounted FROM scheduled_task_runs ORDER BY id"))).all()
        task = (await connection.execute(sa.text("SELECT last_occurrence_seq, run_count, updated_at FROM scheduled_tasks WHERE id = 'task-legacy'"))).one()
    assert legacy == [(None, None), (None, None)]
    assert task.last_occurrence_seq == 0
    assert task.run_count == 7

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await ScheduledTaskRunRepository(factory).create(
        run_record_id="new",
        task_id="task-legacy",
        thread_id="thread-new",
        scheduled_for=datetime.now(UTC),
        trigger="manual",
        status="success",
    )
    async with engine.connect() as connection:
        new_run = (await connection.execute(sa.text("SELECT occurrence_seq, launch_accounted FROM scheduled_task_runs WHERE id = 'new'"))).one()
        after_task = (await connection.execute(sa.text("SELECT last_occurrence_seq, run_count, updated_at FROM scheduled_tasks WHERE id = 'task-legacy'"))).one()
    assert new_run.occurrence_seq == 1
    assert new_run.launch_accounted is not None
    assert not new_run.launch_accounted
    assert after_task.last_occurrence_seq == 1
    assert after_task.run_count == 7
    assert after_task.updated_at == task.updated_at


async def test_migration_retry_and_downgrade_preserve_history(migration_database):
    engine, cfg = migration_database
    await asyncio.to_thread(command.upgrade, cfg, REVISION)
    # A retry can encounter the additive DDL already applied before stamping.
    await asyncio.to_thread(command.stamp, cfg, PREVIOUS)
    await asyncio.to_thread(command.upgrade, cfg, REVISION)
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT COUNT(*) FROM scheduled_task_runs")) == 2
        assert await connection.scalar(sa.text("SELECT run_count FROM scheduled_tasks WHERE id = 'task-legacy'")) == 7
    await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
    task_columns, run_columns, indexes = await _schema(engine)
    assert "last_occurrence_seq" not in task_columns
    assert {"occurrence_seq", "launch_accounted"}.isdisjoint(run_columns)
    assert INDEX not in indexes
    await asyncio.to_thread(command.upgrade, cfg, REVISION)
    async with engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT COUNT(*) FROM scheduled_task_runs")) == 2
        assert await connection.scalar(sa.text("SELECT run_count FROM scheduled_tasks WHERE id = 'task-legacy'")) == 7


async def test_migration_unique_index_accepts_nulls_and_rejects_duplicate_sequence(migration_database):
    engine, cfg = migration_database
    await asyncio.to_thread(command.upgrade, cfg, REVISION)
    async with engine.begin() as connection:
        await connection.execute(sa.text("UPDATE scheduled_task_runs SET occurrence_seq = 1 WHERE id = 'legacy-a'"))
        with pytest.raises(sa.exc.IntegrityError):
            async with connection.begin_nested():
                await connection.execute(sa.text("UPDATE scheduled_task_runs SET occurrence_seq = 1 WHERE id = 'legacy-b'"))
        await connection.execute(sa.text("UPDATE scheduled_task_runs SET occurrence_seq = 2 WHERE id = 'legacy-b'"))
