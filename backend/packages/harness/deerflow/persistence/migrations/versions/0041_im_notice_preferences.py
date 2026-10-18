"""Shared IM notification preferences, including local synthetic owners.

Revision ID: 0041_im_notice_preferences
Revises: 0040_scheduled_group_notice
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_im_notice_preferences"
down_revision = "0040_scheduled_group_notice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("im_notification_preferences"):
        op.create_table(
            "im_notification_preferences",
            sa.Column("owner_user_id", sa.String(64), primary_key=True),
            sa.Column("provider", sa.String(32), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("im_notification_preferences"):
        op.drop_table("im_notification_preferences")
