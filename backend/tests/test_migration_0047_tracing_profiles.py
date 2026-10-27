"""Both upgrade and empty-database bootstrap provision tracing authority tables."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

TABLES = {"tracing_profiles", "tracing_profile_versions", "agent_tracing_bindings", "run_tracing_snapshots", "tracing_admission_fence"}
REVISION = "0047_tracing_profiles"
PREVIOUS = "0046_skill_mutations"


def test_0047_tracing_retains_its_parent_before_the_merge():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_revision(REVISION).down_revision == PREVIOUS


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_tracing_schema_matches_orm_for_fresh_and_upgraded_database(tmp_path, existing, backend):
    schema = ""
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI for real PostgreSQL migration coverage")
        schema = f"tracing_{uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema)
    try:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        if existing:
            await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
            await asyncio.to_thread(command.upgrade, cfg, REVISION)
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            await asyncio.to_thread(command.upgrade, cfg, "head")
        else:
            await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema)
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert TABLES <= tables
            columns = await connection.run_sync(lambda sync: {column["name"] for column in inspect(sync).get_columns("scheduled_task_runs")})
            assert "tracing_snapshot_refs" in columns
            assert (await connection.execute(text("SELECT id FROM tracing_admission_fence"))).scalars().all() == [1]

            def diff(sync):
                context = MigrationContext.configure(sync, opts={"include_object": lambda obj, name, kind, reflected, compare_to: name in TABLES if kind == "table" else True, "compare_type": True})
                return compare_metadata(context, Base.metadata)

            assert await connection.run_sync(diff) == []
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0050_merge_tracing_extension"
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert not TABLES.intersection(tables)
            columns = await connection.run_sync(lambda sync: {column["name"] for column in inspect(sync).get_columns("scheduled_task_runs")})
            assert "tracing_snapshot_refs" not in columns
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert TABLES <= tables
            assert (await connection.execute(text("SELECT id FROM tracing_admission_fence"))).scalars().all() == [1]
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
