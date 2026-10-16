"""Persist original MCP workspace authority without upgrading old tasks."""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column

revision = "0040_mcp_workspace_identity"
down_revision = "0039_run_workspace_identity"
branch_labels = None
depends_on = None


def upgrade():
    safe_add_column("mcp_tasks", sa.Column("workspace_context_json", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("MCP workspace authority requires restoring a matched backup generation")
