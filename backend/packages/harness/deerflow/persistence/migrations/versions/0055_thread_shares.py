"""Add immutable conversation shares and copied artifact bytes."""

import sqlalchemy as sa
from alembic import op

revision = "0055_thread_shares"
down_revision = "0054_project_memory"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("thread_shares"):
        op.create_table(
            "thread_shares",
            sa.Column("share_id", sa.String(32), primary_key=True),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("thread_id", sa.String(64), sa.ForeignKey("threads_meta.thread_id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_id", sa.String(64), nullable=False),
            sa.Column("incarnation", sa.String(32)),
            sa.Column("checkpoint_id", sa.String(128), nullable=False),
            sa.Column("seq", sa.BigInteger(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_thread_shares_owner_thread", "thread_shares", ["owner_id", "thread_id"])
    if not sa.inspect(op.get_bind()).has_table("share_artifacts"):
        op.create_table(
            "share_artifacts",
            sa.Column("share_id", sa.String(32), sa.ForeignKey("thread_shares.share_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("path", sa.String(1024), primary_key=True),
            sa.Column("mime_type", sa.String(128), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size", sa.BigInteger(), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
        )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("share_artifacts"):
        op.drop_table("share_artifacts")
    if sa.inspect(op.get_bind()).has_table("thread_shares"):
        op.drop_table("thread_shares")
