"""Add closure_tickets, closure_ticket_events, closure_sla_configs tables.

Revision ID: 002
Revises: 001
Create Date: 2026-05-19
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


_DEFAULT_SLAS = (
    ("urgent", 4),
    ("important", 72),
    ("normal", 7 * 24),
    ("observe", 30 * 24),
)


def upgrade() -> None:
    op.create_table(
        "closure_tickets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("assignee_id", sa.String(length=64), nullable=True),
        sa.Column("verifier_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("source_thread_id", sa.String(length=64), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_overdue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_run_id",
            "device_id",
            name="uq_closure_tickets_source",
        ),
    )
    op.create_index("ix_closure_tickets_tenant_status", "closure_tickets", ["tenant_id", "status"])
    op.create_index(
        "ix_closure_tickets_tenant_device_status",
        "closure_tickets",
        ["tenant_id", "device_id", "status"],
    )
    op.create_index(
        "ix_closure_tickets_tenant_due",
        "closure_tickets",
        ["tenant_id", "due_at", "is_overdue"],
    )
    op.create_index(
        "ix_closure_tickets_tenant_assignee",
        "closure_tickets",
        ["tenant_id", "assignee_id"],
    )
    op.create_index(
        "ix_closure_tickets_tenant_creator",
        "closure_tickets",
        ["tenant_id", "created_by"],
    )

    op.create_table(
        "closure_ticket_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ticket_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_closure_events_ticket_created",
        "closure_ticket_events",
        ["ticket_id", "created_at"],
    )
    op.create_index(
        "ix_closure_events_tenant_action",
        "closure_ticket_events",
        ["tenant_id", "action"],
    )

    sla_table = op.create_table(
        "closure_sla_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "priority", name="uq_closure_sla_tenant_priority"),
    )

    now = datetime.now(UTC)
    op.bulk_insert(
        sla_table,
        [
            {
                "id": f"default-{priority}",
                "tenant_id": "__default__",
                "priority": priority,
                "sla_hours": hours,
                "updated_by": None,
                "created_at": now,
                "updated_at": now,
            }
            for priority, hours in _DEFAULT_SLAS
        ],
    )


def downgrade() -> None:
    op.drop_table("closure_sla_configs")
    op.drop_index("ix_closure_events_tenant_action", table_name="closure_ticket_events")
    op.drop_index("ix_closure_events_ticket_created", table_name="closure_ticket_events")
    op.drop_table("closure_ticket_events")
    op.drop_index("ix_closure_tickets_tenant_creator", table_name="closure_tickets")
    op.drop_index("ix_closure_tickets_tenant_assignee", table_name="closure_tickets")
    op.drop_index("ix_closure_tickets_tenant_due", table_name="closure_tickets")
    op.drop_index("ix_closure_tickets_tenant_device_status", table_name="closure_tickets")
    op.drop_index("ix_closure_tickets_tenant_status", table_name="closure_tickets")
    op.drop_table("closure_tickets")
