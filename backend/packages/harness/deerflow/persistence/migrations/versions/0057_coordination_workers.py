"""Bind coordination tasks to worker threads and native runs."""

import sqlalchemy as sa
from alembic import op

revision = "0057_coordination_workers"
down_revision = "0056_coordination_task_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("coord_assignments"):
        op.create_table(
            "coord_assignments",
            sa.Column("task_id", sa.String(64), sa.ForeignKey("coord_tasks.id"), primary_key=True),
            sa.Column("epoch", sa.BigInteger(), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False, unique=True),
            sa.Column("assistant_id", sa.String(128), nullable=False),
        )
    if not inspector.has_table("coord_executions"):
        op.create_table(
            "coord_executions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("task_id", sa.String(64), nullable=False),
            sa.Column("epoch", sa.BigInteger(), nullable=False),
            sa.Column("turn", sa.BigInteger(), nullable=False),
            sa.Column("resume_key", sa.String(200)),
            sa.Column("covered_seq", sa.BigInteger(), nullable=False),
            sa.Column("frozen_input", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("run_id", sa.String(64), unique=True),
            sa.ForeignKeyConstraint(["task_id", "epoch"], ["coord_assignments.task_id", "coord_assignments.epoch"]),
            sa.UniqueConstraint("task_id", "turn", name="uq_coord_execution_turn"),
            sa.UniqueConstraint("task_id", "resume_key", name="uq_coord_execution_resume"),
        )

    if not inspector.has_table("coord_artifacts"):
        op.create_table(
            "coord_artifacts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("execution_id", sa.String(64), sa.ForeignKey("coord_executions.id"), nullable=False),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size", sa.BigInteger(), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
        )
    if "ix_coord_artifacts_execution_id" not in {idx["name"] for idx in inspector.get_indexes("coord_artifacts")}:
        op.create_index("ix_coord_artifacts_execution_id", "coord_artifacts", ["execution_id"])


def downgrade() -> None:
    for table in ("coord_artifacts", "coord_executions", "coord_assignments"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
