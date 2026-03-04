"""Add provider/model toggle sync fields to user_model_preferences.

Revision ID: 004
Revises: 003
Create Date: 2026-03-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_model_preferences",
        sa.Column(
            "provider_enabled",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "user_model_preferences",
        sa.Column(
            "enabled_models",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Drop defaults after backfill to avoid future implicit DB defaults.
    op.alter_column("user_model_preferences", "provider_enabled", server_default=None)
    op.alter_column("user_model_preferences", "enabled_models", server_default=None)


def downgrade() -> None:
    op.drop_column("user_model_preferences", "enabled_models")
    op.drop_column("user_model_preferences", "provider_enabled")

