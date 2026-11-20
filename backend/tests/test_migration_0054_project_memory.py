"""Upgrade/downgrade preserves project instructions and initializes no facts."""

import asyncio
import importlib

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


def test_project_memory_upgrade_and_downgrade(tmp_path):
    migration = importlib.import_module("deerflow.persistence.migrations.versions.0054_project_memory")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE projects (id TEXT PRIMARY KEY, instructions TEXT)"))
            conn.execute(text("INSERT INTO projects VALUES ('p1', 'Keep this instruction')"))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                migration.upgrade()
                assert conn.execute(text("SELECT instructions, memory FROM projects")).one() == ("Keep this instruction", None)
                migration.downgrade()
                assert "memory" not in {c["name"] for c in inspect(conn).get_columns("projects")}
                assert conn.execute(text("SELECT instructions FROM projects")).scalar_one() == "Keep this instruction"
                migration.upgrade()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_upgrades_tool_approvals_database_without_losing_data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgraded.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, config, "0053_tool_approvals")
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO projects (id,user_id,name,instructions,presentation,status,created_at,updated_at) VALUES ('p1','u','Existing project','Keep this instruction','{}','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            )
            await conn.execute(text("INSERT INTO tool_approvals (request_id,user_id,thread_id,incarnation,run_id,fingerprint,kind,status,payload,created_at) VALUES ('r1','u','t','i','run','fingerprint','audit','consumed','{}',1)"))
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() == [bootstrap._get_head_revision()]
            assert (await conn.execute(text("SELECT instructions, memory FROM projects WHERE id='p1'"))).one() == ("Keep this instruction", None)
            assert (await conn.execute(text("SELECT status FROM tool_approvals WHERE request_id='r1'"))).scalar_one() == "consumed"
    finally:
        await engine.dispose()
