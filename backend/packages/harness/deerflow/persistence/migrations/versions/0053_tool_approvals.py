"""tool approval decisions and thread grants

Revision ID: 0053_tool_approvals
Revises: 0052_batch_continuation
Create Date: 2026-11-08 23:35:15.929868

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0053_tool_approvals"
down_revision: str | Sequence[str] | None = "0052_batch_continuation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    if not sa.inspect(op.get_bind()).has_table("tool_approvals"):
        op.create_table(
            "tool_approvals",
            sa.Column("request_id", sa.String(length=96), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("incarnation", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("decision", sa.String(length=24), nullable=True),
            sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
            sa.Column("response", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("created_at", sa.Double(), nullable=False),
            sa.Column("expires_at", sa.Double(), nullable=True),
            sa.PrimaryKeyConstraint("request_id"),
        )
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("tool_approvals")}
    for name, columns in (
        ("ix_tool_approvals_run", ["run_id", "status"]),
        ("ix_tool_approvals_scope", ["user_id", "thread_id", "incarnation", "fingerprint"]),
    ):
        if name not in existing:
            op.create_index(name, "tool_approvals", columns, unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if not sa.inspect(op.get_bind()).has_table("tool_approvals"):
        return
    op.drop_table("tool_approvals")
