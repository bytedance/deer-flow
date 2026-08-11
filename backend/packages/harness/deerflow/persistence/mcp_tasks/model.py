from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class McpTaskRow(Base):
    __tablename__ = "mcp_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    server_name: Mapped[str] = mapped_column(String(128))
    driver_name: Mapped[str] = mapped_column(String(64))
    remote_task_id: Mapped[str] = mapped_column(String(255))
    task_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_required: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    driver_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notification_status: Mapped[str] = mapped_column(String(16), default="none", index=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_poll_error_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "server_name",
            "remote_task_id",
            name="uq_mcp_tasks_user_server_remote",
        ),
        Index("ix_mcp_tasks_thread_created", "thread_id", "created_at"),
        Index("ix_mcp_tasks_due", "status", "next_poll_at"),
    )
