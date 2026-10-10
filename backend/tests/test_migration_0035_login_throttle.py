"""Migration 0035: the shared ``login_throttle`` table for cross-replica lockouts."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.login_throttle import LoginThrottleRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0035_login_throttle"
RUN_IDEMPOTENCY = "0036_run_idempotency_request"
PREVIOUS = "0034_run_event_seq_watermark"
TABLE = "login_throttle"
COLUMNS = {"ip", "fail_count", "locked_at", "lock_duration_seconds", "updated_at"}
INDEX = "ix_login_throttle_updated_at"
pytestmark = pytest.mark.asyncio


async def test_0035_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(RUN_IDEMPOTENCY).down_revision == REVISION
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0035)")
    schema = f"login_throttle_{uuid.uuid4().hex}"
    return create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)), schema


async def _shape(engine) -> dict:
    async with engine.connect() as conn:

        def read(sync):
            inspector = sa.inspect(sync)
            tables = set(inspector.get_table_names())
            if TABLE not in tables:
                return {"tables": tables}
            return {
                "tables": tables,
                "columns": {col["name"]: col for col in inspector.get_columns(TABLE)},
                "pk": inspector.get_pk_constraint(TABLE)["constrained_columns"],
                "indexes": {index["name"]: index["column_names"] for index in inspector.get_indexes(TABLE)},
            }

        return await conn.run_sync(read)


async def _orm_diff(engine) -> list:
    """Alembic's own drift check, restricted to the table this revision owns."""

    def only_login_throttle(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_login_throttle, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(diff)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0035_creates_the_table_matching_the_orm_and_downgrades_cleanly(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        assert TABLE not in (await _shape(engine))["tables"]

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert set(shape["columns"]) == COLUMNS
        assert shape["pk"] == ["ip"]
        assert shape["columns"]["fail_count"]["nullable"] is False
        assert shape["columns"]["locked_at"]["nullable"] is True
        assert shape["columns"]["lock_duration_seconds"]["nullable"] is True
        assert shape["columns"]["updated_at"]["nullable"] is False
        assert shape["indexes"][INDEX] == ["updated_at"]  # serves the sweep's stale-counter predicate
        # ``make migrate-rev`` would propose nothing: the revision matches the ORM model.
        assert await _orm_diff(engine) == []

        async with engine.begin() as conn:
            await conn.execute(sa.insert(LoginThrottleRow).values(ip="198.51.100.1", fail_count=5, locked_at=1_700_000_000.5, lock_duration_seconds=300.0, updated_at=sa.func.now()))
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(LoginThrottleRow).values(ip="198.51.100.1", fail_count=1, updated_at=sa.func.now()))
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text(f"SELECT fail_count, locked_at, lock_duration_seconds FROM {TABLE}"))).one()
        assert tuple(row) == (5, 1_700_000_000.5, 300.0)

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        shape = await _shape(engine)
        assert TABLE not in shape["tables"]
        async with engine.connect() as conn:
            # The index goes with the table on downgrade (named, so a leftover would be visible).
            leftover = await conn.run_sync(lambda sync: [name for table in sa.inspect(sync).get_table_names() for name in {index["name"] for index in sa.inspect(sync).get_indexes(table)} if name == INDEX])
        assert leftover == []

        # Downgrade then upgrade again is clean.
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        shape = await _shape(engine)
        assert TABLE in shape["tables"]
        assert INDEX in shape["indexes"]
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0035_completes_a_partially_applied_upgrade(tmp_path, backend):
    """The table already exists (an interrupted earlier attempt): upgrade still lands."""
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            # The table exists but its index was never built (an interrupted earlier attempt).
            await conn.run_sync(Base.metadata.create_all, tables=[LoginThrottleRow.__table__])
            await conn.execute(sa.text(f"DROP INDEX {INDEX}"))
            await conn.execute(sa.insert(LoginThrottleRow).values(ip="203.0.113.9", fail_count=2, updated_at=sa.func.now()))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert INDEX in (await _shape(engine))["indexes"]  # the partial upgrade is completed
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT fail_count FROM {TABLE} WHERE ip='203.0.113.9'"))).scalar_one() == 2
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION

        # A downgrade after someone already dropped the table still completes.
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE {TABLE}"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == PREVIOUS
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_bootstrap_provisions_the_table_on_an_empty_database_and_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    try:
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        shape = await _shape(engine)
        assert set(shape["columns"]) == COLUMNS
        assert INDEX in shape["indexes"]
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == bootstrap._get_head_revision()
    finally:
        await engine.dispose()
