"""feedback tags.

Revision ID: 0008_feedback_tags
Revises: 0007_scheduled_run_active_index
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_feedback_tags"
down_revision: str | Sequence[str] | None = "0007_scheduled_run_active_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("feedback")}
    if "tags" in columns:
        # Idempotent: a DB whose full-metadata create_all already provisioned
        # the column must not have it re-added here.
        return
    op.add_column("feedback", sa.Column("tags", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "tags")
