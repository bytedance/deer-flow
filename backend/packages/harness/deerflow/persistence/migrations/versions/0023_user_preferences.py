"""Persist browser-safe user preferences independently by key."""

import sqlalchemy as sa
from alembic import op

revision = "0023_user_preferences"
down_revision = "0022_scheduled_occurrence_seq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy bootstrap and create_all-based recovery may already have the table.
    if sa.inspect(op.get_bind()).has_table("user_preferences"):
        return
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("user_preferences"):
        op.drop_table("user_preferences")
