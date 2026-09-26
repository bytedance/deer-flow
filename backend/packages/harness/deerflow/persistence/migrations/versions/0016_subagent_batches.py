"""durable native-subagent batches.

Revision ID: 0016_subagent_batches
Revises: 0015_scheduled_task_enqueue
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_subagent_batches"
down_revision: str | Sequence[str] | None = "0015_scheduled_task_enqueue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("subagent_batches"):
        op.create_table(
            "subagent_batches",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("tool_call_id", sa.String(length=128), nullable=True),
            sa.Column("submission_key", sa.String(length=256), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("subagent_type", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("total_items", sa.Integer(), nullable=False),
            sa.Column("max_live_items", sa.Integer(), nullable=False),
            sa.Column("max_running_items", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("execution_spec", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "submission_key", name="uq_subagent_batches_user_submission"),
        )
        op.create_index("ix_subagent_batches_user_id", "subagent_batches", ["user_id"])
        op.create_index("ix_subagent_batches_thread_id", "subagent_batches", ["thread_id"])
        op.create_index("ix_subagent_batches_status", "subagent_batches", ["status"])
        op.create_index("ix_subagent_batches_thread_created", "subagent_batches", ["thread_id", "created_at"])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("subagent_batch_items"):
        op.create_table(
            "subagent_batch_items",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("batch_id", sa.String(length=64), nullable=False),
            sa.Column("item_key", sa.String(length=128), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("lease_owner", sa.String(length=128), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("result_preview", sa.Text(), nullable=True),
            sa.Column("result_truncated", sa.Boolean(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("stop_reason", sa.String(length=64), nullable=True),
            sa.Column("token_usage", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["batch_id"], ["subagent_batches.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("batch_id", "item_key", name="uq_subagent_batch_items_key"),
            sa.UniqueConstraint("batch_id", "position", name="uq_subagent_batch_items_position"),
        )
        op.create_index("ix_subagent_batch_items_batch_id", "subagent_batch_items", ["batch_id"])
        op.create_index("ix_subagent_batch_items_status", "subagent_batch_items", ["status"])
        op.create_index(
            "ix_subagent_batch_items_claim",
            "subagent_batch_items",
            ["status", "lease_expires_at", "batch_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("subagent_batch_items"):
        op.drop_table("subagent_batch_items")
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("subagent_batches"):
        op.drop_table("subagent_batches")
