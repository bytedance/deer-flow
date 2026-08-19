"""Add parked_attempts counter for notification delivery parking cap.

Revision ID: 0014_notification_delivery_parked_attempts
Revises: 0013_notification_deliveries
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_notification_delivery_parked_attempts"
down_revision: str | Sequence[str] | None = "0013_notification_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("notification_deliveries"):
        return
    columns = {col["name"] for col in inspector.get_columns("notification_deliveries")}
    if "parked_attempts" in columns:
        return
    op.add_column(
        "notification_deliveries",
        sa.Column("parked_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("notification_deliveries"):
        return
    columns = {col["name"] for col in inspector.get_columns("notification_deliveries")}
    if "parked_attempts" not in columns:
        return
    op.drop_column("notification_deliveries", "parked_attempts")
