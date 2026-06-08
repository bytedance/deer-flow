"""ORM model for per-user MCP credentials."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class McpUserCredentialRow(Base):
    __tablename__ = "mcp_user_credentials"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    server_name: Mapped[str] = mapped_column(String(128), primary_key=True)

    env_json: Mapped[dict] = mapped_column(JSON, default=dict)
    headers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    oauth_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_mcp_user_credentials_user", "user_id"),
        Index("ix_mcp_user_credentials_server", "server_name"),
    )
