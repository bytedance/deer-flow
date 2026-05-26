"""ORM model for memory audit logs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class MemoryAuditRow(Base):
    """Audit log entry for memory CRUD operations."""

    __tablename__ = "memory_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    fact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_audit_tenant_layer", "tenant_id", "layer"),
        Index("ix_audit_user_action", "user_id", "action"),
        Index("ix_audit_created", "created_at"),
    )
