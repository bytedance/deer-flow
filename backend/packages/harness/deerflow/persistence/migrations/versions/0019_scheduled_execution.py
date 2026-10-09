"""Persist public scheduled execution intent."""

import sqlalchemy as sa

revision = "0019_scheduled_execution"
down_revision = "0018_thread_execution_bindings"
branch_labels = None
depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("scheduled_tasks", sa.Column("execution", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Legacy execution rollback requires drained writers and a coherent backup; preserved intent must not be deleted")
