"""Add workflow event timeline table.

Revision ID: 0004_workflow_events
Revises: 0003_workflows
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_workflow_events"
down_revision: str | Sequence[str] | None = "0003_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("workflow_events"):
        return
    op.create_table(
        "workflow_events",
        sa.Column("workflow_event_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_ns", sa.String(length=256), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=True),
        sa.Column("run_event_seq", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("source_event_ref", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.workflow_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workflow_event_id"),
        sa.UniqueConstraint("workflow_id", "seq", name="uq_workflow_events_workflow_seq"),
    )
    with op.batch_alter_table("workflow_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflow_events_category"), ["category"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflow_events_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflow_events_event_type"), ["event_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflow_events_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflow_events_thread_id"), ["thread_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflow_events_workflow_id"), ["workflow_id"], unique=False)
        batch_op.create_index("ix_workflow_events_thread_run_seq", ["thread_id", "run_id", "run_event_seq"], unique=False)
        batch_op.create_index("ix_workflow_events_workflow_created", ["workflow_id", "created_at"], unique=False)


def downgrade() -> None:
    if not _table_exists("workflow_events"):
        return
    with op.batch_alter_table("workflow_events", schema=None) as batch_op:
        batch_op.drop_index("ix_workflow_events_workflow_created")
        batch_op.drop_index("ix_workflow_events_thread_run_seq")
        batch_op.drop_index(batch_op.f("ix_workflow_events_workflow_id"))
        batch_op.drop_index(batch_op.f("ix_workflow_events_thread_id"))
        batch_op.drop_index(batch_op.f("ix_workflow_events_run_id"))
        batch_op.drop_index(batch_op.f("ix_workflow_events_event_type"))
        batch_op.drop_index(batch_op.f("ix_workflow_events_created_at"))
        batch_op.drop_index(batch_op.f("ix_workflow_events_category"))
    op.drop_table("workflow_events")
