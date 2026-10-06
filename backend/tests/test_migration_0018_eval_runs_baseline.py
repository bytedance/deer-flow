"""Migration ``0018_eval_runs_baseline``: eval_runs.is_baseline + environment.

RAG evaluation metrics visualization (spec 2026-08-24 §3.1.1/§3.1.3, plan
Task 0c): adds the baseline marker (at most one per KB, backstopped by the
partial unique index ``uq_eval_runs_kb_baseline``) and the environment column
(``local`` / ``ci`` / ``nightly``) that keeps CI runs out of the default
latest/trend read sets.

Shape:
1. Hand-build a SQLite DB at revision 0017 without the two columns / index.
2. Run init_engine -> bootstrap_schema -> alembic upgrade head.
3. Both columns exist, the legacy row is backfilled (``is_baseline=0``,
   ``environment='local'``), and the partial unique index exists.
4. downgrade back to 0017 drops columns + index; upgrade head restores them.
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

_BASELINE_INDEX = "uq_eval_runs_kb_baseline"


def _eval_run_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as raw:
        return {row[1] for row in raw.execute("PRAGMA table_info(eval_runs)").fetchall()}


def _baseline_index_sql(db_path: Path) -> str | None:
    """The partial unique index's persisted CREATE INDEX statement, if present."""
    with sqlite3.connect(db_path) as raw:
        row = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (_BASELINE_INDEX,),
        ).fetchone()
        return row[0] if row else None


def _seed_pre_0018(db_path: Path) -> None:
    """Build a versioned DB at 0017 with one eval_runs row and no 0018 columns.

    The current ORM model already carries the 0018 columns + partial unique
    index, so the seed rolls eval_runs back to its 0017 shape before stamping.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            conn.execute(sa.text(f"DROP INDEX IF EXISTS {_BASELINE_INDEX}"))
            cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(eval_runs)"))}
            for column in ("is_baseline", "environment"):
                if column in cols:
                    conn.execute(sa.text(f"ALTER TABLE eval_runs DROP COLUMN {column}"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0017_eval_runs_table')"))
            conn.execute(sa.text("INSERT INTO eval_runs (id, kb_id, status, layer1_metrics, layer2_metrics, created_at) VALUES ('run-legacy', 'kb-1', 'completed', '{}', '{}', '2026-08-24 10:00:00+00:00')"))
    finally:
        sync_engine.dispose()


async def test_migration_0018_adds_columns_backfills_and_creates_index(tmp_path: Path) -> None:
    """upgrade head adds both columns, backfills legacy rows, creates the index."""
    db_path = tmp_path / "legacy.db"
    _seed_pre_0018(db_path)
    assert "is_baseline" not in _eval_run_columns(db_path)
    assert "environment" not in _eval_run_columns(db_path)
    assert _baseline_index_sql(db_path) is None

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        assert {"is_baseline", "environment"} <= _eval_run_columns(db_path)

        with sqlite3.connect(db_path) as raw:
            is_baseline, environment = raw.execute("SELECT is_baseline, environment FROM eval_runs WHERE id = 'run-legacy'").fetchone()
            version = raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        # 存量行回填默认值（NOT NULL DEFAULT 语义）
        assert is_baseline == 0
        assert environment == "local"
        assert version == "0018_eval_runs_baseline"

        # 部分唯一索引（每 KB 至多一行 baseline）：持久化的索引定义必须带 WHERE
        sql = _baseline_index_sql(db_path)
        assert sql is not None
        assert "UNIQUE" in sql.upper()
        assert "WHERE" in sql.upper()
    finally:
        await close_engine()


async def test_migration_0018_downgrade_drops_columns_and_index(tmp_path: Path) -> None:
    """downgrade to 0017 removes columns + index; upgrade head restores them."""
    db_path = tmp_path / "fresh.db"
    _seed_pre_0018(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        # Pre-condition: migrations from 0017 to head added the 0018 schema.
        assert {"is_baseline", "environment"} <= _eval_run_columns(db_path), f"Expected columns after upgrade. Found: {_eval_run_columns(db_path)}"
        assert _baseline_index_sql(db_path) is not None
    finally:
        await close_engine()

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await asyncio.to_thread(alembic_command.downgrade, cfg, "0017_eval_runs_table")

    assert "is_baseline" not in _eval_run_columns(db_path)
    assert "environment" not in _eval_run_columns(db_path)
    assert _baseline_index_sql(db_path) is None

    # And back up — columns + index return (up/down round-trip).
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    assert {"is_baseline", "environment"} <= _eval_run_columns(db_path)
    assert _baseline_index_sql(db_path) is not None
