"""Migration 0047: the shared, encrypted ``mcp_oauth_tokens`` table, and the current migration-chain head."""

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
from deerflow.persistence.mcp_oauth_tokens import McpOAuthTokenRow
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

REVISION = "0047_mcp_oauth_tokens"
PREVIOUS = "0046_skill_mutations"
TABLE = "mcp_oauth_tokens"
COLUMNS = {
    "scope",
    "owner_user_id",
    "server_key",
    "config_fingerprint",
    "access_token_enc",
    "token_request_fingerprint",
    "token_type",
    "access_expires_at",
    "refresh_token_enc",
    "version",
    "refresh_lease_owner",
    "refresh_lease_until",
    "rotated_at",
    "updated_at",
}
NULLABLE = {"access_token_enc", "token_request_fingerprint", "token_type", "access_expires_at", "refresh_token_enc", "refresh_lease_owner", "refresh_lease_until", "rotated_at"}
pytestmark = pytest.mark.asyncio


async def test_0047_is_the_chain_head():
    assert bootstrap._get_head_revision() == REVISION
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "0045_completed_run_evidence"
    # alembic_version.version_num is VARCHAR(32).
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0047)")
    schema = f"mcp_oauth_tokens_{uuid.uuid4().hex}"
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

    def only_oauth_tokens(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name == TABLE
        return getattr(getattr(obj, "table", None), "name", TABLE) == TABLE

    async with engine.connect() as conn:

        def diff(sync):
            context = MigrationContext.configure(sync, opts={"include_object": only_oauth_tokens, "compare_type": True, "compare_server_default": True})
            return compare_metadata(context, Base.metadata)

        return await conn.run_sync(diff)


async def _drop_schema(engine, schema):
    if schema:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _row(**overrides) -> dict:
    values = {"scope": "deployment", "owner_user_id": "", "server_key": "reports", "config_fingerprint": "f" * 64, "version": 0, "updated_at": 1_700_000_000.0}
    values.update(overrides)
    return values


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0047_creates_the_table_matching_the_orm_and_downgrades_cleanly(tmp_path, backend):
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
        assert shape["pk"]["constrained_columns"] == ["scope", "owner_user_id", "server_key"]
        assert shape["pk"]["name"] in ("pk_mcp_oauth_tokens", None)  # SQLite does not report constraint names
        # Token columns are empty while the first refresh is claimed; the key never is.
        assert {name for name, column in shape["columns"].items() if column["nullable"]} == NULLABLE
        # ``make migrate-rev`` would propose nothing: the revision matches the ORM model.
        assert await _orm_diff(engine) == []

        async with engine.begin() as conn:
            await conn.execute(sa.insert(McpOAuthTokenRow).values(**_row()))
            # A personal connection may reuse a deployment server's name.
            await conn.execute(sa.insert(McpOAuthTokenRow).values(**_row(scope="personal", owner_user_id="user-1")))
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(sa.insert(McpOAuthTokenRow).values(**_row(version=3)))

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert TABLE not in (await _shape(engine))["tables"]
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        assert TABLE in (await _shape(engine))["tables"]
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_0047_completes_after_create_all_and_downgrades_after_a_manual_drop(tmp_path, backend):
    """The table already exists (an interrupted earlier attempt): upgrade still lands, and vice versa."""
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[McpOAuthTokenRow.__table__])

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
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == REVISION
    finally:
        await engine.dispose()
