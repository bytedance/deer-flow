"""Add partial unique index to enforce at most one active run per thread.

Revision ID: 0004_one_active_run_per_thread
Revises: 0003_scheduled_tasks
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import _inspector

revision: str = "0004_one_active_run_per_thread"
down_revision: str | Sequence[str] | None = "0003_scheduled_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_one_active_run_per_thread"


def _index_exists() -> bool:
    insp = _inspector()
    if "runs" not in insp.get_table_names():
        return True  # nothing to add/drop
    for idx in insp.get_indexes("runs"):
        if idx.get("name") == INDEX_NAME:
            return True
    return False


def upgrade() -> None:
    if _index_exists():
        return

    bind = op.get_bind()
    dialect_name = bind.dialect.name

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
