"""Add fencing tokens to notification delivery claims.

Revision ID: 0030_notification_claim_tokens
Revises: 0029_scheduler_agent_tasks
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0030_notification_claim_tokens"
down_revision: str | Sequence[str] | None = "0029_scheduler_agent_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("notification_deliveries", sa.Column("claim_token", sa.String(length=64), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("notification_deliveries", "claim_token")
