"""Store runtime grants for MCP agent credential bindings."""

import sqlalchemy as sa
from alembic import op

revision = "0062_mcp_agent_grants"
down_revision = "0061_coordination_coordinator"
branch_labels = None
depends_on = None

_TABLE = "mcp_agent_grants"


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("binding_id", sa.String(128), primary_key=True),
            sa.Column("grant", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)
