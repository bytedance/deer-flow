"""Regression test for migration ``0003_scheduled_tasks``'s idempotency guard.

Revision ``0003_scheduled_tasks`` creates BOTH ``scheduled_tasks`` and
``scheduled_task_runs`` in one ``upgrade()``, but its re-entry guard used to
check only the first table:

    if inspector.has_table("scheduled_tasks"):
        return

On a DB that atypically already has ``scheduled_tasks`` but not its sibling
``scheduled_task_runs`` -- a partial restore, manual DB surgery, or legacy
provisioning that only ever created the first table -- the guard returns
early and silently skips creating ``scheduled_task_runs``. ``alembic_version``
still advances past ``0003`` (and on to head), so there is no error and no
retry path: the gap is permanent once triggered, not transient. The next code
path that touches ``scheduled_task_runs`` (e.g.
``ScheduledTaskRunRepository.count_active_runs()``) then 500s with
``OperationalError: no such table: scheduled_task_runs``.

Reaching this requires the atypical prior state described above. The ordinary
empty-DB and legacy-DB bootstrap branches (``persistence/bootstrap.py``) both
provision ``scheduled_tasks`` and ``scheduled_task_runs`` atomically via
``Base.metadata.create_all``, so a normal fresh install or upgrade never hits
the asymmetric state this test seeds.

End-to-end shape (mirrors ``test_migration_0004_run_ownership_dedupe.py``):

1. Hand-build a SQLite DB at revision ``0002_runs_token_usage`` where
   ``scheduled_tasks`` already exists but ``scheduled_task_runs`` does not.
2. Run ``init_engine`` (the FastAPI lifespan entry point), which routes
   through ``bootstrap_schema`` -> the versioned branch -> ``alembic upgrade
   head`` -> ``0003.upgrade()`` (the revision under test) -> ``0004.upgrade()``.
3. Verify ``scheduled_task_runs`` now exists, ``alembic_version`` reached
   head, and the real repository method succeeds instead of raising.

Two companion tests pin the cases the fix must not regress: the ordinary path
(neither table exists) still creates both, and the fully-idempotent path
(both already exist, e.g. via the hybrid bootstrap's atomic ``create_all``)
still no-ops cleanly with no ``table ... already exists`` error.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa

import deerflow.persistence.models  # noqa: F401  -- registers ORM models
from deerflow.persistence.base import Base
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository

pytestmark = pytest.mark.asyncio

HEAD = "0004_run_ownership"
PRE_0003_REVISION = "0002_runs_token_usage"


def _stamp_alembic_version(conn: sa.Connection, revision: str) -> None:
    conn.execute(sa.text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
    conn.execute(sa.text("DELETE FROM alembic_version"))
    conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": revision})


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as raw:
        return {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _alembic_version(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as raw:
        row = raw.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None


def _seed_pre_0003_with_only_scheduled_tasks(db_path: Path) -> None:
    """Build a DB at revision 0002 where ``scheduled_tasks`` exists but
    ``scheduled_task_runs`` does not -- the atypical prior state that trips
    the 0003 guard gap.

    ``Base.metadata.create_all`` renders the full *current* schema (every
    table across every revision, since the ORM models are the living source
    of truth), so we build that and then drop just ``scheduled_task_runs``,
    landing on exactly the asymmetric state the bug targets. Revision 0004's
    own idempotent checks (``safe_add_column`` / the ``ix_runs_lease`` guard)
    no-op harmlessly when later replayed against a create_all-rendered
    ``runs`` table, so leaving ``runs`` at its full current shape does not
    interfere with reproducing the 0003 bug.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE scheduled_task_runs"))
            # Stamp at 0002 so bootstrap takes the versioned branch and
            # replays 0003 (the revision under test) then 0004 during
            # ``alembic upgrade head``.
            _stamp_alembic_version(conn, PRE_0003_REVISION)
    finally:
        sync_engine.dispose()


def _seed_pre_0003_with_neither_scheduled_table(db_path: Path) -> None:
    """Build an ordinary DB at revision 0002: neither scheduled-task table
    exists yet, matching a real deployment that has never run 0003."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE scheduled_task_runs"))
            conn.execute(sa.text("DROP TABLE scheduled_tasks"))
            _stamp_alembic_version(conn, PRE_0003_REVISION)
    finally:
        sync_engine.dispose()


def _seed_pre_0003_with_both_scheduled_tables(db_path: Path) -> None:
    """Build a DB at revision 0002 where BOTH scheduled-task tables already
    exist -- the fully-idempotent case (e.g. the hybrid bootstrap's legacy
    branch already provisioned them atomically via ``create_all``)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(sync_engine)
        with sync_engine.begin() as conn:
            _stamp_alembic_version(conn, PRE_0003_REVISION)
    finally:
        sync_engine.dispose()


async def test_scheduled_task_runs_created_when_only_scheduled_tasks_preexists(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.db"
    _seed_pre_0003_with_only_scheduled_tasks(db_path)

    # Sanity: confirm we landed in the atypical pre-fix shape before
    # init_engine touches the file.
    tables_before = _table_names(db_path)
    assert "scheduled_tasks" in tables_before
    assert "scheduled_task_runs" not in tables_before
    assert _alembic_version(db_path) == PRE_0003_REVISION

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))

    try:
        tables_after = _table_names(db_path)

        # The guard gap in 0003 checked only ``scheduled_tasks`` before
        # returning early, silently skipping ``scheduled_task_runs``. Both
        # tables are owned by the SAME revision, so both must exist once
        # alembic_version has advanced past it.
        assert "scheduled_task_runs" in tables_after, "0003_scheduled_tasks guard skipped creating scheduled_task_runs when scheduled_tasks already existed"
        # alembic still advances to head regardless -- the gap is silent,
        # not a raised error, which is what makes it a permanent gap rather
        # than something a second "restart" upgrade-head would self-heal.
        assert _alembic_version(db_path) == HEAD

        # Real repository call, not just schema inspection: must not raise
        # ``sqlalchemy.exc.OperationalError: no such table: scheduled_task_runs``.
        sf = get_session_factory()
        assert sf is not None
        repo = ScheduledTaskRunRepository(sf)
        count = await repo.count_active_runs()
        assert count == 0
    finally:
        await close_engine()


async def test_neither_scheduled_table_exists_both_created_normally(tmp_path: Path) -> None:
    """Ordinary-path guard: a real DB at 0002 (neither scheduled table
    present) must still get BOTH tables from a single upgrade head. The fix
    must not regress the common case."""
    db_path = tmp_path / "neither.db"
    _seed_pre_0003_with_neither_scheduled_table(db_path)

    tables_before = _table_names(db_path)
    assert "scheduled_tasks" not in tables_before
    assert "scheduled_task_runs" not in tables_before

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        tables_after = _table_names(db_path)
        assert "scheduled_tasks" in tables_after
        assert "scheduled_task_runs" in tables_after
        assert _alembic_version(db_path) == HEAD
    finally:
        await close_engine()


async def test_both_scheduled_tables_already_exist_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    """Fully-idempotent case: both tables already exist (e.g. the hybrid
    bootstrap's legacy branch already provisioned them atomically). Upgrade
    head must no-op cleanly -- no ``OperationalError: table ... already
    exists``."""
    db_path = tmp_path / "both.db"
    _seed_pre_0003_with_both_scheduled_tables(db_path)

    tables_before = _table_names(db_path)
    assert "scheduled_tasks" in tables_before
    assert "scheduled_task_runs" in tables_before

    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    # Must not raise (e.g. "table scheduled_tasks already exists").
    await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        tables_after = _table_names(db_path)
        assert "scheduled_tasks" in tables_after
        assert "scheduled_task_runs" in tables_after
        assert _alembic_version(db_path) == HEAD
    finally:
        await close_engine()
