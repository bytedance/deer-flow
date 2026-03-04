"""Add user_model_preferences table for persisted model UI preferences.

Revision ID: 003
Revises: 002
Create Date: 2026-03-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_model_preferences",
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("model_name", sa.String(256), nullable=True),
        sa.Column("thinking_effort", sa.String(32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_model_preferences")

