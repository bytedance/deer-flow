"""Carry the triggering trace parent through scheduled run admission."""

import sqlalchemy as sa

revision = "0053_scheduled_traceparent"
down_revision = "0052_batch_continuation"
branch_labels = None
depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("scheduled_task_runs", sa.Column("traceparent", sa.String(55), nullable=True))


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("scheduled_task_runs", "traceparent")
