"""Add composite index (visibility, tenant_id) on knowledge_bases table.

Revision ID: 001
Revises:
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_bases", schema=None) as batch_op:
        batch_op.create_index(
            "ix_knowledge_bases_visibility_tenant",
            ["visibility", "tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_bases", schema=None) as batch_op:
        batch_op.drop_index("ix_knowledge_bases_visibility_tenant")
