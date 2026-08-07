"""ORM rows for the platform-managed App-Key control plane."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AppProfileRow(Base):
    __tablename__ = "app_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class AppCredentialRow(Base):
    __tablename__ = "app_credentials"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    app_id: Mapped[str] = mapped_column(ForeignKey("app_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_app_credentials_active", "key_hash", "revoked_at"),)


class AppCapabilityRow(Base):
    __tablename__ = "app_capabilities"

    app_id: Mapped[str] = mapped_column(ForeignKey("app_profiles.id", ondelete="CASCADE"), primary_key=True)
    capability: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(128), primary_key=True)


class AppKeyAuditRow(Base):
    __tablename__ = "app_key_audits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    app_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
