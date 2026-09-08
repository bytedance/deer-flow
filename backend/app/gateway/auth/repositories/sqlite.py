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

from datetime import UTC
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.auth.models import User
from app.gateway.auth.repositories.base import UserNotFoundError, UserRepository
from deerflow.persistence.user.model import OAUTH_IDENTITY_INDEX_NAME, UserRow

# ``email`` is ``mapped_column(unique=True, index=True)``, which SQLAlchemy
# (and 0001_baseline) realise as a single UNIQUE INDEX -- not a named UNIQUE
# constraint -- so a Postgres duplicate reports the index name here.
_EMAIL_UNIQUE_INDEX_NAME = "ix_users_email"


def _driver_constraint_name(exc: IntegrityError) -> str | None:
    """The violated constraint's name from the driver exception, or ``None``
    when the driver does not expose one.

    ``exc.orig`` is NOT the raw driver error. SQLAlchemy's asyncpg dialect
    re-raises a plain ``AsyncAdapt_asyncpg_dbapi.IntegrityError`` built from a
    rendered string and carrying only ``pgcode``/``sqlstate``
    (``sqlalchemy/dialects/postgresql/asyncpg.py::_handle_exception``); the
    real ``asyncpg.UniqueViolationError`` — the one with ``constraint_name`` —
    survives as ``exc.orig.__cause__`` (``raise translated_error from error``).
    aiosqlite exposes no constraint name at all. Check the wrapper, then its
    cause.
    """
    for obj in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(obj, "constraint_name", None)
        if name:
            return str(name)
    return None


def _is_oauth_identity_violation(exc: IntegrityError) -> bool:
    """Distinguish the ``idx_users_oauth_identity`` (oauth_provider, oauth_id)
    unique-index violation from any OTHER ``IntegrityError`` reaching this
    commit (a duplicate primary key, or a duplicate-email race that slipped
    past the pre-check above).

    Never uses the SQLAlchemy wrapper's ``str(exc)``: it embeds the full
    failed INSERT statement, whose column list names
    ``oauth_provider``/``oauth_id`` on every call regardless of which
    constraint fired, so a substring check on it misclassifies every
    commit-time ``IntegrityError`` on this table as an OAuth conflict
    (reproduced on SQLite: a duplicate ``id`` raised "OAuth account already
    linked: None/None").

    Postgres: match :data:`OAUTH_IDENTITY_INDEX_NAME` against the driver
    constraint name (see :func:`_driver_constraint_name`). SQLite: no
    structured name, only a message naming the columns (``"UNIQUE constraint
    failed: users.oauth_provider, users.oauth_id"``) — require BOTH oauth
    column names, not a bare "oauth" substring.
    """
    name = _driver_constraint_name(exc)
    if name is not None:
        return name == OAUTH_IDENTITY_INDEX_NAME
    message = str(exc.orig).lower()
    return "oauth_provider" in message and "oauth_id" in message


def _is_email_violation(exc: IntegrityError) -> bool:
    """True when ``exc`` is the ``ix_users_email`` uniqueness violation, using
    the same driver-exception inspection as
    :func:`_is_oauth_identity_violation` (never ``str(exc)``, whose INSERT text
    names every column)."""
    name = _driver_constraint_name(exc)
    if name is not None:
        return name == _EMAIL_UNIQUE_INDEX_NAME
    return "users.email" in str(exc.orig).lower()


def _is_uniqueness_violation(exc: IntegrityError) -> bool:
    """True for a unique-index / primary-key violation specifically, as
    opposed to a NOT NULL / CHECK / foreign-key ``IntegrityError`` on the same
    INSERT -- only the former means "a user like this already exists"."""
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    if sqlstate is not None:
        return sqlstate == "23505"  # unique_violation
    message = str(exc.orig).lower()
    return "unique constraint failed" in message or "primary key constraint failed" in message


def _violated_constraint(exc: IntegrityError) -> str | None:
    """Best-effort name of the constraint behind ``exc``, for a diagnostic that
    does not pin an unattributed violation on a specific column. Uses the
    driver constraint name where available, else the column(s) SQLite names in
    its message (``"UNIQUE constraint failed: users.id"``)."""
    name = _driver_constraint_name(exc)
    if name:
        return name
    marker = "constraint failed: "
    message = str(exc.orig)
    if marker in message:
        return message.split(marker, 1)[1].splitlines()[0].strip() or None
    return None


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
        """Insert a new user. Raises ``ValueError`` on any uniqueness
        violation -- duplicate email, a duplicate (provider, oauth_id) pair
        for an OAuth-linked account, or a duplicate id -- with a message
        naming the specific conflict. Other ``IntegrityError``\\ s (NOT NULL,
        CHECK, foreign key) propagate unchanged.

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
                # The email pre-check above already ruled out an email
                # collision under normal (non-racing) conditions, so
                # IntegrityErrors reaching here are usually
                # idx_users_oauth_identity -- but not always (a duplicate
                # primary key, or an email collision that raced past the
                # pre-check). Attribute the failure to the constraint that
                # actually fired instead of assuming any one of them.
                if _is_oauth_identity_violation(exc):
                    raise ValueError(f"OAuth account already linked: {user.oauth_provider}/{user.oauth_id}") from exc
                if _is_email_violation(exc):
                    # A duplicate address that got past the pre-check: a
                    # concurrent insert of the same email.
                    raise ValueError(f"Email already registered: {user.email}") from exc
                if _is_uniqueness_violation(exc):
                    # Some other unique index / primary key (in practice a
                    # duplicate id). "Already exists" fits, but don't dress it
                    # up as an email conflict for an address that isn't
                    # registered.
                    constraint = _violated_constraint(exc)
                    raise ValueError(f"User already exists (constraint: {constraint})" if constraint else "User already exists") from exc
                # A NOT NULL / CHECK / foreign-key IntegrityError is not a
                # "user already exists" condition and not part of this
                # method's ValueError contract -- let it propagate.
                raise
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
