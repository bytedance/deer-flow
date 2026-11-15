"""ORM model for thread metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ThreadMetaRow(Base):
    __tablename__ = "threads_meta"
    __table_args__ = (Index("ix_threads_meta_incognito_expires_at", "incognito", "expires_at"),)

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incarnation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assistant_id: Mapped[str | None] = mapped_column(String(128), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(20), default="idle")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nullable with no server default so a binary sharing the database during a
    # rolling upgrade keeps inserting rows; NULL reads as "not incognito".
    incognito: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Absolute deadline of the incognito thread's current lifetime. The TTL
    # sweep compares it against the database clock; NULL on ordinary threads.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
