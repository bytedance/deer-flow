"""Conversation schedules, occurrence verdicts and durable self-stop requests.

Revision ID: 0029_scheduler_agent_tasks
Revises: 0028_parked_attempts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0029_scheduler_agent_tasks"
down_revision: str | Sequence[str] | None = "0028_parked_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> dict[str, list[sa.Column]]:
    return {
        "runs": [sa.Column("goal_verdict", sa.JSON(), nullable=True)],
        "scheduled_task_runs": [
            sa.Column("goal_objective", sa.Text(), nullable=True),
            sa.Column("goal_verdict", sa.JSON(), nullable=True),
            sa.Column("stop_requested_run_id", sa.String(64), nullable=True),
        ],
        "scheduled_tasks": [
            sa.Column("origin_thread_id", sa.String(64), nullable=True),
            sa.Column("goal_objective", sa.Text(), nullable=True),
            sa.Column("max_runs", sa.Integer(), nullable=True),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("standing_notes", sa.JSON(), nullable=True),
        ],
    }


_INDEX = "ix_scheduled_tasks_origin_thread_id"


def upgrade() -> None:
    for table, columns in _columns().items():
        for column in columns:
            safe_add_column(table, column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scheduled_tasks")}
    if _INDEX not in indexes:
        op.create_index(_INDEX, "scheduled_tasks", ["origin_thread_id"])


def downgrade() -> None:
    # The rollback binary recognizes failed but cannot interpret unmet.
    op.execute(sa.text("UPDATE scheduled_task_runs SET status = 'failed' WHERE status = 'unmet'"))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scheduled_tasks")}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name="scheduled_tasks")
    for table, columns in reversed(tuple(_columns().items())):
        for column in reversed(columns):
            safe_drop_column(table, column.name)
