"""Separate per-workspace read clocks without rewriting native markers."""

import sqlalchemy as sa
from alembic import op

revision = "0038_workspace_read_clocks"
down_revision = "0037_project_visibility"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_thread_read_versions",
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", name="pk_workspace_thread_read_versions"),
    )


def downgrade():
    raise RuntimeError("Workspace read clocks require a matched backup generation; destructive downgrade is refused")
