"""Migration ``0012_documents_path_status``: ``documents.path_status`` JSON column.

Phase-2 batch-1 P3 (spec 2026-08-11 §5): per-path sub-status
(``{"vector": ..., "graph": ...}``) persists on the document row; the wiki
leg stays a library-level mirror injected at read time.

Shape (mirrors ``test_migration_0004_run_ownership_dedupe.py``):

1. Hand-build a SQLite DB that mirrors a real pre-0012 deployment: full
   schema at revision ``0011_knowledge`` minus the ``path_status`` column,
   with one legacy document row.
2. Run ``init_engine`` → ``bootstrap_schema`` → ``alembic upgrade head`` →
   ``0012.upgrade()``.
3. The column exists, the legacy row reads ``NULL`` (old clients unaffected,
   frontend renders no hover — spec §5 兼容), and the version stamps at
   ``0012_documents_path_status``.
4. ``downgrade`` back to ``0011_knowledge`` drops the column again.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR
from deerflow.persistence.engine import close_engine, init_engine

pytestmark = pytest.mark.asyncio


def _document_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(documents)").fetchall()}


def _seed_pre_0012(db_path: Path) -> None:
    """Build a versioned DB at 0011 with one document row and no path_status.

    ``Base.metadata.create_all`` produces the full current schema (including
    ``path_status`` once the ORM declares it), so drop just that column to
    land in the legacy state the migration targets, then stamp at 0011.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(documents)")).fetchall()}
            if "path_status" in cols:
                conn.execute(sa.text("ALTER TABLE documents DROP COLUMN path_status"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0011_knowledge')"))
            conn.execute(
                sa.text(
                    "INSERT INTO documents (id, kb_id, uploader_id, name, size_bytes, storage_path, status, progress_percent, created_at)"
                    " VALUES ('doc-legacy', 'kb-1', 'user-1', 'legacy.md', 10, '/tmp/legacy.md', 'ready', 100, '2026-08-11 00:00:00+00:00')"
                )
            )
    finally:
        sync_engine.dispose()


async def test_migration_0012_adds_path_status_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _seed_pre_0012(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert "path_status" in _document_columns(db_path)

        with sqlite3.connect(db_path) as raw:
            value = raw.execute("SELECT path_status FROM documents WHERE id = 'doc-legacy'").fetchone()[0]
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        # 老行缺省 null —— 前端不展示悬停（spec §5 兼容契约）
        assert value is None
        assert version == "0012_documents_path_status"
    finally:
        await close_engine()


async def test_migration_0012_downgrade_drops_column(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition keeps the test non-vacuous: at head the column exists.
        assert "path_status" in _document_columns(db_path)
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0011_knowledge")

    assert "path_status" not in _document_columns(db_path)

    # And back up — the column returns (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert "path_status" in _document_columns(db_path)
