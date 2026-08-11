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

from sqlalchemy import case, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.auth.models import SystemRole, User
from app.gateway.auth.repositories.base import (
    AdminRoleRequiredError,
    LastAdminError,
    UserNotFoundError,
    UserRepository,
    UserRoleChange,
)
from deerflow.persistence.user.model import UserRow


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


# "DEERROLE" encoded as a signed-safe 64-bit integer. Every PostgreSQL
# process uses this transaction-scoped advisory lock before changing a role,
# preventing write skew when two administrators are demoted concurrently.
_USER_ROLE_LOCK_KEY = 0x44454552524F4C45


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
            stored_email = canonical_email if canonical_email != _normalize_email(row.email) else row.email

            # Keep this as one SQL UPDATE rather than assigning onto the ORM
            # row. A role change can commit after the SELECT above; omitting
            # system_role from the values prevents a detached user from
            # restoring the stale role, while the SQL CASE makes token_version
            # monotonic against the value at update time (not SELECT time).
            stmt = (
                update(UserRow)
                .where(UserRow.id == str(user.id))
                .values(
                    email=stored_email,
                    password_hash=user.password_hash,
                    oauth_provider=user.oauth_provider,
                    oauth_id=user.oauth_id,
                    needs_setup=user.needs_setup,
                    token_version=case(
                        (UserRow.token_version < user.token_version, user.token_version),
                        else_=UserRow.token_version,
                    ),
                )
                .returning(UserRow.email, UserRow.system_role, UserRow.token_version)
                .execution_options(synchronize_session=False)
            )
            persisted = (await session.execute(stmt)).one_or_none()
            if persisted is None:
                raise UserNotFoundError(f"User {user.id} no longer exists")
            user.email = persisted.email
            user.system_role = persisted.system_role  # type: ignore[assignment]
            user.token_version = persisted.token_version
            await session.commit()
        return user

    async def list_users(self, *, offset: int, limit: int) -> tuple[list[User], int]:
        stmt = select(UserRow).order_by(UserRow.created_at, UserRow.id).offset(offset).limit(limit)
        count_stmt = select(func.count()).select_from(UserRow)
        async with self._sf() as session:
            rows = (await session.execute(stmt)).scalars().all()
            total = await session.scalar(count_stmt) or 0
        return [self._row_to_user(row) for row in rows], total

    async def change_user_role(
        self,
        *,
        actor_id: str,
        user_id: str,
        system_role: SystemRole,
    ) -> UserRoleChange:
        """Change a user role under a database-wide transaction lock.

        SQLite uses ``BEGIN IMMEDIATE`` so no competing writer can pass the
        last-admin check. PostgreSQL uses one transaction-scoped advisory lock,
        which provides the same cross-process serialization without requiring
        a schema-only guard row.
        """
        async with self._sf() as session:
            try:
                dialect_name = session.get_bind().dialect.name
                if dialect_name == "sqlite":
                    await session.execute(text("BEGIN IMMEDIATE"))
                elif dialect_name == "postgresql":
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"),
                        {"lock_key": _USER_ROLE_LOCK_KEY},
                    )
                else:
                    # The shared persistence engine currently supports SQLite
                    # and PostgreSQL. Fail closed if another SQL backend is
                    # introduced without a reviewed serialization primitive.
                    raise RuntimeError(f"User role changes are not supported for SQL dialect {dialect_name!r}")

                actor = await session.get(UserRow, actor_id)
                if actor is None or actor.system_role != "admin":
                    raise AdminRoleRequiredError("The acting user is no longer an administrator")

                target = await session.get(UserRow, user_id)
                if target is None:
                    raise UserNotFoundError(f"User {user_id} does not exist")

                previous_role: SystemRole = target.system_role  # type: ignore[assignment]
                if previous_role == system_role:
                    result = UserRoleChange(
                        user=self._row_to_user(target),
                        previous_role=previous_role,
                        changed=False,
                    )
                    await session.commit()
                    return result

                if previous_role == "admin" and system_role == "user":
                    admin_count_stmt = select(func.count()).select_from(UserRow).where(UserRow.system_role == "admin")
                    admin_count = await session.scalar(admin_count_stmt) or 0
                    if admin_count <= 1:
                        raise LastAdminError("The final administrator cannot be demoted")

                # Increment from the value at UPDATE time. Password/reset paths
                # are not protected by the role advisory lock, so a Python-side
                # ``target.token_version += 1`` based on the earlier SELECT
                # could overwrite or collapse a concurrent session revocation.
                update_stmt = (
                    update(UserRow)
                    .where(UserRow.id == user_id)
                    .values(
                        system_role=system_role,
                        token_version=UserRow.token_version + 1,
                    )
                    .returning(UserRow.id)
                    .execution_options(synchronize_session=False)
                )
                updated_id = (await session.execute(update_stmt)).scalar_one_or_none()
                if updated_id is None:
                    raise UserNotFoundError(f"User {user_id} does not exist")
                await session.refresh(target)
                result = UserRoleChange(
                    user=self._row_to_user(target),
                    previous_role=previous_role,
                    changed=True,
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

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
