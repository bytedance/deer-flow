"""ORM models for tenant-level agents and agent permissions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from deerflow.persistence.base import Base


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="tenant_public")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_groups: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    skills: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mcp_servers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
        Index("ix_agents_tenant_enabled", "tenant_id", "enabled"),
    )


class AgentPermissionRow(Base):
    __tablename__ = "agent_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("agent_id", "principal_type", "principal_id", name="uq_agent_perm_principal"),
    )
