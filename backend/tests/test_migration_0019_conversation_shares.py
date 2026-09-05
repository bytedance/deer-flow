"""Migration tests for 0019_conversation_shares (#4548).

Runs the full alembic chain on an empty SQLite database (not
``create_all`` + stamp), then exercises the 0018 downgrade/upgrade cycle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

pytestmark = pytest.mark.asyncio

_SCRIPT_LOCATION = str(_MIGRATIONS_DIR)
_REVISION = "0019_conversation_shares"
_PREVIOUS = "0017_personal_access_tokens"

_EXPECTED_COLUMNS = {
    "id",
    "thread_id",
    "owner_user_id",
    "token_hash",
    "title",
    "snapshot_version",
    "snapshot_json",
    "source_last_seq",
    "expires_at",
    "revoked_at",
    "created_at",
    "updated_at",
}


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    # Escape % for ConfigParser (SQLite URLs carry none, Postgres passwords might).
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _table_names(sync_conn) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _column_names(sync_conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(sync_conn).get_columns(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def test_share_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "share-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Alembic's env.py drives migrations with its own asyncio.run, so the
        # sync command API must run off the test loop (same wrapper the
        # production bootstrap uses).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "conversation_shares" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "conversation_shares"))
        assert columns == _EXPECTED_COLUMNS
        indexes = await _inspect(
            engine,
            lambda conn: {idx["name"]: idx for idx in sa.inspect(conn).get_indexes("conversation_shares")},
        )
        # Token-hash lookup is the public hot path and must stay unique.
        # (SQLite reports uniqueness as int 1; Postgres as bool.)
        assert indexes["ix_conversation_shares_token_hash"]["unique"] in (True, 1)
        assert "ix_conversation_shares_thread_id" in indexes

        # Downgrade to the previous revision drops exactly this table.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        assert "conversation_shares" not in await _inspect(engine, _table_names)

        # Upgrade again recreates it (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        assert "conversation_shares" in await _inspect(engine, _table_names)
    finally:
        await engine.dispose()
