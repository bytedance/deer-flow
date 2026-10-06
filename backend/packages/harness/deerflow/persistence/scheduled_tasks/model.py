from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    origin_thread_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    goal_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The user's normalized "stop when ..." rule; never part of ``prompt``.
    stop_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    standing_notes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    context_mode: Mapped[str] = mapped_column(String(32), default="fresh_thread_per_run")
    assistant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String(16))
    schedule_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="enabled", index=True)
    overlap_policy: Mapped[str] = mapped_column(String(16), default="enqueue")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_occurrence_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # Occurrences with occurrence_seq <= this value never count toward the
    # unmet streak (moved by goal, prompt, stop-condition and note edits).
    unmet_streak_after_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ScheduledTaskRunStatus(StrEnum):
    """Canonical status vocabulary for scheduled-task occurrences."""

    QUEUED = "queued"
    LAUNCHING = "launching"
    RUNNING = "running"
    SUCCESS = "success"
    UNMET = "unmet"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


# Status constants - shared between scheduled_tasks and scheduled_task_runs
# to avoid circular import and ensure consistency.
# Import these from deerflow.persistence.scheduled_tasks.model in both modules.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {
        ScheduledTaskRunStatus.SUCCESS,
        ScheduledTaskRunStatus.UNMET,
        ScheduledTaskRunStatus.FAILED,
        ScheduledTaskRunStatus.SKIPPED,
        ScheduledTaskRunStatus.INTERRUPTED,
    }
)
ACTIVE_RUN_STATUSES: frozenset[str] = frozenset(
    {
        ScheduledTaskRunStatus.QUEUED,
        ScheduledTaskRunStatus.LAUNCHING,
        ScheduledTaskRunStatus.RUNNING,
    }
)

# Parent ``once`` task status projected from a terminal occurrence status.
# Shared by the completion path and both recovery paths so the mapping
# cannot drift between them.
ONCE_TASK_STATUS_BY_RUN_STATUS: dict[str, str] = {
    "success": "completed",
    "failed": "failed",
    "unmet": "failed",
    "interrupted": "cancelled",
    "skipped": "cancelled",
}
