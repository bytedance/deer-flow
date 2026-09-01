"""Migration tests for 0017_personal_access_tokens (#4849).

Runs the full alembic chain on an empty SQLite database (not
``create_all`` + stamp), then exercises the 0017 downgrade/upgrade cycle.
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
_REVISION = "0017_personal_access_tokens"
_PREVIOUS = "0016_subagent_batches"

_EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "name",
    "token_digest",
    "scopes",
    "expires_at",
    "last_used_at",
    "created_at",
    "revoked_at",
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


async def test_pat_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "pat-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Alembic's env.py drives migrations with its own asyncio.run, so the
        # sync command API must run off the test loop (same wrapper the
        # production bootstrap uses).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "personal_access_tokens" in tables
        assert "alembic_version" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "personal_access_tokens"))
        assert columns == _EXPECTED_COLUMNS
        indexes = await _inspect(
            engine,
            lambda conn: {idx["name"] for idx in sa.inspect(conn).get_indexes("personal_access_tokens")},
        )
        # Owner listing + digest lookups are the two hot paths.
        assert "ix_personal_access_tokens_user_id" in indexes
        assert "ix_personal_access_tokens_token_digest" in indexes

        # Downgrade to the previous revision drops exactly this table.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        tables_after_down = await _inspect(engine, _table_names)
        assert "personal_access_tokens" not in tables_after_down

        # Upgrade again recreates it (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        tables_after_up = await _inspect(engine, _table_names)
        assert "personal_access_tokens" in tables_after_up
    finally:
        await engine.dispose()
