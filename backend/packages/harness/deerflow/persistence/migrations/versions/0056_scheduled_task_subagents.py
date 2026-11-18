"""Persist whether each scheduled task enables subagents."""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0056_scheduled_task_subagents"
down_revision = "0055_thread_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    safe_add_column("scheduled_tasks", sa.Column("subagent_enabled", sa.Boolean(), nullable=True))


def downgrade() -> None:
    safe_drop_column("scheduled_tasks", "subagent_enabled")
