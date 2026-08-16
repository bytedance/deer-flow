"""ORM model for the scheduled-task notification delivery outbox (issue #4254).

A row records one pending IM notification for a scheduled-task outcome. The
completion hook only enqueues; a separate delivery worker claims due rows and
sends them. Execution status (``scheduled_task_runs``) and delivery status
(this table) are deliberately independent: a failed delivery never changes the
run outcome, and a re-fired completion hook cannot duplicate a notification
because ``(task_run_id, event, provider, target)`` is unique.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationDeliveryRow(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # pending -> sending -> sent | failed. A failure with retries remaining
    # returns the row to pending with a backoff ``available_at``.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Bounded result snapshot written at enqueue time (summary text, run
    # status, error); the delivery worker never re-reads agent state.
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "task_run_id",
            "event",
            "provider",
            "target",
            name="uq_notification_delivery_run_event_target",
        ),
        Index("ix_notification_deliveries_due", "status", "available_at"),
    )
