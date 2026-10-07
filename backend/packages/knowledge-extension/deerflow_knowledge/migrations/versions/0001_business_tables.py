"""Business tables: kb_knowledge_bases, kb_documents, kb_chunks.

The extension's chain root. Column shapes are the fork's 0011 tables with the
0012 (documents.path_status), 0013 (documents.content_hash), 0015
(chunks.last_edited_at) and 0019 (knowledge_bases.embedding_identity) columns
inlined (D3), renamed under the extension-owned ``kb_`` prefix (D2).

Revision ID: 0001_business_tables
Revises:
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_business_tables"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_knowledge_bases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding_identity", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("kb_knowledge_bases", schema=None) as batch_op:
        batch_op.create_index("ix_kb_knowledge_bases_owner_id", ["owner_id"], unique=False)

    op.create_table(
        "kb_documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kb_id", sa.String(length=64), nullable=False),
        sa.Column("uploader_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("path_status", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("kb_documents", schema=None) as batch_op:
        batch_op.create_index("ix_kb_documents_kb_id", ["kb_id"], unique=False)
        batch_op.create_index("ix_kb_documents_status", ["status"], unique=False)

    op.create_table(
        "kb_chunks",
        sa.Column("chunk_id", sa.String(length=160), nullable=False),
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("kb_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("extract_status", sa.String(length=16), nullable=False),
        sa.Column("extract_error", sa.Text(), nullable=True),
        sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    with op.batch_alter_table("kb_chunks", schema=None) as batch_op:
        batch_op.create_index("ix_kb_chunks_doc_id", ["doc_id"], unique=False)
        batch_op.create_index("ix_kb_chunks_extract_status", ["extract_status"], unique=False)
        batch_op.create_index("ix_kb_chunks_kb_id", ["kb_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("kb_chunks", schema=None) as batch_op:
        batch_op.drop_index("ix_kb_chunks_kb_id")
        batch_op.drop_index("ix_kb_chunks_extract_status")
        batch_op.drop_index("ix_kb_chunks_doc_id")
    op.drop_table("kb_chunks")

    with op.batch_alter_table("kb_documents", schema=None) as batch_op:
        batch_op.drop_index("ix_kb_documents_status")
        batch_op.drop_index("ix_kb_documents_kb_id")
    op.drop_table("kb_documents")

    with op.batch_alter_table("kb_knowledge_bases", schema=None) as batch_op:
        batch_op.drop_index("ix_kb_knowledge_bases_owner_id")
    op.drop_table("kb_knowledge_bases")
