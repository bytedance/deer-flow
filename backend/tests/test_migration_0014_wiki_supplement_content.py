"""Migration ``0014_wiki_supplement_content``: wiki_entries.supplement_content column.

Phase-3 Batch-1 (P1): add supplement layer to Wiki entries for dual-mode editing,
enabling user annotations that persist across dirty regeneration cycles.

Shape:
1. Hand-build a SQLite DB at revision 0013 without the supplement_content column.
2. Run init_engine -> bootstrap_schema -> alembic upgrade head.
3. The column exists, legacy entries read NULL (backward compatible).
4. downgrade back to 0013 drops the column again.
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


def _wiki_entry_columns(db_path: Path) -> set[str]:
    """Get column names from wiki_entries table."""
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(wiki_entries)").fetchall()}


def _seed_pre_0014(db_path: Path) -> None:
    """Build a versioned DB at 0013 with one wiki entry row and no supplement_content."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(wiki_entries)"))}
            if "supplement_content" in cols:
                conn.execute(sa.text("ALTER TABLE wiki_entries DROP COLUMN supplement_content"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0013_documents_content_hash')"))
            conn.execute(sa.text("INSERT INTO wiki_entries (id, kb_id, title, content, status, source_chunk_ids, updated_at) VALUES ('wiki-legacy', 'kb-1', '多态', '面向对象特性之一', 'ready', '{}', '2026-08-15 00:00:00+00:00')"))
    finally:
        sync_engine.dispose()


async def test_migration_0014_adds_supplement_column(tmp_path: Path) -> None:
    """RED: migration adds supplement_content column."""
    db_path = tmp_path / "legacy.db"
    _seed_pre_0014(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert "supplement_content" in _wiki_entry_columns(db_path)

        # Legacy row defaults to null
        with sqlite3.connect(db_path) as raw:
            value = raw.execute("SELECT supplement_content FROM wiki_entries WHERE id = 'wiki-legacy'").fetchone()[0]
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        # Spec contract: nullable with no server default - old rows stay NULL
        assert value is None
        assert version == "0014_wiki_supplement_content"
    finally:
        await close_engine()


async def test_migration_0014_downgrade_drops_column(tmp_path: Path) -> None:
    """RED: migration downgrade removes supplement_content column."""
    db_path = tmp_path / "fresh.db"
    # Build a versioned DB at 0013 with wiki_entries table but no supplement_content.
    _seed_pre_0014(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition: after init_engine runs migrations from 0013 to head,
        # the column should now exist.
        assert "supplement_content" in _wiki_entry_columns(db_path), f"Expected column after upgrade. Found: {_wiki_entry_columns(db_path)}"
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0013_documents_content_hash")

    assert "supplement_content" not in _wiki_entry_columns(db_path)

    # And back up - the column returns (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert "supplement_content" in _wiki_entry_columns(db_path)
