"""ORM model for the ``scheduled_jobs`` table.

A scheduled job is a user-owned, time-triggered Agent execution. The job
specification (trigger, payload, scheduling state) lives here; per-run
execution records live in ``scheduled_job_runs``.

Key fields:

- ``user_id``: owning DeerFlow user. All queries are scoped by this via the
  AUTO sentinel in ``ScheduledJobRepository``.
- ``trigger_type`` / ``trigger_data``: discriminated trigger (at / every / cron).
  ``trigger_data`` is a JSON blob carrying trigger-specific fields (``at``
  ISO timestamp, ``every_seconds`` + ``anchor_ms``, ``expr`` + ``tz`` +
  ``stagger_ms``).
- ``thread_strategy``: ``"new"`` (fresh thread per run) or ``"fixed"``
  (always reuse ``fixed_thread_id``).
- ``source_channel``: where the job was created. Drives delivery routing:
  ``"web"`` → in-app notification, ``"im:<platform>:<conv>:<chat_id>"``
  → IM push via existing ``app/channels`` infrastructure.
- ``delete_after_run``: one-shot (``at``) jobs default to ``True``;
  recurring (``every`` / ``cron``) jobs default to ``False``. Set
  explicitly on creation.
- ``next_run_at``: indexed. The scheduler reads ``WHERE enabled AND
  next_run_at <= now`` to find due jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScheduledJobRow(Base):
    """A user-owned scheduled job definition plus scheduling state."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Human description
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Trigger (discriminated union: at / every / cron)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Execution target
    thread_strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    fixed_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Scheduling state
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Error backoff state
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Lifecycle
    delete_after_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Source / delivery routing
    source_channel: Mapped[str] = mapped_column(String(128), nullable=False, default="web")

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    __table_args__ = (
        Index("idx_scheduled_jobs_due", "enabled", "next_run_at"),
        Index("idx_scheduled_jobs_user_enabled", "user_id", "enabled"),
    )
