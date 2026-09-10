"""Migration tests for 0023_conversation_share_quotas (#4548).

Runs the real alembic chain on an empty SQLite database, seeds shares at
the previous revision, and verifies the quota table is created, backfilled
from existing rows, and dropped cleanly on downgrade.
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
_REVISION = "0023_conversation_share_quotas"
_PREVIOUS = "0022_conversation_shares"

_EXPECTED_COLUMNS = {"owner_user_id", "stored_shares"}


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    # Escape % for ConfigParser (SQLite URLs carry none; Postgres passwords might).
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _table_names(sync_conn) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _column_names(sync_conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(sync_conn).get_columns(table)}


def _index_names(sync_conn, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(sync_conn).get_indexes(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def test_quota_migration_upgrades_backfills_and_downgrades(tmp_path: Path) -> None:
    db_path = tmp_path / "share-quota-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Stop at the previous revision, then seed shares the way a live
        # deployment would have them before this migration ran.
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO conversation_shares (id, thread_id, owner_user_id, token_hash, title,"
                    " snapshot_version, snapshot_json, source_last_seq, expires_at, revoked_at, created_at, updated_at)"
                    " VALUES ('s1', 't1', 'owner-a', 'h1', 'x', 1, '{}', NULL, NULL, NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00'),"
                    " ('s2', 't1', 'owner-a', 'h2', 'x', 1, '{}', NULL, NULL, NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00'),"
                    " ('s3', 't2', 'owner-b', 'h3', 'x', 1, '{}', NULL, NULL, NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
                )
            )

        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "conversation_share_quotas" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "conversation_share_quotas"))
        assert columns == _EXPECTED_COLUMNS
        # The admission counter is backfilled from rows that predate it, so
        # an upgraded deployment starts with a consistent quota.
        async with engine.connect() as conn:
            counters = {owner: stored for owner, stored in await conn.execute(sa.text("SELECT owner_user_id, stored_shares FROM conversation_share_quotas"))}
        assert counters == {"owner-a": 2, "owner-b": 1}
        # The quota count query is indexed (it runs on every creation).
        indexes = await _inspect(engine, lambda conn: _index_names(conn, "conversation_shares"))
        assert "ix_conversation_shares_owner_user_id" in indexes

        # Downgrade drops exactly this migration's objects.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        assert "conversation_share_quotas" not in await _inspect(engine, _table_names)
        indexes_after = await _inspect(engine, lambda conn: _index_names(conn, "conversation_shares"))
        assert "ix_conversation_shares_owner_user_id" not in indexes_after

        # Upgrade again recreates them (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        assert "conversation_share_quotas" in await _inspect(engine, _table_names)
    finally:
        await engine.dispose()


def test_pins_immediate_parent_revision() -> None:
    """The chain stays linear: 0023 revises 0022 and nothing else does."""
    import importlib.util
    from pathlib import Path

    module_path = Path(_MIGRATIONS_DIR) / "versions" / "0023_conversation_share_quotas.py"
    spec = importlib.util.spec_from_file_location("migration_0023", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == _REVISION
    assert module.down_revision == _PREVIOUS
