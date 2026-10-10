"""Fence inbound dedupe cleanup to its admission generation.

Revision ID: 0040_webhook_claim_tokens
Revises: 0039_user_disabled
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0040_webhook_claim_tokens"
down_revision: str | Sequence[str] | None = "0039_user_disabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("webhook_deliveries", sa.Column("claim_token", sa.String(length=32), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("webhook_deliveries", "claim_token")
