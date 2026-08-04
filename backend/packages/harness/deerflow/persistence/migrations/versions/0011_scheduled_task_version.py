"""add scheduled_tasks.version for optimistic concurrency

The schedule aggregate carries a `version` token that every committed write
increments and that `save` compares against, so a read-modify-write racing a
dispatch or completion is refused rather than silently rolling back the fields
those writes own (`next_run_at`, `run_count`, `last_run_id`) and re-arming an
already-executed occurrence.

Existing rows start at 0, which is also the aggregate's default, so a task read
before this migration and saved after it compares equal and commits normally.

Revision ID: 0011_scheduled_task_version
Revises: 0010_run_cancel_request
"""

from __future__ import annotations

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0011_scheduled_task_version"
down_revision = "0010_run_cancel_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    safe_add_column(
        "scheduled_tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    safe_drop_column("scheduled_tasks", "version")
