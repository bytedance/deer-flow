"""ORM model for agent usage statistics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class AgentUsageRow(Base):
    __tablename__ = "agent_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    token_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_agent_usage_tenant_agent", "tenant_id", "agent_name"),
        Index("ix_agent_usage_user", "user_id"),
        Index("ix_agent_usage_thread", "thread_id"),
        Index("ix_agent_usage_time_range", "tenant_id", "used_at"),
    )
