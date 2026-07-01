"""scheduled task context mode.

Revision ID: 0004_scheduled_task_context_mode
Revises: 0003_scheduled_tasks
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0004_scheduled_task_context_mode"
down_revision: str | Sequence[str] | None = "0003_scheduled_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "scheduled_tasks",
        sa.Column(
            "context_mode",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'fresh_thread_per_run'"),
        ),
    )
    safe_add_column(
        "scheduled_tasks",
        sa.Column(
            "last_thread_id",
            sa.String(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    safe_drop_column("scheduled_tasks", "last_thread_id")
    safe_drop_column("scheduled_tasks", "context_mode")
