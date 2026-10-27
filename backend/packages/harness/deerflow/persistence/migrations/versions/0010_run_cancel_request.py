"""durable cross-worker run cancellation requests.

Revision ID: 0010_run_cancel_request
Revises: 0009_webhook_dedupe
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0010_run_cancel_request"
down_revision: str | Sequence[str] | None = "0009_webhook_dedupe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(
        "runs",
        sa.Column("cancel_action", sa.String(length=20), nullable=True),
    )
    safe_add_column(
        "runs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("runs", "cancel_requested_at")
    safe_drop_column("runs", "cancel_action")
