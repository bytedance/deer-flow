"""ORM models for the closed-loop ticket subsystem."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ClosureTicketRow(Base):
    """A single closed-loop ticket tracking remediation of a fault, work order, or report finding."""

    __tablename__ = "closure_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # State machine fields. Validated at the service layer; column type stays String for portability.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    severity: Mapped[str | None] = mapped_column(String(16))

    device_id: Mapped[str | None] = mapped_column(String(64))
    device_name: Mapped[str | None] = mapped_column(String(255))

    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(String(64))
    verifier_id: Mapped[str | None] = mapped_column(String(64))

    # Source tracing.
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    # "diagnosis" | "report" | "manual" | "chat"
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    source_thread_id: Mapped[str | None] = mapped_column(String(64))

    # Free-form payload (resolution_plan, attachments, verification_payload, etc.).
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_run_id",
            "device_id",
            name="uq_closure_tickets_source",
        ),
        Index("ix_closure_tickets_tenant_status", "tenant_id", "status"),
        Index("ix_closure_tickets_tenant_device_status", "tenant_id", "device_id", "status"),
        Index("ix_closure_tickets_tenant_due", "tenant_id", "due_at", "is_overdue"),
        Index("ix_closure_tickets_tenant_assignee", "tenant_id", "assignee_id"),
        Index("ix_closure_tickets_tenant_creator", "tenant_id", "created_by"),
    )


class ClosureTicketEventRow(Base):
    """Append-only audit log for closure ticket state transitions."""

    __tablename__ = "closure_ticket_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # "create" | "assign" | "start" | "submit_verification" | "verify_close"
    # | "reject" | "reopen" | "mark_overdue" | "update_metadata"
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_closure_events_ticket_created", "ticket_id", "created_at"),
        Index("ix_closure_events_tenant_action", "tenant_id", "action"),
    )


class ClosureSlaConfigRow(Base):
    """Per-tenant SLA duration (in hours) for each priority level."""

    __tablename__ = "closure_sla_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    # "urgent" | "important" | "normal" | "observe"
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("tenant_id", "priority", name="uq_closure_sla_tenant_priority"),
    )
