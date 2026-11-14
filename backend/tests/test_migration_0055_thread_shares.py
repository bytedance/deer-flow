"""Migration and ORM shapes agree; upgrades preserve existing conversations."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_share_upgrade_downgrade_and_schema(tmp_path, backend):
    schema = None
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "share_migration_" + uuid.uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, config, "0054_project_memory")
        async with engine.begin() as conn:
            await conn.execute(
                ThreadMetaRow.__table__.insert().values(thread_id="existing", user_id="alice", display_name="Existing conversation", status="idle", metadata_json={}, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            )
        await asyncio.to_thread(command.upgrade, config, "0055_thread_shares")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT display_name FROM threads_meta WHERE thread_id='existing'"))).scalar_one() == "Existing conversation"

            def schema_diff(sync):
                context = MigrationContext.configure(sync, opts={"compare_type": True, "include_object": lambda obj, name, type_, reflected, compare_to: type_ != "table" or name in {"thread_shares", "share_artifacts"}})
                return compare_metadata(context, Base.metadata)

            assert await conn.run_sync(schema_diff) == []
        await asyncio.to_thread(command.downgrade, config, "0054_project_memory")
        await asyncio.to_thread(command.upgrade, config, "0055_thread_shares")
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
