"""ORM model for runtime MCP agent grants."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class McpAgentGrantRow(Base):
    __tablename__ = "mcp_agent_grants"

    binding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    grant: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
