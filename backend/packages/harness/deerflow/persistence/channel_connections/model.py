"""ORM models for user-owned IM channel connections."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ChannelConnectionRow(Base):
    __tablename__ = "channel_connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")

    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    external_account_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    workspace_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bot_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    capabilities_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "provider",
            "external_account_id",
            "workspace_id",
            name="uq_channel_connection_owner_provider_identity",
        ),
        Index("idx_channel_connections_event_lookup", "provider", "workspace_id", "bot_user_id"),
        # Enforce the single-active-owner invariant at the database layer: at most
        # one non-revoked row may exist per external identity. This makes ownership
        # transfer race-safe (concurrent connects from different owners can no
        # longer both commit a connected row). Partial unique indexes are
        # supported by both SQLite (>= 3.8.0) and PostgreSQL.
        Index(
            "uq_channel_connection_active_identity",
            "provider",
            "external_account_id",
            "workspace_id",
            unique=True,
            sqlite_where=text("status != 'revoked'"),
            postgresql_where=text("status != 'revoked'"),
        ),
    )


class ChannelCredentialRow(Base):
    __tablename__ = "channel_credentials"

    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("channel_connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encrypted_extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


class ChannelOAuthStateRow(Base):
    __tablename__ = "channel_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    code_verifier_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    nonce_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)


class ChannelConversationRow(Base):
    __tablename__ = "channel_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("channel_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_topic_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_conversation_id",
            "external_topic_id",
            name="uq_channel_conversation_connection_external",
        ),
    )
