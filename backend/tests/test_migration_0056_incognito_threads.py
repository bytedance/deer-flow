"""Migration and ORM shapes agree; ordinary rows survive the incognito columns."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow


def _columns(sync_conn) -> set[str]:
    return {column["name"] for column in inspect(sync_conn).get_columns("threads_meta")}


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_incognito_upgrade_downgrade_and_schema(tmp_path, backend):
    schema = None
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "incognito_migration_" + uuid.uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, config, "0055_thread_shares")
        async with engine.begin() as conn:
            await conn.execute(
                ThreadMetaRow.__table__.insert().values(thread_id="existing", user_id="alice", display_name="Existing conversation", status="idle", metadata_json={}, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            )

        await asyncio.to_thread(command.upgrade, config, "0056_incognito_threads")

        async with engine.begin() as conn:
            legacy = (await conn.execute(text("SELECT incognito, expires_at FROM threads_meta WHERE thread_id='existing'"))).one()
            assert legacy == (None, None)
            expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)
            await conn.execute(ThreadMetaRow.__table__.insert().values(thread_id="secret", user_id="alice", status="idle", metadata_json={}, incognito=True, expires_at=expires_at, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
            secret = (await conn.execute(text("SELECT incognito, expires_at FROM threads_meta WHERE thread_id='secret'"))).one()
            assert secret[0] in (True, 1)
            assert secret[1] is not None

        async with engine.connect() as conn:

            def schema_diff(sync):
                context = MigrationContext.configure(sync, opts={"compare_type": True})
                return compare_metadata(context, Base.metadata)

            assert await conn.run_sync(schema_diff) == []

        await asyncio.to_thread(command.downgrade, config, "0055_thread_shares")
        async with engine.connect() as conn:
            columns = await conn.run_sync(_columns)
            assert "incognito" not in columns
            assert "expires_at" not in columns
            assert (await conn.execute(text("SELECT display_name FROM threads_meta WHERE thread_id='existing'"))).scalar_one() == "Existing conversation"

        await asyncio.to_thread(command.upgrade, config, "0056_incognito_threads")
        async with engine.connect() as conn:
            assert {"incognito", "expires_at"} <= await conn.run_sync(_columns)
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
