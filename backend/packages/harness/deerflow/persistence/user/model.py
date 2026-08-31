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

# Single source of truth for the index name, shared with
# app.gateway.auth.repositories.sqlite._is_oauth_identity_violation (which
# has to match a Postgres driver error's constraint_name against exactly
# this string). Previously that name was a separate hardcoded literal
# there, with no test catching the two drifting apart. Migration files
# under persistence/migrations/versions/ intentionally do NOT import this
# -- migrations are frozen historical DDL, not a live view of the model --
# so 0018_oauth_identity_pg_partial.py keeps its own literal by
# convention (consistent with every other revision in that package).
OAUTH_IDENTITY_INDEX_NAME = "idx_users_oauth_identity"


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
        # sqlite_where alone is a SQLAlchemy dialect-specific kwarg -- it
        # does not apply on the postgresql dialect, so a table created
        # against Postgres with only sqlite_where builds a FULL
        # (non-partial) unique index instead of a partial one. This is
        # NOT a correctness bug: verified empirically against a live
        # Postgres instance that a full index already enforces the
        # intended semantics on its own -- Postgres (like SQLite) treats
        # NULL as never-equal-to-NULL in a unique index, so real
        # (provider, id) duplicates are already rejected and unlimited
        # (NULL, NULL) rows are already allowed, per standard SQL NULL
        # handling, independent of the WHERE predicate. postgresql_where
        # is added for two smaller, real reasons instead: (1) it matches
        # the comment above literally (a partial index, on both
        # backends), and (2) a partial index only indexes non-NULL rows,
        # so it stays smaller and cheaper to maintain as the
        # plain-password-account rows (the common case) accumulate.
        Index(
            OAUTH_IDENTITY_INDEX_NAME,
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
            postgresql_where=text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL"),
        ),
    )
