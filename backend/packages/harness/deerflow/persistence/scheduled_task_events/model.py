"""ORM model for scheduled-task lifecycle events (agent stop, auto-pause, finish).

The finalization observer writes one row per lifecycle transition in the same
transaction as the task or occurrence state change. ``(task_id, anchor, event)``
is unique, so crash and lease recovery that finalize again add nothing. The
row is display-only chat history for the originating conversation: it is not
part of the checkpoint and never becomes model context. Deleting the task
keeps its rows (they carry a title snapshot); deleting the chat removes them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ScheduledTaskEventRow(Base):
    __tablename__ = "scheduled_task_events"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The originating chat (the task's ``origin_thread_id``).
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL only for an idle finish (no occurrence ended the task).
    occurrence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Dedupe anchor: the occurrence id, else ``end:<iso>`` / ``seq:<n>``.
    anchor: Mapped[str] = mapped_column(String(96), nullable=False)
    # task_stopped | task_paused | task_finished
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    # Newest run of the originating chat when the event was written; the chat
    # places the line after the turn that holds this run.
    after_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_scheduled_task_events"),
        UniqueConstraint("task_id", "anchor", "event", name="uq_scheduled_task_event"),
        Index("ix_scheduled_task_events_thread", "thread_id", "created_at"),
        Index("ix_scheduled_task_events_user_id", "user_id"),
    )
