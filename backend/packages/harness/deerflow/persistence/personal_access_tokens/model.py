"""ORM model for personal access tokens (PAT)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class PersonalAccessTokenRow(Base):
    __tablename__ = "personal_access_tokens"

    __table_args__ = (Index("ix_personal_access_tokens_token_digest", "token_digest", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 hex digest of the ``dfp_…`` token. The raw token exists only in
    # the create response and is never persisted or logged. The named unique
    # index (rather than a column-level constraint) keeps ``create_all`` output
    # identical to migration 0017, so downgrades work on bootstrapped DBs too.
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # Subset of the route-permission strings owned by ``app.gateway.authz``.
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
