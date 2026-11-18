"""Add independent coordination tasks and durable ordered input."""

import sqlalchemy as sa
from alembic import op

revision = "0056_coordination_task_state"
down_revision = "0055_thread_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("coord_tasks"):
        op.create_table(
            "coord_tasks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("owner_id", sa.String(64), nullable=False),
            sa.Column("request_id", sa.String(200), nullable=False),
            sa.Column("project_id", sa.String(64)),
            sa.Column("root_id", sa.String(64), nullable=False),
            sa.Column("parent_id", sa.String(64), sa.ForeignKey("coord_tasks.id")),
            sa.Column("depends_on", sa.JSON(), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("revision", sa.BigInteger(), nullable=False),
            sa.Column("execution_epoch", sa.BigInteger(), nullable=False),
            sa.Column("latest_input_seq", sa.BigInteger(), nullable=False),
            sa.Column("result_ref", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("owner_id", "request_id", name="uq_coord_task_request"),
        )
    # A non-transactional SQLite upgrade can be interrupted between DDL steps.
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("coord_tasks")}
    if "ix_coord_tasks_owner_root" not in indexes:
        op.create_index("ix_coord_tasks_owner_root", "coord_tasks", ["owner_id", "root_id"])
    if "ix_coord_tasks_owner_parent" not in indexes:
        op.create_index("ix_coord_tasks_owner_parent", "coord_tasks", ["owner_id", "parent_id"])
    if not sa.inspect(op.get_bind()).has_table("coord_inputs"):
        op.create_table(
            "coord_inputs",
            sa.Column("task_id", sa.String(64), sa.ForeignKey("coord_tasks.id"), primary_key=True),
            sa.Column("sequence", sa.BigInteger(), primary_key=True),
            sa.Column("request_id", sa.String(200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("task_id", "request_id", name="uq_coord_input_request"),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("coord_inputs"):
        op.drop_table("coord_inputs")
    if sa.inspect(op.get_bind()).has_table("coord_tasks"):
        op.drop_table("coord_tasks")
