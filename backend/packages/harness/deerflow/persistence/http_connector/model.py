"""ORM model for tenant-level HTTP connector configurations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from deerflow.persistence.base import Base


class TenantHttpConnectorRow(Base):
    __tablename__ = "tenant_http_connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    auth_token_env: Mapped[str | None] = mapped_column(String(100), nullable=True)
    auth_header: Mapped[str] = mapped_column(String(100), nullable=False, default="Authorization")
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    max_response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=524288)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_on_status: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: [502, 503, 504])
    cache_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_name", name="uq_tenant_http_connector_name"),
        Index("ix_tenant_http_connectors_tenant", "tenant_id", "enabled"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "connector_name": self.connector_name,
            "display_name": self.display_name,
            "description": self.description,
            "url": self.url,
            "method": self.method,
            "headers": self.headers,
            "auth_type": self.auth_type,
            "auth_token_env": self.auth_token_env,
            "auth_header": self.auth_header,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "max_retries": self.max_retries,
            "retry_on_status": self.retry_on_status,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "enabled": self.enabled,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
