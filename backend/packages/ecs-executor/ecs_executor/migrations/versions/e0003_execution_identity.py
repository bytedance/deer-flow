"""Append immutable execution intent storage without inventing historical grants."""

import sqlalchemy as sa
from alembic import op

revision = "e0003_execution_identity"
down_revision = "e0002_workspace_scope"
branch_labels = None
depends_on = None


def upgrade():
    if "execution_identity" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ecs_execution_jobs")}:
        op.add_column("ecs_execution_jobs", sa.Column("execution_identity", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Execution identity rollback requires drained physical execution and coherent backups; identity cannot be dropped")
