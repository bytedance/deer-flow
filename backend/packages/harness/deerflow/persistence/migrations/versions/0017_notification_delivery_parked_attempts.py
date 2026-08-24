"""Add parked_attempts counter for notification delivery parking cap.

Revision ID: 0017_parked_attempts
Revises: 0016_notification_deliveries
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_parked_attempts"
down_revision: str | Sequence[str] | None = "0016_notification_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("notification_deliveries"):
        return
    columns = {col["name"] for col in inspector.get_columns("notification_deliveries")}
    if "parked_attempts" not in columns:
        # Temporary server_default backfills existing rows. Dropped below so
        # the durable schema matches create_all (ORM Python-side default=0).
        with op.batch_alter_table("notification_deliveries") as batch:
            batch.add_column(
                sa.Column("parked_attempts", sa.Integer(), nullable=False, server_default="0"),
            )
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.alter_column(
            "parked_attempts",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
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
