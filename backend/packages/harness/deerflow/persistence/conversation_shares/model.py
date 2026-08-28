"""ORM model for read-only conversation share records (#4548)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ConversationShareRow(Base):
    """One owner-created share of an immutable conversation snapshot."""

    __tablename__ = "conversation_shares"

    __table_args__ = (Index("ix_conversation_shares_token_hash", "token_hash", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # HMAC-SHA-256 hex digest of the bearer token (pepper applied by the app
    # layer). The raw token exists only in the create response and is never
    # persisted or logged. The named unique index (rather than a column-level
    # constraint) keeps ``create_all`` output identical to the migration, so
    # downgrades work on bootstrapped databases too.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # Versioned, sanitized public snapshot DTO. Treated as untrusted content
    # at render time; built through the allowlisted snapshot contract, never
    # a raw serialization of LangGraph messages or run-event rows.
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Audit/debug boundary of the source thread at snapshot time. Public
    # rendering must never re-read the source thread with it.
    source_last_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
