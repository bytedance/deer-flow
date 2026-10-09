"""Migration 0032: run origin column and index, read-state tables, task events."""

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

REVISION = "0032_activity_and_task_events"
NEXT = "0033_batch_result_artifact"
AFTER_NEXT = "0034_run_event_seq_watermark"
LOGIN_THROTTLE = "0035_login_throttle"
PREVIOUS = "0031_scheduled_streak_boundary"
TABLES = {"thread_read_markers", "thread_read_versions", "scheduled_task_events"}
INDEXES = {
    "runs": {"ix_runs_thread_change_seq"},
    "thread_read_markers": {"ix_thread_read_markers_thread_id"},
    "scheduled_task_events": {"ix_scheduled_task_events_thread", "ix_scheduled_task_events_user_id"},
}
pytestmark = pytest.mark.asyncio


async def test_0032_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(NEXT).down_revision == REVISION
    assert script.get_revision(AFTER_NEXT).down_revision == NEXT
    assert script.get_revision(LOGIN_THROTTLE).down_revision == AFTER_NEXT
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0032)")
    parts = urlsplit(uri)
    scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    schema = f"activity_events_{uuid.uuid4().hex}"
    return create_async_engine(urlunsplit(parts._replace(scheme=scheme, query=query)), connect_args=build_asyncpg_connect_args(schema)), schema


async def _shape(engine) -> dict:
    async with engine.connect() as conn:

        def read(sync):
            inspector = sa.inspect(sync)
            tables = set(inspector.get_table_names())
            return {
                "tables": tables,
                "run_columns": {col["name"]: col for col in inspector.get_columns("runs")},
                "indexes": {table: {index["name"] for index in inspector.get_indexes(table)} for table in INDEXES if table in tables},
                "uniques": {constraint["name"]: constraint["column_names"] for constraint in inspector.get_unique_constraints("scheduled_task_events")} if "scheduled_task_events" in tables else {},
            }

        return await conn.run_sync(read)


async def _insert_legacy_run(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO runs (run_id,thread_id,user_id,status,operation_kind,multitask_strategy,metadata_json,kwargs_json,message_count,"
                "total_input_tokens,total_output_tokens,total_tokens,llm_call_count,lead_agent_tokens,subagent_tokens,middleware_tokens,"
                "token_usage_by_model,change_seq,created_at,updated_at) "
                "VALUES ('legacy-run','legacy-thread','owner','success','run','reject','{}','{}',0,0,0,0,0,0,0,0,'{}',7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0032_upgrade_keeps_runs_and_downgrade_drops_everything(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        await _insert_legacy_run(engine)

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert TABLES <= shape["tables"]
        assert shape["run_columns"]["origin_kind"]["nullable"] is True
        assert shape["run_columns"]["origin_kind"]["default"] is None
        for table, names in INDEXES.items():
            assert names <= shape["indexes"][table], table
        assert shape["uniques"]["uq_scheduled_task_event"] == ["task_id", "anchor", "event"]
        async with engine.connect() as conn:
            # Never backfilled: legacy runs stay "interactive or unknown".
            row = (await conn.execute(sa.text("SELECT origin_kind, change_seq, status FROM runs WHERE run_id='legacy-run'"))).one()
        assert tuple(row) == (None, 7, "success")

        # The unique key deduplicates lifecycle events at the database level.
        insert = sa.text(
            "INSERT INTO scheduled_task_events (id,user_id,task_id,thread_id,occurrence_id,anchor,event,reason_code,after_run_id,payload_json,created_at) "
            "VALUES (:id,'owner','task','origin','occ','occ','task_finished','max_runs',NULL,'{}',CURRENT_TIMESTAMP)"
        )
        async with engine.begin() as conn:
            await conn.execute(insert, {"id": "evt-1"})
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(insert, {"id": "evt-2"})

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        shape = await _shape(engine)
        assert TABLES.isdisjoint(shape["tables"])
        assert "origin_kind" not in shape["run_columns"]
        assert "ix_runs_thread_change_seq" not in shape["indexes"]["runs"]
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT change_seq FROM runs WHERE run_id='legacy-run'"))).scalar_one() == 7

        # Downgrade then upgrade again is clean.
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert TABLES <= (await _shape(engine))["tables"]
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0032_completes_a_partially_applied_upgrade(tmp_path, backend):
    """One table and the column already exist, the runs index is missing."""
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE runs ADD COLUMN origin_kind VARCHAR(32)"))
            await conn.execute(sa.text("CREATE TABLE thread_read_versions (user_id VARCHAR(64) NOT NULL, version BIGINT DEFAULT 0 NOT NULL, CONSTRAINT pk_thread_read_versions PRIMARY KEY (user_id))"))
            await conn.execute(sa.text("INSERT INTO thread_read_versions (user_id, version) VALUES ('owner', 3)"))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert TABLES <= shape["tables"]
        for table, names in INDEXES.items():
            assert names <= shape["indexes"][table], table
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version FROM thread_read_versions WHERE user_id='owner'"))).scalar_one() == 3
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION

        # A downgrade that already removed part of the schema still completes.
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP TABLE scheduled_task_events"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        shape = await _shape(engine)
        assert TABLES.isdisjoint(shape["tables"])
        assert "origin_kind" not in shape["run_columns"]
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
