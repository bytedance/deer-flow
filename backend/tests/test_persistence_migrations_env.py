"""Tests for the ``include_object`` filter used by ``migrations/env.py``.

LangGraph checkpointer tables (``checkpoints`` and friends) live alongside
DeerFlow's own tables in the same database. Alembic must NEVER emit DDL for
them or a future ``alembic revision --autogenerate`` would propose
``drop_table('checkpoints')`` whenever LangGraph's tables are reflected from
a live DB.

The filter is the only line of defence between an honest autogenerate run
and a destructive revision. It lives in ``_env_filters.py`` so it can be unit
tested without alembic's import-time machinery.
"""

from __future__ import annotations

import sqlalchemy as sa

from deerflow.persistence.migrations._env_filters import (
    LANGGRAPH_OWNED_TABLES,
    include_object,
)


def _table(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData())


def test_filter_excludes_langgraph_checkpoint_tables() -> None:
    for owned in (
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    ):
        assert include_object(_table(owned), owned, "table", True, None) is False


def test_filter_includes_deerflow_tables() -> None:
    for owned in ("runs", "threads_meta", "feedback", "users", "channel_connections"):
        assert include_object(_table(owned), owned, "table", True, None) is True


def test_filter_excludes_indexes_on_langgraph_tables() -> None:
    # An Index whose parent table is LangGraph-owned must also be filtered out;
    # otherwise autogenerate would emit drop_index against tables alembic does
    # not own.
    md = sa.MetaData()
    parent = sa.Table("checkpoints", md, sa.Column("id", sa.Integer, primary_key=True))
    idx = sa.Index("ix_checkpoints_anything", parent.c.id)
    assert include_object(idx, idx.name, "index", True, None) is False


def test_filter_includes_indexes_on_deerflow_tables() -> None:
    md = sa.MetaData()
    parent = sa.Table("runs", md, sa.Column("run_id", sa.String, primary_key=True))
    idx = sa.Index("ix_runs_something", parent.c.run_id)
    assert include_object(idx, idx.name, "index", True, None) is True


def test_langgraph_owned_tables_set_is_complete() -> None:
    # Pin the explicit set so an inadvertent removal -- e.g. someone simplifying
    # the filter -- requires a test diff that surfaces the change.
    assert LANGGRAPH_OWNED_TABLES == frozenset(
        {
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
            "checkpoint_migrations",
        }
    )


def test_env_module_wires_busy_timeout_for_sqlite() -> None:
    """Regression for the cross-process bootstrap pitfall: alembic spawns its
    own engine inside ``env.py::run_migrations_online`` and that engine does
    NOT inherit PRAGMAs from the production engine. Without an event listener
    here, its connections would use the default 5s busy_timeout and racy
    multi-process bootstrap would fail with ``database is locked`` instead of
    waiting for the file lock.

    We check the source rather than execute env.py (which would try to drive
    alembic on import) so this test stays a pure parity check.
    """
    from pathlib import Path  # noqa: PLC0415

    env_path = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/persistence/migrations/env.py"
    src = env_path.read_text(encoding="utf-8")
    assert "PRAGMA busy_timeout=30000" in src or "PRAGMA busy_timeout = 30000" in src, (
        "env.py must set busy_timeout on its alembic-spawned engine; without it, cross-process bootstrap on SQLite fails fast instead of waiting for the file lock"
    )
    assert 'listens_for(connectable.sync_engine, "connect")' in src, "busy_timeout must be wired via an event listener so EVERY connection alembic opens gets the PRAGMA, not just one initial probe"
