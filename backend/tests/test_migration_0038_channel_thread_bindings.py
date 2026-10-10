"""Migration 0038: the shared ``channel_thread_bindings`` table (IM chat -> DeerFlow thread)."""

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
from deerflow.persistence.channel_thread_bindings import ChannelThreadBindingRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0038_channel_thread_bindings"
PREVIOUS = "0037_project_document_summaries"
TABLE = "channel_thread_bindings"
COLUMNS = {"key", "channel_name", "chat_id", "topic_id", "thread_id", "user_id", "created_at", "updated_at"}
INDEX = "ix_channel_thread_bindings_channel_chat"
pytestmark = pytest.mark.asyncio


async def test_0038_is_the_single_head_and_chains_after_0037():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0038)")
    schema = f"channel_bindings_{uuid.uuid4().hex}"
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

    def only_bindings(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_bindings, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(diff)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0038_creates_the_table_matching_the_orm_and_downgrades_cleanly(tmp_path, backend):
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
        assert shape["pk"] == ["key"]
        assert shape["columns"]["channel_name"]["nullable"] is False
        assert shape["columns"]["chat_id"]["nullable"] is False
        assert shape["columns"]["topic_id"]["nullable"] is True
        assert shape["columns"]["thread_id"]["nullable"] is False
        assert shape["columns"]["user_id"]["nullable"] is False
        assert shape["columns"]["created_at"]["nullable"] is False
        assert shape["columns"]["updated_at"]["nullable"] is False
        assert shape["indexes"][INDEX] == ["channel_name", "chat_id"]  # serves list_entries(channel) and the prefix remove
        # ``make migrate-rev`` would propose nothing: the revision matches the ORM model.
        assert await _orm_diff(engine) == []

        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(ChannelThreadBindingRow).values(key="slack:C1:171.1", channel_name="slack", chat_id="C1", topic_id="171.1", thread_id="thread-1", user_id="U1", created_at=1_700_000_000.0, updated_at=1_700_000_000.5)
            )
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(ChannelThreadBindingRow).values(key="slack:C1:171.1", channel_name="slack", chat_id="C1", thread_id="thread-2", user_id="", created_at=1.0, updated_at=1.0))
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text(f"SELECT channel_name, chat_id, topic_id, thread_id, user_id, created_at, updated_at FROM {TABLE}"))).one()
        assert tuple(row) == ("slack", "C1", "171.1", "thread-1", "U1", 1_700_000_000.0, 1_700_000_000.5)

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
async def test_0038_completes_a_partially_applied_upgrade(tmp_path, backend):
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
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelThreadBindingRow.__table__])
            await conn.execute(sa.text(f"DROP INDEX {INDEX}"))
            await conn.execute(sa.insert(ChannelThreadBindingRow).values(key="slack:C1", channel_name="slack", chat_id="C1", thread_id="thread-1", user_id="", created_at=1.0, updated_at=1.0))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert INDEX in (await _shape(engine))["indexes"]  # the partial upgrade is completed
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT thread_id FROM {TABLE} WHERE key='slack:C1'"))).scalar_one() == "thread-1"
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
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION
    finally:
        await engine.dispose()
