"""reliable MCP task notifications and cancellation.

Revision ID: 0013_mcp_task_notifications
Revises: 0012_mcp_task_results
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_mcp_task_notifications"
down_revision: str | Sequence[str] | None = "0012_mcp_task_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_index_if_missing(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    if any(index.get("name") == name for index in inspector.get_indexes(table)):
        return
    op.create_index(name, table, columns, unique=unique)


def _drop_index_if_present(name: str, table: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    if any(index.get("name") == name for index in inspector.get_indexes(table)):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("runs", sa.Column("idempotency_key", sa.String(length=255), nullable=True))

    safe_add_column("mcp_tasks", sa.Column("event_fingerprint", sa.String(length=64), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("event_version", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("mcp_tasks", sa.Column("notified_version", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("mcp_tasks", sa.Column("dispatch_version", sa.Integer(), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("dispatch_attempt", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("mcp_tasks", sa.Column("dispatch_event", sa.JSON(), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_run_id", sa.String(length=64), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_error", sa.Text(), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("mcp_tasks", sa.Column("next_notification_at", sa.DateTime(timezone=True), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_lease_owner", sa.String(length=128), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("cancel_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("mcp_tasks", sa.Column("next_cancel_at", sa.DateTime(timezone=True), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("last_cancel_error", sa.Text(), nullable=True))

    _create_index_if_missing("uq_runs_idempotency_key", "runs", ["idempotency_key"], unique=True)
    _create_index_if_missing("ix_mcp_tasks_notification_due", "mcp_tasks", ["notification_status", "next_notification_at"])
    _create_index_if_missing("ix_mcp_tasks_cancel_due", "mcp_tasks", ["cancel_requested_at", "next_cancel_at"])

    # Terminal rows created by PR2 will never be polled again, so seed one
    # outbox version for their already-pending notification. Non-terminal rows
    # get a canonical fingerprint on their next status/error observation.
    op.execute(sa.text("UPDATE mcp_tasks SET event_version = 1, next_notification_at = updated_at WHERE status IN ('completed', 'failed', 'cancelled') AND notification_status = 'pending' AND event_version = 0"))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    _drop_index_if_present("ix_mcp_tasks_cancel_due", "mcp_tasks")
    _drop_index_if_present("ix_mcp_tasks_notification_due", "mcp_tasks")
    _drop_index_if_present("uq_runs_idempotency_key", "runs")

    for column in (
        "last_cancel_error",
        "next_cancel_at",
        "cancel_attempt_count",
        "notification_lease_expires_at",
        "notification_lease_owner",
        "next_notification_at",
        "notification_attempt_count",
        "notification_error",
        "notification_run_id",
        "dispatch_event",
        "dispatch_attempt",
        "dispatch_version",
        "notified_version",
        "event_version",
        "event_fingerprint",
    ):
        safe_drop_column("mcp_tasks", column)
    safe_drop_column("runs", "idempotency_key")
