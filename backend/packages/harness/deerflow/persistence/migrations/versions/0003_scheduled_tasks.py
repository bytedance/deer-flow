"""scheduled tasks.

Revision ID: 0003_scheduled_tasks
Revises: 0002_runs_token_usage
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_scheduled_tasks"
down_revision: str | Sequence[str] | None = "0002_runs_token_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("scheduled_tasks"):
        # Idempotent: a DB whose full-metadata create_all already provisioned
        # both scheduled-task tables (e.g. legacy test seeds) must not have them
        # re-created here.
        return
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("context_mode", sa.String(length=32), nullable=False),
        sa.Column("assistant_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("schedule_type", sa.String(length=16), nullable=False),
        sa.Column("schedule_spec", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("overlap_policy", sa.String(length=16), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(length=64), nullable=True),
        sa.Column("last_thread_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scheduled_tasks", schema=None) as batch_op:
        batch_op.create_index("ix_scheduled_tasks_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_scheduled_tasks_thread_id", ["thread_id"], unique=False)
        batch_op.create_index("ix_scheduled_tasks_status", ["status"], unique=False)
        batch_op.create_index("ix_scheduled_tasks_next_run_at", ["next_run_at"], unique=False)

    op.create_table(
        "scheduled_task_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scheduled_task_runs", schema=None) as batch_op:
        batch_op.create_index("ix_scheduled_task_runs_task_id", ["task_id"], unique=False)
        batch_op.create_index("ix_scheduled_task_runs_thread_id", ["thread_id"], unique=False)
        batch_op.create_index("ix_scheduled_task_runs_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("scheduled_task_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_scheduled_task_runs_status")
        batch_op.drop_index("ix_scheduled_task_runs_thread_id")
        batch_op.drop_index("ix_scheduled_task_runs_task_id")
    op.drop_table("scheduled_task_runs")

    with op.batch_alter_table("scheduled_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_scheduled_tasks_next_run_at")
        batch_op.drop_index("ix_scheduled_tasks_status")
        batch_op.drop_index("ix_scheduled_tasks_thread_id")
        batch_op.drop_index("ix_scheduled_tasks_user_id")
    op.drop_table("scheduled_tasks")
