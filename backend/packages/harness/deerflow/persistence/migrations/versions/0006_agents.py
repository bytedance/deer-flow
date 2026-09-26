"""agents.

Revision ID: 0006_agents
Revises: 0005_run_stop_reason
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agents"
down_revision: str | Sequence[str] | None = "0005_run_stop_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agents"):
        # Idempotent: a DB whose full-metadata create_all already provisioned
        # the table (e.g. legacy test seeds) must not have it re-created here.
        return
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        # No server_default: matches the ORM's Python-side ``default=""`` (the
        # store always supplies soul on insert), keeping create_all and the
        # migration byte-identical (test_create_all_and_alembic_upgrade...).
        sa.Column("soul", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_agents_user_name"),
    )
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.create_index("ix_agents_user_id", ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index("ix_agents_user_id")
    op.drop_table("agents")
