"""Regression test for GitHub issue #3682.

End-to-end shape:

1. Hand-build a SQLite DB that mirrors a real pre-#3658 deployment -- the
   ``runs`` table is missing the ``token_usage_by_model`` column, mirroring
   what every existing user's DB looked like after the upgrade that triggered
   the issue.
2. Run ``init_engine`` (the entry point used by the FastAPI Gateway
   lifespan), which now routes through ``bootstrap_schema``.
3. Confirm a real ``SELECT`` against the column succeeds, demonstrating the
   500 from the original issue is gone.

The pre-fix codepath would have raised
``sqlalchemy.exc.OperationalError: no such column: runs.token_usage_by_model``
on step 3.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.run import RunRepository

pytestmark = pytest.mark.asyncio


def _seed_pre_3658_database(db_path: Path) -> None:
    """Build a DB that looks like a pre-PR-#3658 deployment.

    Uses the synchronous ``sqlite3`` driver so the seed is independent of the
    async engine under test.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Easiest way to get the legacy shape exactly right: create_all then
    # ALTER away the new column.
    sync_url = f"sqlite:///{db_path.as_posix()}"
    sync_engine = sa.create_engine(sync_url)
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            conn.execute(sa.text("ALTER TABLE runs DROP COLUMN token_usage_by_model"))
    finally:
        sync_engine.dispose()


async def test_legacy_database_recovers_token_usage_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _seed_pre_3658_database(db_path)

    # Sanity: confirm we did indeed land in the buggy pre-fix shape before
    # init_engine touches the file.
    with sqlite3.connect(db_path) as raw:
        cols = {row[1] for row in raw.execute("PRAGMA table_info(runs)").fetchall()}
        assert "run_id" in cols
        assert "token_usage_by_model" not in cols
        version_table_count = raw.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone()[0]
        assert version_table_count == 0

    # Run the same init_engine path FastAPI lifespan uses on startup.
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))

    try:
        # The column must now be present.
        with sqlite3.connect(db_path) as raw:
            cols = {row[1] for row in raw.execute("PRAGMA table_info(runs)").fetchall()}
            assert "token_usage_by_model" in cols
            version_row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version_row[0] == "0003_scheduled_tasks"

        # And the read path that originally 500'd must now succeed.
        sf = get_session_factory()
        assert sf is not None
        repo = RunRepository(sf)
        # No rows yet -- the point is just that the SELECT does not raise
        # ``no such column: runs.token_usage_by_model``.
        result = await repo.aggregate_tokens_by_thread(thread_id=str(uuid4()))
        assert result["total_tokens"] == 0
        assert result["by_model"] == {}
    finally:
        await close_engine()


async def test_legacy_database_with_manual_alter_still_bootstraps(tmp_path: Path) -> None:
    """User-side workaround scenario: someone already applied the manual
    ``ALTER TABLE runs ADD COLUMN token_usage_by_model JSON`` from the issue
    write-up. The hybrid bootstrap must just stamp head, not double-add the
    column, and not error.
    """
    db_path = tmp_path / "manual_altered.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        # Don't strip the column -- this is the "user already ran the
        # workaround" case where create_all already produced it.
    finally:
        sync_engine.dispose()

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        with sqlite3.connect(db_path) as raw:
            cols = [row[1] for row in raw.execute("PRAGMA table_info(runs)").fetchall()]
            # No duplicate column -- list, not set, to catch dupes.
            assert cols.count("token_usage_by_model") == 1
            version_row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version_row[0] == "0003_scheduled_tasks"
    finally:
        await close_engine()
