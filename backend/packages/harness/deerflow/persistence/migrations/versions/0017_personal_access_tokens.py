"""personal access tokens.

Revision ID: 0017_personal_access_tokens
Revises: 0016_subagent_batches
Create Date: 2026-08-26

Numbering note: generated against the then-current main head (0016), as were
the 0017 migrations in #5078 (conversation shares) and #4843 (notification
deliveries, claiming 0017+0018). Whichever merges first keeps the slot; the
others renumber on rebase — adjust ``revision``/``down_revision`` here and
the migration-head assertions in tests/test_persistence_bootstrap*.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_personal_access_tokens"
down_revision: str | Sequence[str] | None = "0016_subagent_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("personal_access_tokens"):
        op.create_table(
            "personal_access_tokens",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("token_digest", sa.String(length=64), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_personal_access_tokens_user_id", "personal_access_tokens", ["user_id"])
        op.create_index("ix_personal_access_tokens_token_digest", "personal_access_tokens", ["token_digest"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("personal_access_tokens"):
        op.drop_index("ix_personal_access_tokens_token_digest", table_name="personal_access_tokens")
        op.drop_index("ix_personal_access_tokens_user_id", table_name="personal_access_tokens")
        op.drop_table("personal_access_tokens")
