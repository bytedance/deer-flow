"""Migration tests for 0024_project_documents (Phase-2 spec §6.1).

Pins the table shape and the four indexes on upgrade, the clean downgrade,
and the chain head (the forward-revision-compat pin moved here with 0023,
forwarded to 0024 after the rebase onto 0023_user_preferences).
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command

from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision
from deerflow.persistence.engine import close_engine, init_engine

pytestmark = pytest.mark.asyncio

REVISION = "0024_project_documents"
PREVIOUS = "0023_user_preferences"
TABLE = "project_documents"
INDEXES = {
    "ix_project_documents_project_id",
    "ix_project_documents_user_id",
    "ix_project_documents_sha256",
    "ix_project_documents_trashed_at",
}
COLUMNS = {
    "id",
    "project_id",
    "user_id",
    "name",
    "stored_relpath",
    "sha256",
    "size_bytes",
    "source_thread_id",
    "source_kind",
    "source_name",
    "trashed_at",
    "trash_origin",
    "created_at",
    "updated_at",
}


async def _engine(tmp_path, name: str = "test.db"):
    url = f"sqlite+aiosqlite:///{tmp_path / name}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    from deerflow.persistence.engine import get_engine

    return get_engine()


async def _inspect(engine):
    async with engine.connect() as conn:

        def _read(sync_conn):
            inspector = sa.inspect(sync_conn)
            return (
                inspector.has_table(TABLE),
                {c["name"] for c in inspector.get_columns(TABLE)} if inspector.has_table(TABLE) else set(),
                {i["name"] for i in inspector.get_indexes(TABLE)} if inspector.has_table(TABLE) else set(),
            )

        return await conn.run_sync(_read)


async def test_0024_is_the_chain_head():
    assert _get_head_revision() == REVISION


async def test_0024_upgrade_creates_table_and_indexes(tmp_path):
    engine = await _engine(tmp_path)
    try:
        exists, columns, indexes = await _inspect(engine)
        assert exists
        assert columns == COLUMNS
        assert INDEXES <= indexes
    finally:
        await close_engine()


async def test_0024_downgrade_drops_table_and_reupgrade_recreates(tmp_path):
    engine = await _engine(tmp_path)
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        exists, _, _ = await _inspect(engine)
        assert not exists

        # Downgrade is guarded and idempotent: repeating it is a no-op.
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        exists, columns, indexes = await _inspect(engine)
        assert exists
        assert columns == COLUMNS
        assert INDEXES <= indexes
    finally:
        await close_engine()


async def test_0024_upgrade_is_guarded_against_an_existing_table(tmp_path):
    """The inspector.has_table idiom keeps re-running the revision a no-op."""
    engine = await _engine(tmp_path)
    try:
        cfg = _get_alembic_config(engine)
        # Simulate a database that already carries the table (create_all
        # bootstrap path): upgrading again must not fail.
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        exists, columns, _ = await _inspect(engine)
        assert exists and columns == COLUMNS
    finally:
        await close_engine()
