"""Add the unmet-streak boundary and the stop condition to scheduled tasks.

Revision ID: 0031_scheduled_streak_boundary
Revises: 0030_notification_claim_tokens
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0031_scheduled_streak_boundary"
down_revision: str | Sequence[str] | None = "0030_notification_claim_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    # Occurrences at or below this sequence never count toward the automatic
    # pause streak. NULL means no boundary (every existing row).
    safe_add_column("scheduled_tasks", sa.Column("unmet_streak_after_seq", sa.BigInteger(), nullable=True))
    # The user's normalized "stop when ..." rule. NULL means none.
    safe_add_column("scheduled_tasks", sa.Column("stop_condition", sa.Text(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("scheduled_tasks", "stop_condition")
    safe_drop_column("scheduled_tasks", "unmet_streak_after_seq")
