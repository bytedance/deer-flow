"""ORM model for the ``scheduled_job_runs`` table.

Each row is a single execution attempt of a scheduled job. Status flows:

    running → ok | error | skipped | timeout

Rows are append-only — never updated in place except to flip ``running``
to a terminal state and fill ``finished_at``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScheduledJobRunRow(Base):
    """A single execution attempt of a scheduled job."""

    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scheduled_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Redundant with job.user_id but stored here so list queries don't
    # need to join — repository enforces user_id at write time.
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # running | ok | error | skipped | timeout

    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_scheduled_job_runs_job_started", "job_id", "started_at"),
        Index("idx_scheduled_job_runs_user_started", "user_id", "started_at"),
    )
