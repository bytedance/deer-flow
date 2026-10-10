"""The dedupe receipt column is additive, idempotent and matches create_all."""

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
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.webhook_delivery.model import WebhookDeliveryRow  # noqa: F401 -- registers the ORM table

REVISION = "0040_webhook_claim_tokens"
PREVIOUS = "0039_user_disabled"
TABLE = "webhook_deliveries"
LEGACY_COLUMNS = {"channel", "workspace_id", "chat_id", "message_id", "first_seen"}
pytestmark = pytest.mark.asyncio


async def test_0040_extends_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'claims.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres dedupe migration)")
    schema = f"dedupe_claims_{uuid.uuid4().hex}"
    return create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)), schema


async def _columns(engine):
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda sync: sa.inspect(sync).get_columns(TABLE))
    return {column["name"]: column for column in columns}


async def _legacy_row(engine):
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(f"SELECT channel, workspace_id, chat_id, message_id, first_seen FROM {TABLE} WHERE message_id='legacy'"))).one()


async def _orm_diff(engine):
    def only_dedupe(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def compare(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_dedupe, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(compare)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0040_preserves_legacy_rows_and_supports_repeat_upgrade_and_downgrade(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        assert set(await _columns(engine)) == LEGACY_COLUMNS
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"INSERT INTO {TABLE} (channel, workspace_id, chat_id, message_id) VALUES ('slack', 'team', 'chat', 'legacy')"))
        before = await _legacy_row(engine)

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        columns = await _columns(engine)
        assert set(columns) == LEGACY_COLUMNS | {"claim_token"}
        assert columns["claim_token"]["nullable"] is True
        assert columns["claim_token"]["default"] is None
        assert columns["claim_token"]["type"].length == 32
        assert await _legacy_row(engine) == before
        assert await _orm_diff(engine) == []
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text(f"SELECT claim_token FROM {TABLE} WHERE message_id='legacy'"))).scalar_one() is None

        # An interrupted attempt already added the column: applying it again is a no-op.
        await asyncio.to_thread(command.stamp, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert await _legacy_row(engine) == before
        assert await _orm_diff(engine) == []

        # Old writers can still omit this additive nullable field during rollout.
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"INSERT INTO {TABLE} (channel, workspace_id, chat_id, message_id) VALUES ('slack', 'team', 'chat', 'old-writer')"))
            await conn.execute(sa.text(f"UPDATE {TABLE} SET claim_token=:token WHERE message_id='legacy'"), {"token": uuid.uuid4().hex})
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert set(await _columns(engine)) == LEGACY_COLUMNS
        assert await _legacy_row(engine) == before

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert await _legacy_row(engine) == before
        assert await _orm_diff(engine) == []
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
