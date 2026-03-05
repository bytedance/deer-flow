"""Add S3 artifact sync columns to threads table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column("s3_sync_status", sa.String(16), nullable=False, server_default="none"),
    )
    op.add_column(
        "threads",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "threads",
        sa.Column("local_evicted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("idx_threads_s3_sync_status", "threads", ["s3_sync_status"])
    op.create_index("idx_threads_last_accessed_at", "threads", ["last_accessed_at"])


def downgrade() -> None:
    op.drop_index("idx_threads_last_accessed_at", table_name="threads")
    op.drop_index("idx_threads_s3_sync_status", table_name="threads")
    op.drop_column("threads", "local_evicted")
    op.drop_column("threads", "last_accessed_at")
    op.drop_column("threads", "s3_sync_status")
