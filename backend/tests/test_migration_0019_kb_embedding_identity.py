"""Migration ``0019_kb_embedding_identity``: knowledge_bases.embedding_identity column.

D2 (spec 2026-10-04): record which embedding coordinate space a library's vectors
live in, so a later config change can tell "this library is stale" from "unknown".

Shape (mirrors 0013):
1. Hand-build a SQLite DB at revision 77df30935788 minus the embedding_identity
   column, with one legacy knowledge-base row.
2. Run init_engine -> upgrade head.
3. The column exists, the legacy row reads NULL (unstamped = unknown, not "current").
4. downgrade back to 77df30935788 drops the column again.
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
from deerflow.knowledge.models import KnowledgeBaseRow  # noqa: F401 -- registers the knowledge tables
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR
from deerflow.persistence.engine import close_engine, init_engine

pytestmark = pytest.mark.asyncio


def _kb_columns(db_path: Path) -> set[str]:
    """Get column names from knowledge_bases."""
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(knowledge_bases)").fetchall()}


def _seed_pre_0019(db_path: Path) -> None:
    """Build a versioned DB at 77df30935788 with one KB row and no embedding_identity."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(knowledge_bases)")).fetchall()}
            if "embedding_identity" in cols:
                conn.execute(sa.text("ALTER TABLE knowledge_bases DROP COLUMN embedding_identity"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('77df30935788')"))
            conn.execute(sa.text("INSERT INTO knowledge_bases (id, owner_id, name, description, visibility, created_at) VALUES ('kb-legacy', 'user-1', '遗留库', NULL, 'private', '2026-08-11 00:00:00+00:00')"))
    finally:
        sync_engine.dispose()


async def test_migration_0019_adds_embedding_identity_column(tmp_path: Path) -> None:
    """Migration adds embedding_identity; a legacy row stays NULL (unstamped)."""
    db_path = tmp_path / "legacy.db"
    _seed_pre_0019(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert "embedding_identity" in _kb_columns(db_path)

        with sqlite3.connect(db_path) as raw:
            value = raw.execute("SELECT embedding_identity FROM knowledge_bases WHERE id = 'kb-legacy'").fetchone()[0]
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        # Spec contract: nullable with no server default - old rows stay NULL,
        # and NULL means "unknown", never "current".
        assert value is None
        assert version == "0019_kb_embedding_identity"
    finally:
        await close_engine()


async def test_migration_0019_downgrade_drops_column(tmp_path: Path) -> None:
    """Migration downgrade removes embedding_identity; upgrade brings it back."""
    db_path = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition keeps the test non-vacuous: at head the column exists.
        assert "embedding_identity" in _kb_columns(db_path)
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "77df30935788")

    assert "embedding_identity" not in _kb_columns(db_path)

    # And back up - the column returns (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert "embedding_identity" in _kb_columns(db_path)
