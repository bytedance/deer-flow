"""ORM model for the users table.

Lives in the harness persistence package so it is picked up by
``Base.metadata.create_all()`` alongside ``threads_meta``, ``runs``,
``run_events``, and ``feedback``. Using the shared engine means:

- One SQLite/Postgres database, one connection pool
- One schema initialisation codepath
- Consistent async sessions across auth and persistence reads
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from deerflow.persistence.base import Base


class MalformedUserPreferences:
    """Opaque marker returned when a legacy SQLite JSON value cannot decode."""

    __slots__ = ()

    def __deepcopy__(self, memo: dict[int, object]) -> MalformedUserPreferences:
        return self


MALFORMED_USER_PREFERENCES = MalformedUserPreferences()


class LenientUserPreferencesJSON(TypeDecorator[object]):
    """JSON storage that contains malformed preference rows at the read edge."""

    impl = JSON
    cache_ok = True

    def result_processor(
        self,
        dialect: Dialect,
        coltype: object,
    ) -> Callable[[Any], Any] | None:
        # TypeDecorator.process_result_value runs only *after* the inner JSON
        # decoder, so it cannot catch malformed legacy SQLite text. Wrap that
        # decoder directly for this one non-critical preference column; valid
        # JSON and all bind/write behavior still use SQLAlchemy's JSON type.
        impl_processor = self.impl_instance.result_processor(dialect, coltype)
        if impl_processor is None:
            return None

        def process(value: Any) -> Any:
            try:
                return impl_processor(value)
            except (TypeError, ValueError):
                return MALFORMED_USER_PREFERENCES

        return process


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

    # Browser-safe, user-level UI preferences. The API owns a strict allowlist;
    # this JSON column must never receive credentials, browser permission state,
    # or thread/workspace-scoped data. NULL distinguishes "never migrated" from
    # a stored preference object so the frontend can perform a one-time import
    # from its legacy localStorage value.
    preferences: Mapped[object | None] = mapped_column(LenientUserPreferencesJSON(), nullable=True)
    preferences_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        Index(
            "idx_users_oauth_identity",
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
        ),
    )
