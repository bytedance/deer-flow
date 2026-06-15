"""Add memory_audit table

Revision ID: 004
Revises: 003
Create Date: 2026-05-26

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("layer", sa.String(16), nullable=False),
        sa.Column("fact_id", sa.String(128), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_audit_tenant_id", "memory_audit", ["tenant_id"])
    op.create_index("ix_memory_audit_user_id", "memory_audit", ["user_id"])
    op.create_index("ix_audit_tenant_layer", "memory_audit", ["tenant_id", "layer"])
    op.create_index("ix_audit_user_action", "memory_audit", ["user_id", "action"])
    op.create_index("ix_audit_created", "memory_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_created", table_name="memory_audit")
    op.drop_index("ix_audit_user_action", table_name="memory_audit")
    op.drop_index("ix_audit_tenant_layer", table_name="memory_audit")
    op.drop_index("ix_memory_audit_user_id", table_name="memory_audit")
    op.drop_index("ix_memory_audit_tenant_id", table_name="memory_audit")
    op.drop_table("memory_audit")
