"""Preserve nullable evidence snapshots in durable batch results."""

from __future__ import annotations

import sqlalchemy as sa

revision = "0032_batch_result_artifact"
down_revision = "0031_scheduled_streak_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("subagent_batch_items", sa.Column("result_artifact", sa.JSON(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("subagent_batch_items", "result_artifact")
