"""Preserve server-owned thread execution routing independently of runs."""

import sqlalchemy as sa
from alembic import op

revision = "0018_thread_execution_bindings"
down_revision = "0017_personal_access_tokens"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("thread_execution_bindings"):
        return
    op.create_table(
        "thread_execution_bindings",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("backend", sa.String(64), nullable=False),
        sa.Column("parent_thread_id", sa.String(64)),
        sa.Column("source_workspace", sa.JSON()),
        sa.Column("recovery_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    raise RuntimeError("Legacy execution rollback requires drained writers and a coherent backup; preserved intent must not be deleted")
