"""Persist native batch recovery policy and pre-dispatch attempt identity.

Revision ID: 0053_batch_recovery
Revises: 0052_batch_continuation
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_batch_recovery"
down_revision = "0052_batch_continuation"
branch_labels = None
depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("subagent_batches", sa.Column("recovery_policy", sa.String(24), nullable=True))
    safe_add_column("subagent_batch_items", sa.Column("attempt_id", sa.String(64), nullable=True))
    safe_add_column("subagent_batch_items", sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("subagent_batches")}
    if "recovery_policy" in columns and bind.execute(sa.text("SELECT 1 FROM subagent_batches WHERE recovery_policy = 'conservative' AND status IN ('queued', 'running', 'paused') LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while conservative batches remain active; stop workers and resolve or cancel them first")
    if bind.execute(sa.text("SELECT 1 FROM subagent_batch_items WHERE status = 'outcome_unknown' LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while batch outcomes remain unknown")
    safe_drop_column("subagent_batch_items", "dispatch_started_at")
    safe_drop_column("subagent_batch_items", "attempt_id")
    safe_drop_column("subagent_batches", "recovery_policy")
