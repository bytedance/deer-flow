"""durable long-running MCP tasks.

Revision ID: 0011_mcp_tasks
Revises: 0010_run_cancel_request
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_mcp_tasks"
down_revision: str | Sequence[str] | None = "0010_run_cancel_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("mcp_tasks"):
        return

    op.create_table(
        "mcp_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("server_name", sa.String(length=128), nullable=False),
        sa.Column("driver_name", sa.String(length=64), nullable=False),
        sa.Column("remote_task_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_required", sa.JSON(), nullable=True),
        sa.Column("driver_data", sa.JSON(), nullable=False),
        sa.Column("notification_status", sa.String(length=16), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_error", sa.Text(), nullable=True),
        sa.Column("poll_attempt_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_poll_error_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "server_name",
            "remote_task_id",
            name="uq_mcp_tasks_user_server_remote",
        ),
    )
    with op.batch_alter_table("mcp_tasks", schema=None) as batch_op:
        batch_op.create_index("ix_mcp_tasks_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_mcp_tasks_thread_id", ["thread_id"], unique=False)
        batch_op.create_index("ix_mcp_tasks_status", ["status"], unique=False)
        batch_op.create_index("ix_mcp_tasks_notification_status", ["notification_status"], unique=False)
        batch_op.create_index("ix_mcp_tasks_next_poll_at", ["next_poll_at"], unique=False)
        batch_op.create_index("ix_mcp_tasks_thread_created", ["thread_id", "created_at"], unique=False)
        batch_op.create_index("ix_mcp_tasks_due", ["status", "next_poll_at"], unique=False)


def downgrade() -> None:
    op.drop_table("mcp_tasks")
