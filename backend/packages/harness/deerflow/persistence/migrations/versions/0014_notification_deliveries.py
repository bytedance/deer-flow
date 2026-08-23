"""Scheduled-task notification delivery outbox (issue #4254).

Revision ID: 0014_notification_deliveries
Revises: 0013_mcp_task_notifications
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_notification_deliveries"
down_revision: str | Sequence[str] | None = "0013_mcp_task_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("notification_deliveries"):
        # Idempotent: a DB whose full-metadata create_all already provisioned
        # the table (e.g. a fresh DB) must not have it re-created here.
        return
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("task_run_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
        # Idempotency key from the issue design: one notification per
        # (task_run_id, event, provider, target), enforced at the DB layer.
        sa.UniqueConstraint(
            "task_run_id",
            "event",
            "provider",
            "target",
            name="uq_notification_delivery_run_event_target",
        ),
    )
    op.create_index("ix_notification_deliveries_task_id", "notification_deliveries", ["task_id"], unique=False)
    op.create_index("ix_notification_deliveries_task_run_id", "notification_deliveries", ["task_run_id"], unique=False)
    op.create_index("ix_notification_deliveries_owner_user_id", "notification_deliveries", ["owner_user_id"], unique=False)
    op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "available_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("notification_deliveries"):
        op.drop_index("ix_notification_deliveries_due", table_name="notification_deliveries")
        op.drop_index("ix_notification_deliveries_owner_user_id", table_name="notification_deliveries")
        op.drop_index("ix_notification_deliveries_task_run_id", table_name="notification_deliveries")
        op.drop_index("ix_notification_deliveries_task_id", table_name="notification_deliveries")
        op.drop_table("notification_deliveries")
