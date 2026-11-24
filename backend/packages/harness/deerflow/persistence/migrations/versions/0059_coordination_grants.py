"""Persist revocable Task-scoped runtime authority."""

import sqlalchemy as sa
from alembic import op

revision = "0059_coordination_grants"
down_revision = "0058_mcp_browser_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("coord_task_grants"):
        op.create_table(
            "coord_task_grants",
            sa.Column("task_id", sa.String(64), sa.ForeignKey("coord_tasks.id"), primary_key=True),
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("authority", sa.JSON(), nullable=False),
            sa.Column("channel", sa.JSON(), nullable=True),
            sa.Column("expires_at", sa.Double(), nullable=False),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("coord_task_grants"):
        op.drop_table("coord_task_grants")
