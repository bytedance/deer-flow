"""Optional native batch dependencies and completion follow-up.

Revision ID: 0052_batch_continuation
Revises: 0051_merge_run_inputs_fencing
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_batch_continuation"
down_revision = "0051_merge_run_inputs_fencing"
branch_labels = None
depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    for column in (
        sa.Column("continuation_json", sa.JSON(), nullable=True),
        sa.Column("continuation_status", sa.String(24), nullable=True),
        sa.Column("continuation_run_id", sa.String(64), nullable=True),
    ):
        safe_add_column("subagent_batches", column)
    if "ix_subagent_batches_continuation_status" not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("subagent_batches")}:
        op.create_index("ix_subagent_batches_continuation_status", "subagent_batches", ["continuation_status"])
    if "subagent_batch_dependencies" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "subagent_batch_dependencies",
            sa.Column("item_id", sa.String(64), sa.ForeignKey("subagent_batch_items.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("prerequisite_id", sa.String(64), sa.ForeignKey("subagent_batch_items.id", ondelete="CASCADE"), primary_key=True),
        )
        op.create_index("ix_subagent_batch_dependencies_prerequisite", "subagent_batch_dependencies", ["prerequisite_id"])


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    if "subagent_batch_dependencies" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("subagent_batch_dependencies")
    if "ix_subagent_batches_continuation_status" in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("subagent_batches")}:
        op.drop_index("ix_subagent_batches_continuation_status", table_name="subagent_batches")
    for name in ("continuation_json", "continuation_status", "continuation_run_id"):
        safe_drop_column("subagent_batches", name)
