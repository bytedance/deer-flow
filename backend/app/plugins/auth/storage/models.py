from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import Base


class User(Base):
    """Application user table."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_id", name="uq_users_oauth_identity"),
        {"comment": "Application user table."},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    system_role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    oauth_provider: Mapped[str | None] = mapped_column(String(64), default=None)
    oauth_id: Mapped[str | None] = mapped_column(String(255), default=None)
    needs_setup: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
