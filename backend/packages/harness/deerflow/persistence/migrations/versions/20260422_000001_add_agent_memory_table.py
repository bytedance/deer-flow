"""add agent_memory table for postgres memory backend

Revision ID: 20260422_000001
Revises:
Create Date: 2026-04-22 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_memory",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("user_id", "agent_name", name="pk_agent_memory"),
    )


def downgrade() -> None:
    op.drop_table("agent_memory")
