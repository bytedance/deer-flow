"""Migration tests for 0025_repair_run_change_seq (#5516).

``0023_run_change_seq`` was inserted ahead of the already-shipped
``0023_user_preferences`` revision, so databases stamped at that revision (or
later) never executed it and permanently lack the ``run_change_clock`` table
and ``runs.change_seq`` column. 0025 re-applies the same guarded DDL on
upgrade, heals those databases, and no-ops on healthy shapes.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config, _get_head_revision
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.run import RunRepository

pytestmark = pytest.mark.asyncio

REVISION = "0025_repair_run_change_seq"
PREVIOUS = "0024_project_documents"
STAMP_BEFORE_INSERTION = "0023_user_preferences"


def _seed_database_that_skipped_0023(db_path) -> None:
    """Build the #5516 shape: stamped past 0023_run_change_seq without running it.

    Mirrors a deployment that reached ``0023_user_preferences`` before
    ``0023_run_change_seq`` was inserted ahead of it: the version row says the
    revision is applied, so alembic never runs it, and the schema it owns is
    missing. Uses the synchronous ``sqlite3``-backed engine so the seed is
    independent of the async engine under test.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            # Remove everything 0023_run_change_seq owns.
            conn.execute(sa.text("DROP INDEX IF EXISTS ix_runs_change_seq"))
            conn.execute(sa.text("DROP INDEX IF EXISTS ix_runs_user_change_seq"))
            conn.execute(sa.text("ALTER TABLE runs DROP COLUMN change_seq"))
            conn.execute(sa.text("DROP TABLE IF EXISTS run_change_clock"))
            # 0024 had not run at this stamp either.
            conn.execute(sa.text("DROP TABLE IF EXISTS project_documents"))
            # Stamp the position such a deployment sat at.
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text(f"INSERT INTO alembic_version (version_num) VALUES ('{STAMP_BEFORE_INSERTION}')"))
    finally:
        sync_engine.dispose()


def _table_and_column_state(db_path) -> tuple[bool, bool, set[str], str | None]:
    with sqlite3.connect(db_path) as raw:
        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        run_columns = {row[1] for row in raw.execute("PRAGMA table_info(runs)").fetchall()}
        run_indexes = {row[1] for row in raw.execute("PRAGMA index_list(runs)").fetchall()}
        version_row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
    return "run_change_clock" in tables, "change_seq" in run_columns, run_indexes, version_row[0] if version_row else None


async def test_0025_chains_into_the_single_head():
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    # Later migrations may advance the head without removing this revision.
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS


async def test_0025_repairs_schema_skipped_by_the_0023_insertion(tmp_path):
    db_path = tmp_path / "skipped-0023.db"
    _seed_database_that_skipped_0023(db_path)

    has_table, has_column, _, version = _table_and_column_state(db_path)
    assert not has_table
    assert not has_column
    assert version == STAMP_BEFORE_INSERTION

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        has_table, has_column, run_indexes, version = _table_and_column_state(db_path)
        assert has_table
        assert has_column
        assert {"ix_runs_change_seq", "ix_runs_user_change_seq"} <= run_indexes
        assert version == _get_head_revision()

        # The exact call that 500'd in #5516: bumping the change clock.
        sf = get_session_factory()
        assert sf is not None
        async with sf() as session:
            assert await RunRepository._next_change_seq(session) == 1
    finally:
        await close_engine()


async def test_0025_downgrade_preserves_ancestor_owned_schema_and_data(tmp_path):
    """Rolling back only this repair must not remove schema owned by 0023.

    The change-clock schema belongs to ancestor ``0023_run_change_seq``; a
    repair downgrade that dropped it would leave the database stamped at 0024
    without 0023's schema — recreating the #5516 hole — and would discard
    allocated clock positions.
    """
    db_path = tmp_path / "downgrade.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        from deerflow.persistence.engine import get_engine

        engine = get_engine()
        assert engine is not None
        cfg = _get_alembic_config(engine)

        # Allocate a clock position so the data-preservation claim is real.
        sf = get_session_factory()
        assert sf is not None
        async with sf() as session:
            assert await RunRepository._next_change_seq(session) == 1
            await session.commit()

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        has_table, has_column, run_indexes, version = _table_and_column_state(db_path)
        assert has_table
        assert has_column
        assert {"ix_runs_change_seq", "ix_runs_user_change_seq"} <= run_indexes
        assert version == PREVIOUS
        with sqlite3.connect(db_path) as raw:
            assert raw.execute("SELECT value FROM run_change_clock WHERE id = 1").fetchone()[0] == 1

        # Downgrade is idempotent; re-upgrading re-runs the guarded repair as a no-op.
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        has_table, has_column, run_indexes, version = _table_and_column_state(db_path)
        assert has_table
        assert has_column
        assert {"ix_runs_change_seq", "ix_runs_user_change_seq"} <= run_indexes
        assert version == REVISION
        with sqlite3.connect(db_path) as raw:
            assert raw.execute("SELECT value FROM run_change_clock WHERE id = 1").fetchone()[0] == 1
    finally:
        await close_engine()
