"""Persist the original channel binding of a coordination task."""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0064_coordination_channel_origin"
down_revision = "0063_scheduled_task_subagents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    safe_add_column("coord_tasks", sa.Column("channel_origin", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    safe_drop_column("coord_tasks", "channel_origin")
