"""ORM model for conversation-created scheduled runs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    assistant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="lead_agent")
    agent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(16), nullable=False, default="once")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    channel_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    topic_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thread_ts: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel_user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_channel_user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        Index("idx_scheduled_tasks_due", "status", "run_at"),
        Index("idx_scheduled_tasks_owner_thread", "owner_user_id", "thread_id"),
    )
