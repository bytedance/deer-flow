"""Regression test for migration ``0004_run_ownership`` dedupe pass.

End-to-end shape:

1. Hand-build a SQLite DB that mirrors a real pre-0004 deployment that ran
   ``GATEWAY_WORKERS>1`` before this PR and accumulated duplicate active rows
   per thread (the exact dirty state the multi-worker ownership fix targets).
2. Stamp it at ``0003_scheduled_tasks`` so ``bootstrap_schema`` takes the
   versioned branch and runs ``alembic upgrade head``.
3. Insert two+ pending/running rows for the same ``thread_id`` (only possible
   because the partial unique index does not exist yet).
4. Run ``init_engine`` (the FastAPI lifespan entry point), which routes
   through ``bootstrap_schema`` → ``upgrade head`` → ``0004.upgrade()``.
5. Verify the migration cancelled the superseded duplicates (set them to
   ``error`` with an explanatory message), kept the newest active row, and
   successfully built the ``uq_runs_thread_active`` partial unique index.

Pre-fix codepath would have raised ``UNIQUE constraint failed`` (SQLite) /
``could not create unique index`` (Postgres) on step 5, aborting the alembic
upgrade and blocking gateway startup.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.engine import close_engine, init_engine
from deerflow.persistence.run.model import RunRow

pytestmark = pytest.mark.asyncio


def _seed_pre_0004_with_duplicates(db_path: Path) -> None:
    """Build a DB at revision 0003 with duplicate active rows per thread.

    Uses a synchronous engine so the seed is independent of the async engine
    under test. ``Base.metadata.create_all`` produces the full current schema
    (including the partial unique index), so we drop just the unique index to
    land in the dirty state the migration's dedupe pass targets: a versioned
    DB at 0003 where duplicate active rows per thread can coexist. We then
    stamp at 0003 and insert the duplicates via the ORM (so Python-side
    defaults populate).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            # Drop only the partial unique index — this is the invariant the
            # migration rebuilds, and its absence is what permits duplicate
            # active rows to exist in the first place.
            conn.execute(sa.text("DROP INDEX IF EXISTS uq_runs_thread_active"))
            # Stamp at 0003 so bootstrap takes the versioned branch and runs
            # ``alembic upgrade head`` (which is what executes 0004.upgrade()).
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("DELETE FROM alembic_version"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0003_scheduled_tasks')"))

        base = datetime.now(UTC)
        with Session(sync_engine) as session:
            session.add_all(
                [
                    RunRow(
                        run_id="run-old-a",
                        thread_id="thread-dup",
                        status="pending",
                        created_at=base,
                        updated_at=base,
                    ),
                    RunRow(
                        run_id="run-old-b",
                        thread_id="thread-dup",
                        status="running",
                        created_at=base + timedelta(seconds=10),
                        updated_at=base + timedelta(seconds=10),
                    ),
                    RunRow(
                        run_id="run-newest",
                        thread_id="thread-dup",
                        status="pending",
                        created_at=base + timedelta(seconds=60),
                        updated_at=base + timedelta(seconds=60),
                    ),
                    RunRow(
                        run_id="run-solo",
                        thread_id="thread-solo",
                        status="running",
                        created_at=base,
                        updated_at=base,
                    ),
                    RunRow(
                        run_id="run-success",
                        thread_id="thread-done",
                        status="success",
                        created_at=base,
                        updated_at=base,
                    ),
                ]
            )
            session.commit()
    finally:
        sync_engine.dispose()


def _fetch_runs(db_path: Path) -> dict[str, tuple[str, str | None]]:
    """Map run_id -> (status, error) for assertions."""
    with sqlite3.connect(db_path) as raw:
        rows = raw.execute("SELECT run_id, status, error FROM runs").fetchall()
    return {run_id: (status, error) for run_id, status, error in rows}


def _index_exists(db_path: Path, index_name: str) -> bool:
    with sqlite3.connect(db_path) as raw:
        row = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
    return row is not None


async def test_migration_dedupes_duplicate_active_rows_before_unique_index(tmp_path: Path) -> None:
    db_path = tmp_path / "dirty.db"
    _seed_pre_0004_with_duplicates(db_path)

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))

    try:
        runs = _fetch_runs(db_path)

        # Newest active row on the duplicated thread survives unchanged.
        assert runs["run-newest"] == ("pending", None)

        # Older duplicate active rows are cancelled with an explanatory error.
        assert runs["run-old-a"][0] == "error"
        assert "uq_runs_thread_active" in (runs["run-old-a"][1] or "")
        assert runs["run-old-b"][0] == "error"
        assert "uq_runs_thread_active" in (runs["run-old-b"][1] or "")

        # Untouched threads: single active row stays active, terminal rows stay terminal.
        assert runs["run-solo"] == ("running", None)
        assert runs["run-success"] == ("success", None)

        # The partial unique index was successfully created — the upgrade did
        # not abort with ``UNIQUE constraint failed``.
        assert _index_exists(db_path, "uq_runs_thread_active")
        assert _index_exists(db_path, "ix_runs_lease")

        with sqlite3.connect(db_path) as raw:
            version_row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version_row[0] == "0004_run_ownership"

        # Sanity: the invariant the index enforces is now true — at most one
        # active row per thread.
        with sqlite3.connect(db_path) as raw:
            dupes = raw.execute("SELECT thread_id, COUNT(*) FROM runs WHERE status IN ('pending', 'running') GROUP BY thread_id HAVING COUNT(*) > 1").fetchall()
        assert dupes == []
    finally:
        await close_engine()
