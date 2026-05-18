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

import json
import logging
from datetime import UTC
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.auth.models import User
from app.gateway.auth.repositories.base import UserNotFoundError, UserRepository
from deerflow.persistence.user.model import UserRow

logger = logging.getLogger(__name__)


# Mapping from enterprise role id to the legacy ``system_role`` value
# whose users should also be considered as holding the role. Mirrors
# ``deerflow.enterprise.rbac.permission_provider._SYSTEM_ROLE_MAPPING``
# but lives here as a small inline constant so the app layer does not
# import enterprise modules eagerly.
_ROLE_TO_SYSTEM_ROLE: dict[str, str] = {
    "admin": "admin",
    "member": "user",
}


def _serialize_roles(roles: list[str]) -> str:
    """Serialise ``User.roles`` to the JSON-encoded TEXT column."""
    # ``ensure_ascii=False`` matches the engine-wide JSON serializer used
    # for other persistence rows (see ``persistence/engine.py``).
    return json.dumps(list(roles or []), ensure_ascii=False)


def _deserialize_roles(raw: str | None) -> list[str]:
    """Parse ``UserRow.roles`` JSON back into a Python list.

    Invalid / legacy NULL values are tolerated and surfaced as an empty
    list so a corrupted row cannot block the entire auth path — the
    warning helps operators spot it.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Malformed users.roles JSON %r; treating as empty list", raw)
        return []
    if not isinstance(parsed, list):
        logger.warning("Expected users.roles JSON array, got %r; treating as empty list", type(parsed).__name__)
        return []
    return [str(item) for item in parsed]


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
            system_role=row.system_role,
            roles=_deserialize_roles(getattr(row, "roles", None)),
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
            roles=_serialize_roles(user.roles),
            created_at=user.created_at,
            oauth_provider=user.oauth_provider,
            oauth_id=user.oauth_id,
            needs_setup=user.needs_setup,
            token_version=user.token_version,
        )

    # ── CRUD ──────────────────────────────────────────────────────────

    async def create_user(self, user: User) -> User:
        """Insert a new user. Raises ``ValueError`` on duplicate email."""
        row = self._user_to_row(user)
        async with self._sf() as session:
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
        stmt = select(UserRow).where(UserRow.email == email)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
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
            row.email = user.email
            row.password_hash = user.password_hash
            row.system_role = user.system_role
            row.roles = _serialize_roles(user.roles)
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

    async def get_users_by_role(self, role: str) -> list[User]:
        """Return every user whose ``roles`` JSON contains ``role`` or whose
        legacy ``system_role`` maps to ``role`` (see ``_ROLE_TO_SYSTEM_ROLE``).

        Implementation notes:

        - We use SQLite-portable JSON matching via ``LIKE`` on the
          serialised array. ``roles`` is stored as a JSON list — the
          ``"<role>"`` token (with surrounding quotes) cannot match by
          accident across role names because ``JSON.dumps`` escapes
          embedded quotes and we never store a role id containing them.
          PostgreSQL would benefit from ``jsonb`` / ``@>`` once
          ``users.roles`` is migrated to ``jsonb`` — tracked in plan
          backlog under PostgreSQL production hardening.
        - Returns an empty list when no users match. Caller decides
          whether 404 is appropriate.
        """
        legacy_system_role = _ROLE_TO_SYSTEM_ROLE.get(role)
        # The pattern keeps the surrounding quotes so ``"member"`` does
        # not match ``"membership"`` (defence in depth — there is no
        # such role today, but the constraint is cheap).
        like_pattern = f'%"{role}"%'
        clauses = [UserRow.roles.like(like_pattern)]
        if legacy_system_role is not None:
            clauses.append(UserRow.system_role == legacy_system_role)
        stmt = select(UserRow).where(or_(*clauses))
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_user(row) for row in result.scalars().all()]

    async def list_all_users(self) -> list[User]:
        """Return every row from ``users`` ordered by ``created_at``.

        Ordered output keeps script logs deterministic across runs and
        helps operators diff dry-run vs real-run output line by line.
        """
        stmt = select(UserRow).order_by(UserRow.created_at)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_user(row) for row in result.scalars().all()]


# Backwards-compatibility alias: the file is named ``sqlite.py`` and
# the original class was named ``SQLiteUserRepository``, but the same
# implementation works for PostgreSQL because every operation goes
# through SQLAlchemy's async dialect. We expose ``PostgresUserRepository``
# as an alias so call sites that want explicit naming can use it without
# duplicating code (plan §3 M1-6 covers both backends).
PostgresUserRepository = SQLiteUserRepository
