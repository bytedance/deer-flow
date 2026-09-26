"""deployment-level managed subagents.

Revision ID: 0014_managed_subagents
Revises: 0013_mcp_task_notifications
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_managed_subagents"
down_revision: str | Sequence[str] | None = "0013_mcp_task_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("managed_subagents"):
        return
    op.create_table(
        "managed_subagents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("managed_subagents"):
        op.drop_table("managed_subagents")
