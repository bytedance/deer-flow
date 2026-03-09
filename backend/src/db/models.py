"""SQLAlchemy ORM models for all database tables.

Defines the schema for users, threads, user_memory, user_api_keys,
uploads, timeline_events, and usage_log tables.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.db.engine import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Use JSON type that works with both PostgreSQL and SQLite
# In PostgreSQL this will use JSONB; in SQLite it uses JSON
_JSONType = JSON().with_variant(JSONB, "postgresql")


class UserModel(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self, include_password: bool = False) -> dict:
        """Convert to dictionary representation."""
        result = {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_password:
            result["password_hash"] = self.password_hash
        return result


class ThreadModel(Base):
    """Thread ownership model."""

    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    s3_sync_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_evicted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))

    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    __table_args__ = (
        Index("idx_threads_user_id", "user_id"),
        Index("idx_threads_s3_sync_status", "s3_sync_status"),
        Index("idx_threads_last_accessed_at", "last_accessed_at"),
        Index("idx_threads_project_id", "project_id"),
    )


class ProjectModel(Base):
    """Project model for organizing threads into folders."""

    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
        Index("idx_projects_user_id", "user_id"),
    )


class UserMemoryModel(Base):
    """Per-user memory storage model."""

    __tablename__ = "user_memory"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    memory_json: Mapped[dict] = mapped_column(_JSONType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class UserApiKeyModel(Base):
    """Encrypted API key storage model."""

    __tablename__ = "user_api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_api_keys_user_provider"),
        Index("idx_user_api_keys_user_id", "user_id"),
    )


class UserModelPreferenceModel(Base):
    """Per-user persisted model selection preferences."""

    __tablename__ = "user_model_preferences"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thinking_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_enabled: Mapped[dict] = mapped_column(_JSONType, nullable=False, default=dict)
    enabled_models: Mapped[dict] = mapped_column(_JSONType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class UploadModel(Base):
    """File upload metadata model."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("idx_uploads_thread_id", "thread_id"),)


class TimelineEventModel(Base):
    """Append-only agent timeline event log per thread.

    Records every message (human/ai/tool) and history truncation event
    as an ordered timeline for observability and debugging.
    """

    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_data: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_timeline_thread_id", "thread_id"),
        Index("idx_timeline_created_at", "created_at"),
    )


class UsageLogModel(Base):
    """Usage tracking / rate limiting model."""

    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("idx_usage_log_user_id", "user_id"),
        Index("idx_usage_log_created_at", "created_at"),
    )
