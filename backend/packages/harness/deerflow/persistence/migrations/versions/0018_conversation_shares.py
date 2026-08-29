"""conversation shares (#4548).

Revision ID: 0018_conversation_shares
Revises: 0017_personal_access_tokens
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_conversation_shares"
down_revision: str | Sequence[str] | None = "0017_personal_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("conversation_shares"):
        op.create_table(
            "conversation_shares",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("owner_user_id", sa.String(length=64), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("snapshot_version", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("source_last_seq", sa.BigInteger(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_conversation_shares_thread_id", "conversation_shares", ["thread_id"])
        op.create_index("ix_conversation_shares_token_hash", "conversation_shares", ["token_hash"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("conversation_shares"):
        op.drop_index("ix_conversation_shares_token_hash", table_name="conversation_shares")
        op.drop_index("ix_conversation_shares_thread_id", table_name="conversation_shares")
        op.drop_table("conversation_shares")
