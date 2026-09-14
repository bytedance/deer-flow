"""Persist per-task occurrence order and idempotent launch accounting.

Revision ID: 0022_scheduled_occurrence_seq
Revises: 0019_thread_incarnations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_scheduled_occurrence_seq"
down_revision: str | Sequence[str] | None = "0019_thread_incarnations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_scheduled_task_run_occurrence_seq"


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("scheduled_tasks", sa.Column("last_occurrence_seq", sa.BigInteger(), nullable=False, server_default="0"))
    # Caller clocks cannot reconstruct the admission order or prove which
    # historical launches were counted. Preserve NULL for both legacy fields.
    safe_add_column("scheduled_task_runs", sa.Column("occurrence_seq", sa.BigInteger(), nullable=True))
    safe_add_column("scheduled_task_runs", sa.Column("launch_accounted", sa.Boolean(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scheduled_task_runs")}
    if _INDEX not in indexes:
        op.create_index(_INDEX, "scheduled_task_runs", ["task_id", "occurrence_seq"], unique=True)


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scheduled_task_runs")}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name="scheduled_task_runs")
    safe_drop_column("scheduled_task_runs", "launch_accounted")
    safe_drop_column("scheduled_task_runs", "occurrence_seq")
    safe_drop_column("scheduled_tasks", "last_occurrence_seq")
