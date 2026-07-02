"""ORM model for workflow frontdoor envelopes."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class WorkflowRow(Base):
    __tablename__ = "workflows"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="message")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    source: Mapped[str | None] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256))

    external_message_ref: Mapped[str | None] = mapped_column(Text)
    conversation_ref: Mapped[str | None] = mapped_column(Text)
    thread_ref: Mapped[str | None] = mapped_column(Text)
    sender_ref: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)

    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    checkpoint_ns: Mapped[str | None] = mapped_column(String(256))
    checkpoint_id: Mapped[str | None] = mapped_column(String(128))

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        Index(
            "uq_workflows_source_idempotency",
            "source_type",
            "source",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_workflows_status_updated", "status", "updated_at"),
        Index("ix_workflows_claimable", "status", "next_attempt_at", "lease_expires_at"),
        Index("ix_workflows_thread_run", "thread_id", "run_id"),
    )


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"

    workflow_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="lifecycle", index=True)

    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    checkpoint_ns: Mapped[str | None] = mapped_column(String(256))
    checkpoint_id: Mapped[str | None] = mapped_column(String(128))
    run_event_seq: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(256))
    source_event_ref: Mapped[str | None] = mapped_column(Text)

    content_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        UniqueConstraint("workflow_id", "seq", name="uq_workflow_events_workflow_seq"),
        Index("ix_workflow_events_workflow_created", "workflow_id", "created_at"),
        Index("ix_workflow_events_thread_run_seq", "thread_id", "run_id", "run_event_seq"),
    )
