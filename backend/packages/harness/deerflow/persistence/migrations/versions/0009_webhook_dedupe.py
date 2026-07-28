"""Cross-pod inbound webhook dedupe table (issue #4120).

Revision ID: 0009_webhook_dedupe
Revises: 0008_thread_operation_kind
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_webhook_dedupe"
down_revision: str | Sequence[str] | None = "0008_thread_operation_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("webhook_deliveries"):
        # Idempotent: a DB whose full-metadata create_all already provisioned
        # the table (e.g. a fresh DB, or a legacy test seed) must not have it
        # re-created here.
        return
    op.create_table(
        "webhook_deliveries",
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=512), nullable=False),
        sa.Column("chat_id", sa.String(length=512), nullable=False),
        sa.Column("message_id", sa.String(length=1024), nullable=False),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Composite PK mirrors ChannelManager._inbound_dedupe_key exactly. A
        # single joined surrogate key is deliberately avoided: the components
        # can contain characters (e.g. NUL) that are illegal in a Postgres TEXT
        # column, and a joined key would also risk length overflow.
        sa.PrimaryKeyConstraint(
            "channel",
            "workspace_id",
            "chat_id",
            "message_id",
            name="pk_webhook_deliveries",
        ),
    )
    op.create_index("ix_webhook_deliveries_first_seen", "webhook_deliveries", ["first_seen"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("webhook_deliveries"):
        op.drop_index("ix_webhook_deliveries_first_seen", table_name="webhook_deliveries")
        op.drop_table("webhook_deliveries")
