"""ORM model for personal access tokens (PAT)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class PersonalAccessTokenRow(Base):
    __tablename__ = "personal_access_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 hex digest of the ``dfp_…`` token. The raw token exists only in
    # the create response and is never persisted or logged.
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Subset of the route-permission strings owned by ``app.gateway.authz``.
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
