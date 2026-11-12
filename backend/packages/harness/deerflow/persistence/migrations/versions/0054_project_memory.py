"""Add bounded project memory; existing projects start with an empty pool."""

import sqlalchemy as sa

revision = "0054_project_memory"
down_revision = "0053_tool_approvals"
branch_labels = None
depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("projects", sa.Column("memory", sa.JSON(), nullable=True))


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("projects", "memory")
