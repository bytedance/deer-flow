"""Add workflow frontdoor envelope table.

Revision ID: 0003_workflows
Revises: 0002_runs_token_usage
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_workflows"
down_revision: str | Sequence[str] | None = "0002_runs_token_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("workflows"):
        return
    op.create_table(
        "workflows",
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("external_message_ref", sa.Text(), nullable=True),
        sa.Column("conversation_ref", sa.Text(), nullable=True),
        sa.Column("thread_ref", sa.Text(), nullable=True),
        sa.Column("sender_ref", sa.Text(), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_ns", sa.String(length=256), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflows_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_status"), ["status"], unique=False)
        batch_op.create_index("ix_workflows_claimable", ["status", "next_attempt_at", "lease_expires_at"], unique=False)
        batch_op.create_index("ix_workflows_status_updated", ["status", "updated_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_thread_id"), ["thread_id"], unique=False)
        batch_op.create_index("ix_workflows_thread_run", ["thread_id", "run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            "uq_workflows_source_idempotency",
            ["source_type", "source", "idempotency_key"],
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )


def downgrade() -> None:
    if not _table_exists("workflows"):
        return
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.drop_index("uq_workflows_source_idempotency")
        batch_op.drop_index(batch_op.f("ix_workflows_user_id"))
        batch_op.drop_index("ix_workflows_thread_run")
        batch_op.drop_index(batch_op.f("ix_workflows_thread_id"))
        batch_op.drop_index("ix_workflows_status_updated")
        batch_op.drop_index("ix_workflows_claimable")
        batch_op.drop_index(batch_op.f("ix_workflows_status"))
        batch_op.drop_index(batch_op.f("ix_workflows_source"))
        batch_op.drop_index(batch_op.f("ix_workflows_run_id"))
    op.drop_table("workflows")
