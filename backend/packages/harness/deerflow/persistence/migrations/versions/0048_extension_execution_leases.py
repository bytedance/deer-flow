"""Generic extension execution fences.

Revision ID: 0048_extension_execution_leases
Revises: 0047_mcp_oauth_tokens
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_extension_execution_leases"
down_revision = "0047_mcp_oauth_tokens"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("extension_execution_leases"):
        op.create_table(
            "extension_execution_leases",
            sa.Column("namespace", sa.String(96), primary_key=True),
            sa.Column("resource_id", sa.String(128), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("holder_id", sa.String(128), nullable=False),
            sa.Column("epoch", sa.BigInteger(), nullable=False),
            sa.Column("expires_at", sa.Double(), nullable=False),
        )


def downgrade():
    op.drop_table("extension_execution_leases")
