"""Migration 0042: the shared ``channel_leases`` table (per-provider IM transport leader lease)."""

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
from deerflow.persistence.channel_leases import ChannelLeaseRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0042_channel_leases"
PREVIOUS = "0041_im_notice_preferences"
NEXT = "0043_runtime_im_notices"
CURRENT_HEAD = "0044_channel_runtime_configs"
TABLE = "channel_leases"
COLUMNS = {"provider", "owner_id", "epoch", "lease_expires_at", "transport_running", "updated_at"}
pytestmark = pytest.mark.asyncio


async def test_0042_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == NEXT
    assert script.get_revision(NEXT).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0042)")
    schema = f"channel_leases_{uuid.uuid4().hex}"
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
                "pk": inspector.get_pk_constraint(TABLE),
            }

        return await conn.run_sync(read)


async def _orm_diff(engine) -> list:
    """Alembic's own drift check, restricted to the table this revision owns."""

    def only_leases(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_leases, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(diff)


async def _drop_schema(engine, schema):
    if schema:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0042_creates_the_table_matching_the_orm_and_downgrades_cleanly(tmp_path, backend):
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
        assert shape["pk"]["constrained_columns"] == ["provider"]
        assert shape["pk"]["name"] in ("pk_channel_leases", None)  # SQLite does not report constraint names
        assert all(column["nullable"] is False for column in shape["columns"].values())
        # ``make migrate-rev`` would propose nothing: the revision matches the ORM model.
        assert await _orm_diff(engine) == []

        async with engine.begin() as conn:
            await conn.execute(sa.insert(ChannelLeaseRow).values(provider="telegram", owner_id="host:worker", epoch=1, lease_expires_at=1_700_000_030.0, transport_running=True, updated_at=1_700_000_000.0))
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(ChannelLeaseRow).values(provider="telegram", owner_id="other", epoch=1, lease_expires_at=1.0, transport_running=False, updated_at=1.0))

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert TABLE not in (await _shape(engine))["tables"]
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert TABLE in (await _shape(engine))["tables"]
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0042_completes_after_create_all_and_downgrades_after_a_manual_drop(tmp_path, backend):
    """The table already exists (an interrupted earlier attempt): upgrade still lands, and vice versa."""
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION

        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE {TABLE}"))
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == PREVIOUS
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


async def test_bootstrap_provisions_the_table_on_an_empty_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    try:
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        assert set((await _shape(engine))["columns"]) == COLUMNS
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == CURRENT_HEAD
    finally:
        await engine.dispose()
