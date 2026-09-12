"""conversation share quotas (#4548).

Revision ID: 0025_conversation_share_quotas
Revises: 0024_conversation_shares
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_conversation_share_quotas"
down_revision: str | Sequence[str] | None = "0024_conversation_shares"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("conversation_share_quotas"):
        op.create_table(
            "conversation_share_quotas",
            sa.Column("owner_user_id", sa.String(length=64), nullable=False),
            sa.Column("stored_shares", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("owner_user_id"),
        )
    # Backfill the admission counter from rows that predate it — and keep
    # running it on migration retries: an interrupted upgrade can leave the
    # table created but the revision unstamped, and a backfill that only ran
    # with the table's creation would skip permanently, letting affected
    # owners exceed the cap by their legacy row count. ON CONFLICT DO
    # NOTHING keeps owners whose counter is already live (a completed
    # backfill or post-migration admissions) untouched.
    op.execute("INSERT INTO conversation_share_quotas (owner_user_id, stored_shares) SELECT owner_user_id, COUNT(*) FROM conversation_shares GROUP BY owner_user_id ON CONFLICT (owner_user_id) DO NOTHING")
    indexes = {index["name"] for index in inspector.get_indexes("conversation_shares")}
    if "ix_conversation_shares_owner_user_id" not in indexes:
        # The per-owner quota count runs on every creation.
        op.create_index("ix_conversation_shares_owner_user_id", "conversation_shares", ["owner_user_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("conversation_shares")}
    if "ix_conversation_shares_owner_user_id" in indexes:
        op.drop_index("ix_conversation_shares_owner_user_id", table_name="conversation_shares")
    if inspector.has_table("conversation_share_quotas"):
        op.drop_table("conversation_share_quotas")
