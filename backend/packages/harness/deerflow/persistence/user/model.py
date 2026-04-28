"""ORM model for the users table.

Lives in the harness persistence package so it is picked up by
``Base.metadata.create_all()`` alongside ``threads_meta``, ``runs``,
``run_events``, and ``feedback``. Using the shared engine means:

- One SQLite/Postgres database, one connection pool
- One schema initialisation codepath
- Consistent async sessions across auth and persistence reads
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class UserRow(Base):
    __tablename__ = "users"

    # UUIDs are stored as 36-char strings for cross-backend portability.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # "admin" | "user" — kept as plain string to avoid ALTER TABLE pain
    # when new roles are introduced.
    system_role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # OAuth linkage (optional). A partial unique index enforces one
    # account per (provider, oauth_id) pair, leaving NULL/NULL rows
    # unconstrained so plain password accounts can coexist.
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Auth lifecycle flags
    needs_setup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_version: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index(
            "idx_users_oauth_identity",
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
        ),
    )
