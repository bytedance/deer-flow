"""SQLAlchemy-backed UserRepository implementation.

Uses the shared async session factory from
``deerflow.persistence.engine`` — the ``users`` table lives in the
same database as ``threads_meta``, ``runs``, ``run_events``, and
``feedback``.

Constructor takes the session factory directly (same pattern as the
other four repositories in ``deerflow.persistence.*``). Callers
construct this after ``init_engine_from_config()`` has run.
"""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import UTC
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.auth.models import User
from app.gateway.auth.repositories.base import (
    UserNotFoundError,
    UserPreferencesNotInitializedError,
    UserPreferencesWriteConflict,
    UserRepository,
)
from deerflow.persistence.user.model import UserRow

_PREFERENCE_WRITE_MAX_ATTEMPTS = 5


def _normalize_email(email: str) -> str:
    """Canonicalise an email address for storage and lookup.

    An email identifies exactly one account regardless of the case the client
    sends. The two write paths would otherwise disagree: local registration
    normalises through ``EmailStr``, which lowercases only the *domain* and
    keeps the local-part case (``Victim@X.COM`` -> ``Victim@x.com``), while OIDC
    provisioning lowercases the whole address (``-> victim@x.com``). Combined
    with the previous case-sensitive lookup, ``Victim@x.com`` and
    ``victim@x.com`` resolved to two separate rows, defeating the invariant
    that a local account blocks an SSO login on the same email.

    Canonicalising to lowercase at every write site and matching
    case-insensitively on read closes that gap for new accounts while letting
    existing mixed-case rows keep resolving, without a destructive bulk rewrite.
    """
    return email.lower()


class SQLiteUserRepository(UserRepository):
    """Async user repository backed by the shared SQLAlchemy engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Converters ────────────────────────────────────────────────────

    @staticmethod
    def _row_to_user(row: UserRow) -> User:
        return User(
            id=UUID(row.id),
            email=row.email,
            password_hash=row.password_hash,
            system_role=row.system_role,  # type: ignore[arg-type]
            # SQLite loses tzinfo on read; reattach UTC so downstream
            # code can compare timestamps reliably.
            created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
            oauth_provider=row.oauth_provider,
            oauth_id=row.oauth_id,
            needs_setup=row.needs_setup,
            token_version=row.token_version,
        )

    @staticmethod
    def _user_to_row(user: User) -> UserRow:
        return UserRow(
            id=str(user.id),
            email=user.email,
            password_hash=user.password_hash,
            system_role=user.system_role,
            created_at=user.created_at,
            oauth_provider=user.oauth_provider,
            oauth_id=user.oauth_id,
            needs_setup=user.needs_setup,
            token_version=user.token_version,
        )

    # ── CRUD ──────────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        """Insert a new user. Raises ``ValueError`` on duplicate email.

        The email is canonicalised to lowercase before insert so the existing
        unique constraint enforces case-insensitive uniqueness for new rows and
        the returned ``User`` reflects the stored form.
        """
        user.email = _normalize_email(user.email)
        row = self._user_to_row(user)
        async with self._sf() as session:
            # The unique constraint is case-sensitive, so it cannot catch a
            # canonical address colliding with a mixed-case legacy row.
            existing = select(UserRow.id).where(func.lower(UserRow.email) == user.email).limit(1)
            if await session.scalar(existing) is not None:
                raise ValueError(f"Email already registered: {user.email}")
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(f"Email already registered: {user.email}") from exc
        return user

    async def get_user_by_id(self, user_id: str) -> User | None:
        async with self._sf() as session:
            row = await session.get(UserRow, user_id)
            return self._row_to_user(row) if row is not None else None

    async def get_user_by_email(self, email: str) -> User | None:
        # Case-insensitive match: an account is keyed by its email regardless of
        # the case the caller supplies (see ``_normalize_email``). ``.first()``
        # with a deterministic ``created_at`` ordering resolves to the oldest
        # account instead of raising if a pre-fix database already holds two
        # rows differing only in case, so the fix never turns a legacy duplicate
        # pair into a 500. ``id`` is a secondary tiebreaker so the choice stays
        # deterministic even if two legacy rows share the same ``created_at``.
        stmt = select(UserRow).where(func.lower(UserRow.email) == _normalize_email(email)).order_by(UserRow.created_at, UserRow.id).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return self._row_to_user(row) if row is not None else None

    async def update_user(self, user: User) -> User:
        async with self._sf() as session:
            row = await session.get(UserRow, str(user.id))
            if row is None:
                # Hard fail on concurrent delete: callers (reset_admin,
                # password change handlers, _ensure_admin_user) all
                # fetched the user just before this call, so a missing
                # row here means the row vanished underneath us. Silent
                # success would let the caller log "password reset" for
                # a row that no longer exists.
                raise UserNotFoundError(f"User {user.id} no longer exists")
            # Canonicalise the email only when it actually changes, comparing
            # case-insensitively against the stored value, then mirror the
            # persisted value back onto the returned object. Re-lowercasing an
            # *unchanged* legacy mixed-case email — e.g. a password-only update
            # on a pre-fix ``Victim@x.com`` row while a canonical ``victim@x.com``
            # row also exists — would rewrite it onto the other row's unique
            # email and raise IntegrityError, surfacing as a 500 on the
            # change-password / reset-admin paths that do not catch it. Guarding
            # against the *raw* stored value (``canonical != row.email``) is not
            # enough: the mixed-case row's canonical form still differs from its
            # own stored casing, so it would rewrite and collide anyway. A genuine
            # change still normalises, so the unique constraint keeps enforcing
            # case-insensitive uniqueness for updated rows; get_user_by_email
            # already resolves legacy mixed-case rows case-insensitively on read.
            canonical_email = _normalize_email(user.email)
            if canonical_email != _normalize_email(row.email):
                row.email = canonical_email
            user.email = row.email
            row.password_hash = user.password_hash
            row.system_role = user.system_role
            row.oauth_provider = user.oauth_provider
            row.oauth_id = user.oauth_id
            row.needs_setup = user.needs_setup
            row.token_version = user.token_version
            await session.commit()
        return user

    async def count_users(self) -> int:
        stmt = select(func.count()).select_from(UserRow)
        async with self._sf() as session:
            return await session.scalar(stmt) or 0

    async def count_admin_users(self) -> int:
        stmt = select(func.count()).select_from(UserRow).where(UserRow.system_role == "admin")
        async with self._sf() as session:
            return await session.scalar(stmt) or 0

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        stmt = select(UserRow).where(UserRow.oauth_provider == provider, UserRow.oauth_id == oauth_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_user(row) if row is not None else None

    async def get_user_preferences(self, user_id: str) -> tuple[dict | None, int]:
        stmt = select(UserRow.preferences, UserRow.preferences_revision).where(UserRow.id == user_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one_or_none()
        if row is None:
            raise UserNotFoundError(f"User {user_id} no longer exists")
        preferences, revision = row
        return deepcopy(preferences), int(revision)

    async def initialize_user_preferences(self, user_id: str, settings: dict) -> tuple[dict, int]:
        """Set the first preference record without overwriting another client.

        The conditional update is the cross-process arbiter: two tabs or Gateway
        workers can both observe NULL, but only one can change it. The loser
        reads and returns the winner's server value.
        """
        candidate = deepcopy(settings)
        async with self._sf() as session:
            result = await session.execute(
                update(UserRow)
                .where(UserRow.id == user_id, UserRow.preferences.is_(None))
                .values(
                    preferences=candidate,
                    preferences_revision=UserRow.preferences_revision + 1,
                )
            )
            if result.rowcount == 0:
                row = (await session.execute(select(UserRow.preferences, UserRow.preferences_revision).where(UserRow.id == user_id))).one_or_none()
                if row is None:
                    raise UserNotFoundError(f"User {user_id} no longer exists")
                existing, revision = row
                if existing is None:
                    # A concurrent transaction may have lost before committing;
                    # let a normal retry from the client resolve that rare race.
                    raise UserPreferencesWriteConflict(f"Preferences for user {user_id} are being initialized")
                return deepcopy(existing), int(revision)

            row = (await session.execute(select(UserRow.preferences, UserRow.preferences_revision).where(UserRow.id == user_id))).one()
            await session.commit()
            stored, revision = row
            return deepcopy(stored), int(revision)

    async def merge_user_preferences(self, user_id: str, patch: dict) -> tuple[dict, int]:
        """Merge with an optimistic revision CAS supported by SQLite/Postgres."""
        for _attempt in range(_PREFERENCE_WRITE_MAX_ATTEMPTS):
            async with self._sf() as session:
                dialect_name = session.get_bind().dialect.name
                try:
                    row = (await session.execute(select(UserRow.preferences, UserRow.preferences_revision).where(UserRow.id == user_id))).one_or_none()
                    if row is None:
                        raise UserNotFoundError(f"User {user_id} no longer exists")
                    current, revision = row
                    if current is None:
                        raise UserPreferencesNotInitializedError(f"Preferences for user {user_id} have not been initialized")

                    merged = _merge_preferences(current, patch)
                    result = await session.execute(
                        update(UserRow)
                        .where(
                            UserRow.id == user_id,
                            UserRow.preferences_revision == revision,
                        )
                        .values(
                            preferences=merged,
                            preferences_revision=revision + 1,
                        )
                    )
                    if result.rowcount == 1:
                        await session.commit()
                        return merged, int(revision) + 1
                    await session.rollback()
                except OperationalError as exc:
                    # In WAL mode, a transaction that SELECTed before another
                    # writer committed cannot upgrade its stale read snapshot.
                    # SQLite reports SQLITE_BUSY_SNAPSHOT immediately; the
                    # connection busy_timeout cannot make that snapshot valid.
                    # Roll back the snapshot and rerun the complete read/merge/
                    # CAS cycle so disjoint client patches are not lost. Other
                    # SQLite failures and every Postgres failure retain their
                    # existing error semantics.
                    if dialect_name != "sqlite" or not _is_sqlite_busy_error(exc):
                        raise
                    await session.rollback()

        raise UserPreferencesWriteConflict(f"Concurrent preference updates for user {user_id} did not settle")


def _is_sqlite_busy_error(exc: OperationalError) -> bool:
    """Match SQLITE_BUSY and its extended result codes from sqlite3."""
    error_code = getattr(exc.orig, "sqlite_errorcode", None)
    if isinstance(error_code, int):
        return error_code & 0xFF == sqlite3.SQLITE_BUSY

    # Python 3.12's sqlite3 exceptions expose ``sqlite_errorcode``. Keep the
    # message fallback for compatible DBAPI adapters that omit that attribute.
    return "database is locked" in str(exc.orig).lower()


def _merge_preferences(current: dict, patch: dict) -> dict:
    """Deep-merge allowlisted sections; JSON null clears optional fields."""
    merged = deepcopy(current)
    for section, values in patch.items():
        target = merged.setdefault(section, {})
        for key, value in values.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = deepcopy(value)
    return merged
