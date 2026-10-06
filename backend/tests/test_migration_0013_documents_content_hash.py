"""Migration ``0013_documents_content_hash``: documents.content_hash column.

Task 11 (duplicate-upload interception): persist SHA-256 hash of file content for
duplicate detection - frontend computes hash on selection and compares against
existing documents in the same KB.

Shape:
1. Hand-build a SQLite DB at revision 0012 minus the content_hash column,
   with one legacy document row.
2. Run init_engine -> bootstrap_schema -> alembic upgrade head.
3. The column exists, the legacy row reads NULL (old clients unaffected).
4. downgrade back to 0012 drops the column again.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

import deerflow.persistence.models  # noqa: F401 -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR
from deerflow.persistence.engine import close_engine, init_engine

pytestmark = pytest.mark.asyncio


def _document_columns(db_path: Path) -> set[str]:
    """Get column names from documents table."""
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(documents)").fetchall()}


def _seed_pre_0013(db_path: Path) -> None:
    """Build a versioned DB at 0012 with one document row and no content_hash."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(documents)")).fetchall()}
            if "content_hash" in cols:
                conn.execute(sa.text("ALTER TABLE documents DROP COLUMN content_hash"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0012_documents_path_status')"))
            conn.execute(
                sa.text(
                    "INSERT INTO documents (id, kb_id, uploader_id, name, size_bytes, storage_path, status, progress_percent, path_status, created_at)"
                    " VALUES ('doc-legacy', 'kb-1', 'user-1', 'legacy.md', 10, '/tmp/legacy.md', 'ready', 100, '{}', '2026-08-11 00:00:00+00:00')"
                )
            )
    finally:
        sync_engine.dispose()


async def test_migration_0013_adds_content_hash_column(tmp_path: Path) -> None:
    """RED: migration adds content_hash column."""
    db_path = tmp_path / "legacy.db"
    _seed_pre_0013(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert "content_hash" in _document_columns(db_path)

        # Legacy row defaults to null
        with sqlite3.connect(db_path) as raw:
            value = raw.execute("SELECT content_hash FROM documents WHERE id = 'doc-legacy'").fetchone()[0]
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        # Spec contract: nullable with no server default - old rows stay NULL
        assert value is None
        assert version == "0013_documents_content_hash"
    finally:
        await close_engine()


async def test_migration_0013_downgrade_drops_column(tmp_path: Path) -> None:
    """RED: migration downgrade removes content_hash column."""
    db_path = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition keeps the test non-vacuous: at head the column exists.
        assert "content_hash" in _document_columns(db_path)
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0012_documents_path_status")

    assert "content_hash" not in _document_columns(db_path)

    # And back up - the column returns (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert "content_hash" in _document_columns(db_path)
