from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, current_time


class User(DataClassBase):
    """User account table."""

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "idx_users_oauth_identity",
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
        ),
        {"comment": "User account table."},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    system_role: Mapped[str] = mapped_column(String(16), default="user")

    password_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    oauth_provider: Mapped[str | None] = mapped_column(String(32), default=None)
    oauth_id: Mapped[str | None] = mapped_column(String(128), default=None)
    needs_setup: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=current_time,
        sort_order=999,
        comment="Created at",
    )
