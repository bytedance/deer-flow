"""project_documents shelf table (Projects Phase 2 Slice B).

Revision ID: 0024_project_documents
Revises: 0023_user_preferences
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_project_documents"
down_revision: str | Sequence[str] | None = "0023_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project_documents"):
        op.create_table(
            "project_documents",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("stored_relpath", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("source_thread_id", sa.String(length=64), nullable=True),
            sa.Column("source_kind", sa.String(length=16), nullable=True),
            sa.Column("source_name", sa.String(length=255), nullable=True),
            sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trash_origin", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_project_documents_project_id", "project_documents", ["project_id"])
        op.create_index("ix_project_documents_user_id", "project_documents", ["user_id"])
        op.create_index("ix_project_documents_sha256", "project_documents", ["sha256"])
        op.create_index("ix_project_documents_trashed_at", "project_documents", ["trashed_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("project_documents"):
        op.drop_index("ix_project_documents_trashed_at", table_name="project_documents")
        op.drop_index("ix_project_documents_sha256", table_name="project_documents")
        op.drop_index("ix_project_documents_user_id", table_name="project_documents")
        op.drop_index("ix_project_documents_project_id", table_name="project_documents")
        op.drop_table("project_documents")
