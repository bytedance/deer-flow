"""KB usability sprint baseline columns.

Revision ID: 003
Revises: 002
Create Date: 2026-05-19

Adds 4 nullable / default-backed columns required by the
2026-05-19 knowledge-base usability sprint:

* knowledge_base_documents.index_queued_at  (DateTime, nullable)
* knowledge_bases.embedding_model           (String(128), nullable)
* knowledge_bases.embedding_dim             (Integer, default 0)
* knowledge_bases.vector_metric_stale       (Boolean, default false)

All columns are additive and downgrade-safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_base_documents", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("index_queued_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("knowledge_bases", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("embedding_model", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "vector_metric_stale",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_bases", recreate="auto") as batch_op:
        batch_op.drop_column("vector_metric_stale")
        batch_op.drop_column("embedding_dim")
        batch_op.drop_column("embedding_model")

    with op.batch_alter_table("knowledge_base_documents", recreate="auto") as batch_op:
        batch_op.drop_column("index_queued_at")
