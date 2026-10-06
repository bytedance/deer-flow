"""Migration ``0016_manual_knowledge_table``: manual_knowledge table.

Phase-3 Batch-1 (P6, Task 7): user-managed knowledge cards living outside the
AI wiki lifecycle (never auto-regenerated, spec §8), carrying the
``include_in_wiki_search`` toggle that feeds the Task-8 wiki-path merge.

Shape:
1. Hand-build a SQLite DB at revision 0015 without the manual_knowledge table.
2. Run init_engine -> bootstrap_schema -> alembic upgrade head.
3. The table exists with the full P6 column set.
4. downgrade back to 0015 drops the table; upgrade head restores it.
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

_EXPECTED_COLUMNS = {
    "id",
    "kb_id",
    "owner_id",
    "title",
    "content",
    "include_in_wiki_search",
    "tags",
    "created_at",
    "updated_at",
}


def _manual_knowledge_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(manual_knowledge)").fetchall()}


def _seed_pre_0016(db_path: Path) -> None:
    """Build a versioned DB at 0015 with no manual_knowledge table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS manual_knowledge"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0015_chunk_last_edited_at')"))
    finally:
        sync_engine.dispose()


async def test_migration_0016_creates_manual_knowledge_table(tmp_path: Path) -> None:
    """RED: the upgrade creates manual_knowledge with the P6 column set."""
    db_path = tmp_path / "legacy.db"
    _seed_pre_0016(db_path)
    assert _manual_knowledge_columns(db_path) == set()

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert _manual_knowledge_columns(db_path) == _EXPECTED_COLUMNS
        with sqlite3.connect(db_path) as raw:
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == "0016_manual_knowledge_table"
    finally:
        await close_engine()


async def test_migration_0016_downgrade_drops_table(tmp_path: Path) -> None:
    """RED: downgrade to 0015 drops the table; upgrade head restores it."""
    db_path = tmp_path / "fresh.db"
    _seed_pre_0016(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition: migrations from 0015 to head created the table.
        assert _manual_knowledge_columns(db_path) == _EXPECTED_COLUMNS
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0015_chunk_last_edited_at")

    assert _manual_knowledge_columns(db_path) == set()

    # And back up — the table returns (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert _manual_knowledge_columns(db_path) == _EXPECTED_COLUMNS
