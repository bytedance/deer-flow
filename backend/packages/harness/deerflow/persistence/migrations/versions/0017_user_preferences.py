"""Add durable user-level UI preferences.

Revision ID: 0017_user_preferences
Revises: 0016_subagent_batches
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0017_user_preferences"
down_revision: str | Sequence[str] | None = "0016_subagent_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("users", sa.Column("preferences", sa.JSON(), nullable=True))
    safe_add_column(
        "users",
        sa.Column(
            "preferences_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("users", "preferences_revision")
    safe_drop_column("users", "preferences")
