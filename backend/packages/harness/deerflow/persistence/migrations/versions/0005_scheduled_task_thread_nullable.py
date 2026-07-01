"""scheduled task thread nullable.

Revision ID: 0005_scheduled_task_thread_nullable
Revises: 0004_scheduled_task_context_mode
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_scheduled_task_thread_nullable"
down_revision: str | Sequence[str] | None = "0004_scheduled_task_context_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "thread_id",
            existing_type=sa.String(length=64),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "thread_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
