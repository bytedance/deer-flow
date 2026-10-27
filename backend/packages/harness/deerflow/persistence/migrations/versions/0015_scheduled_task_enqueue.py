"""Durable scheduled-task enqueue state.

Revision ID: 0015_scheduled_task_enqueue
Revises: 0014_managed_subagents
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_scheduled_task_enqueue"
down_revision: str | Sequence[str] | None = "0014_managed_subagents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_active_index(*, statuses: str) -> None:
    bind = op.get_bind()
    existing = {index["name"] for index in sa.inspect(bind).get_indexes("scheduled_task_runs")}
    with op.batch_alter_table("scheduled_task_runs", schema=None) as batch_op:
        if "uq_scheduled_task_run_active" in existing:
            batch_op.drop_index("uq_scheduled_task_run_active")
        predicate = sa.text(f"status IN ({statuses})")
        batch_op.create_index(
            "uq_scheduled_task_run_active",
            ["task_id"],
            unique=True,
            sqlite_where=predicate,
            postgresql_where=predicate,
        )


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    # Before this revision, ``queued`` was a transient pre-launch marker and
    # startup interrupted crash leftovers.  Durable enqueue gives the same
    # value a new meaning, so preserve the old restart behavior at the upgrade
    # boundary instead of launching an occurrence that may already have run.
    op.execute(
        sa.text("UPDATE scheduled_task_runs SET status = 'interrupted', error = 'interrupted: gateway upgraded before the queued run reached a terminal state', finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP) WHERE status = 'queued'")
    )
    safe_add_column(
        "scheduled_task_runs",
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
    )
    safe_add_column(
        "scheduled_task_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    safe_add_column(
        "scheduled_task_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _replace_active_index(statuses="'queued', 'launching', 'running'")
    op.execute(sa.text("UPDATE scheduled_tasks SET overlap_policy = 'enqueue' WHERE overlap_policy = 'skip'"))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    # A deployment must not leave a status unknown to the old scheduler.
    op.execute(sa.text("UPDATE scheduled_task_runs SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL WHERE status = 'launching'"))
    op.execute(sa.text("UPDATE scheduled_tasks SET overlap_policy = 'skip' WHERE overlap_policy = 'enqueue'"))
    _replace_active_index(statuses="'queued', 'running'")
    safe_drop_column("scheduled_task_runs", "attempt_count")
    safe_drop_column("scheduled_task_runs", "lease_expires_at")
    safe_drop_column("scheduled_task_runs", "lease_owner")
