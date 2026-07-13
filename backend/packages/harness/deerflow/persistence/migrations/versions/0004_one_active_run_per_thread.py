"""Add partial unique index to enforce at most one active run per thread.

Revision ID: 0004_one_active_run_per_thread
Revises: 0003_scheduled_tasks
Create Date: 2026-07-09
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import _inspector

logger = logging.getLogger(__name__)

revision: str = "0004_one_active_run_per_thread"
down_revision: str | Sequence[str] | None = "0003_scheduled_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_one_active_run_per_thread"

_CLEANUP_ERROR = "Cleaned up during migration 0004: duplicate active runs per thread"


def _index_exists() -> bool:
    insp = _inspector()
    if "runs" not in insp.get_table_names():
        return True  # nothing to add/drop
    for idx in insp.get_indexes("runs"):
        if idx.get("name") == INDEX_NAME:
            return True
    return False


def _cleanup_duplicate_active_runs(connection, dialect_name: str) -> int:
    """Mark duplicate active runs as interrupted, keeping only the newest per thread.

    If a thread has multiple pending/running rows (e.g. from a pre-fix
    multi-worker race), the partial unique index cannot be created.  This
    helper keeps the most-recently-created active run per thread and marks
    the rest as ``interrupted``.
    """
    if dialect_name == "postgresql":
        time_expr = "NOW()"
    else:
        time_expr = "datetime('now')"

    result = connection.execute(
        sa.text(f"""
            UPDATE runs SET
                status = 'interrupted',
                error = :error,
                updated_at = {time_expr}
            WHERE run_id IN (
                SELECT run_id FROM (
                    SELECT run_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY thread_id ORDER BY created_at DESC
                        ) AS rn
                    FROM runs
                    WHERE status IN ('pending', 'running')
                ) ranked
                WHERE rn > 1
            )
        """),
        {"error": _CLEANUP_ERROR},
    )
    cleaned = result.rowcount
    if cleaned:
        logger.warning(
            "Migration 0004: cleaned up %d duplicate active run(s) before creating unique index",
            cleaned,
        )
    return cleaned


def upgrade() -> None:
    if _index_exists():
        return

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Clean up any pre-existing duplicate active runs that would prevent
    # the unique index from being created.
    _cleanup_duplicate_active_runs(bind, dialect_name)

    if dialect_name == "postgresql":
        op.create_index(
            INDEX_NAME,
            "runs",
            ["thread_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('pending', 'running')"),
        )
    else:
        # SQLite and other dialects
        op.create_index(
            INDEX_NAME,
            "runs",
            ["thread_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('pending', 'running')"),
        )


def downgrade() -> None:
    if not _index_exists():
        return
    op.drop_index(INDEX_NAME, table_name="runs")
