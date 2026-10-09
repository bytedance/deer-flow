"""Version the existing private execution ledger without modifying records."""

import sqlalchemy as sa
from alembic import op

revision = "e0001_execution_ledger"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ecs_execution_jobs"):
        op.create_table(
            "ecs_execution_jobs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("namespace", sa.String(64), nullable=False),
            sa.Column("request_key", sa.String(128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("record", sa.JSON(), nullable=False),
            sa.UniqueConstraint("namespace", "request_key", name="uq_ecs_execution_request"),
        )
        op.create_index("ix_ecs_execution_jobs_state", "ecs_execution_jobs", ["state"])
    if not inspector.has_table("ecs_execution_nodes"):
        op.create_table("ecs_execution_nodes", sa.Column("id", sa.String(64), primary_key=True), sa.Column("record", sa.JSON(), nullable=False))
    if not inspector.has_table("ecs_native_affinities"):
        op.create_table(
            "ecs_native_affinities",
            sa.Column("user_id", sa.String(255), primary_key=True),
            sa.Column("thread_id", sa.String(255), primary_key=True),
            sa.Column("incarnation", sa.String(255), primary_key=True),
            sa.Column("node_id", sa.String(64), nullable=False),
        )


def downgrade():
    raise RuntimeError("Executor rollback requires drained physical execution and a coherent backup; reservations cannot be dropped")
