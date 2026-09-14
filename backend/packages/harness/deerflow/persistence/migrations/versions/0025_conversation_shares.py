"""conversation shares (#4548).

Revision ID: 0025_conversation_shares
Revises: 0023_user_preferences
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_conversation_shares"
down_revision: str | Sequence[str] | None = "0023_user_preferences"
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
    # Each index is checked independently of the table guard: SQLite DDL is
    # non-transactional, so an upgrade interrupted between the table's
    # creation and these calls must still create what is missing on retry —
    # otherwise the revision can be stamped with the unique token-hash
    # index permanently absent. The inspector is rebuilt after the optional
    # create_table so it observes the fresh table's (empty) index set.
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("conversation_shares")}
    if "ix_conversation_shares_thread_id" not in indexes:
        op.create_index("ix_conversation_shares_thread_id", "conversation_shares", ["thread_id"])
    if "ix_conversation_shares_token_hash" not in indexes:
        op.create_index("ix_conversation_shares_token_hash", "conversation_shares", ["token_hash"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("conversation_shares"):
        indexes = {index["name"] for index in inspector.get_indexes("conversation_shares")}
        if "ix_conversation_shares_token_hash" in indexes:
            op.drop_index("ix_conversation_shares_token_hash", table_name="conversation_shares")
        if "ix_conversation_shares_thread_id" in indexes:
            op.drop_index("ix_conversation_shares_thread_id", table_name="conversation_shares")
        op.drop_table("conversation_shares")
