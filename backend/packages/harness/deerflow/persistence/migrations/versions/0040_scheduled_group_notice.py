"""Add an optional Feishu group notification connection to scheduled tasks.

Revision ID: 0040_scheduled_group_notice
Revises: 0039_user_disabled

Legacy tasks keep NULL and their existing owner notifications. There is no
foreign key: disconnecting a group must retain the selected target so pending
delivery can report the loss instead of silently losing the destination.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0040_scheduled_group_notice"
down_revision: str | None = "0039_user_disabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column("scheduled_tasks", sa.Column("notification_group_connection_id", sa.String(64), nullable=True))


def downgrade() -> None:
    safe_drop_column("scheduled_tasks", "notification_group_connection_id")
