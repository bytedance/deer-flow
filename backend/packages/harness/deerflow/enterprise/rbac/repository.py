"""RBAC persistence: ORM models, repository ABC, and SQLite/Postgres impls.

Tables (RFC §8.2):

- ``roles``: ``id`` (TEXT, PK — stores :class:`Role` enum value),
  ``name`` (display name, UNIQUE), ``description``, ``is_default`` flag.
- ``role_permissions``: composite PK ``(role_id, permission)`` with
  ``granted_by`` audit column. Permission strings are the
  :class:`Permission` enum values (e.g. ``"data:read"``).

Both ORM classes register on the shared
:class:`deerflow.persistence.base.Base` metadata so the existing Alembic
environment in ``deerflow.persistence.migrations.env`` picks them up via
``target_metadata = Base.metadata`` (plan §2.1 / M0-5).

The SQLite and Postgres repositories currently share the same code path
because the operations are pure SQLAlchemy Core / ORM with no
backend-specific SQL. We keep the two classes distinct anyway so M2/M3
can specialise (e.g. PostgreSQL bulk upserts) without renaming public
symbols.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import Boolean, ForeignKey, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.enterprise.rbac.models import DEFAULT_ROLE_PERMISSIONS, Permission, Role
from deerflow.persistence.base import Base

# ── ORM models ───────────────────────────────────────────────────────────


class RoleRow(Base):
    """``roles`` table: one row per built-in or custom role."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RolePermissionRow(Base):
    """``role_permissions`` table: composite (role_id, permission) PK."""

    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ── Repository contract ──────────────────────────────────────────────────


class RbacRepository(ABC):
    """Read/write contract over the ``roles`` + ``role_permissions`` tables.

    Permission look-ups (:meth:`get_role_permissions`) are intentionally
    on the hot path of every authenticated request — implementations are
    expected to be cheap (single-statement, indexed). The Alembic data
    migration in M1-3 seeds :data:`DEFAULT_ROLE_PERMISSIONS` so a fresh
    database is usable without any admin action.
    """

    @abstractmethod
    async def get_role_permissions(self, role: Role) -> set[Permission]:
        """Return all permissions currently granted to ``role``.

        Unknown permission strings (e.g. an enum value removed in a later
        release) are silently dropped so a stale row cannot crash
        permission resolution. Repository implementations log a warning
        on the drop.
        """

    @abstractmethod
    async def set_custom_permission(self, role: Role, permission: Permission, granted_by: str) -> None:
        """Insert or update a single ``(role, permission)`` grant."""

    @abstractmethod
    async def remove_custom_permission(self, role: Role, permission: Permission) -> None:
        """Drop a single ``(role, permission)`` grant. No-op when absent."""

    @abstractmethod
    async def list_roles(self) -> list[Role]:
        """Return every role row that maps to a known :class:`Role` enum value.

        Custom rows whose ``id`` is not in the enum are filtered out so
        downstream consumers can safely call ``Role(value)``.
        """

    @abstractmethod
    async def replace_role_permissions(self, role: Role, permissions: set[Permission], granted_by: str) -> None:
        """Replace the full permission set for ``role`` atomically.

        Used by the ``PUT /roles/{id}/permissions`` route — the operator
        sends the desired state and the repository diffs it against the
        current rows in a single transaction.
        """


# ── SQLAlchemy-backed implementation ─────────────────────────────────────


import logging  # noqa: E402  (after class defs for readability)

logger = logging.getLogger(__name__)


class _SqlAlchemyRbacRepository(RbacRepository):
    """Shared implementation for both SQLite and PostgreSQL backends.

    Subclasses only exist so that future backend-specific tuning (bulk
    upserts on PG, e.g.) has a natural home.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_role_permissions(self, role: Role) -> set[Permission]:
        stmt = select(RolePermissionRow.permission).where(RolePermissionRow.role_id == role.value)
        async with self._sf() as session:
            result = await session.execute(stmt)
            permissions: set[Permission] = set()
            for value in result.scalars():
                try:
                    permissions.add(Permission(value))
                except ValueError:
                    # Stale enum value from a previous release — log and
                    # drop instead of crashing the whole permission
                    # resolution path.
                    logger.warning(
                        "Ignoring unknown permission %r on role %r — drop or migrate the role_permissions row",
                        value,
                        role.value,
                    )
        return permissions

    async def set_custom_permission(self, role: Role, permission: Permission, granted_by: str) -> None:
        async with self._sf() as session:
            existing = await session.get(RolePermissionRow, (role.value, permission.value))
            if existing is None:
                # Lazily upsert the role row so the FK constraint never
                # trips when an operator sets a permission on a role that
                # was not pre-seeded.
                role_row = await session.get(RoleRow, role.value)
                if role_row is None:
                    session.add(RoleRow(id=role.value, name=role.value, is_default=False))
                session.add(
                    RolePermissionRow(
                        role_id=role.value,
                        permission=permission.value,
                        granted_by=granted_by,
                    ),
                )
            else:
                existing.granted_by = granted_by
            await session.commit()

    async def remove_custom_permission(self, role: Role, permission: Permission) -> None:
        async with self._sf() as session:
            row = await session.get(RolePermissionRow, (role.value, permission.value))
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def list_roles(self) -> list[Role]:
        stmt = select(RoleRow.id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            roles: list[Role] = []
            for value in result.scalars():
                try:
                    roles.append(Role(value))
                except ValueError:
                    logger.warning("Ignoring unknown role row id=%r", value)
        return roles

    async def replace_role_permissions(self, role: Role, permissions: set[Permission], granted_by: str) -> None:
        async with self._sf() as session:
            # Ensure the role row exists so FK from role_permissions is satisfied.
            role_row = await session.get(RoleRow, role.value)
            if role_row is None:
                session.add(RoleRow(id=role.value, name=role.value, is_default=False))

            current_stmt = select(RolePermissionRow).where(RolePermissionRow.role_id == role.value)
            current_rows = (await session.execute(current_stmt)).scalars().all()
            current_perms = {row.permission for row in current_rows}
            desired_perms = {p.value for p in permissions}

            for row in current_rows:
                if row.permission not in desired_perms:
                    await session.delete(row)
            for new_value in desired_perms - current_perms:
                session.add(
                    RolePermissionRow(
                        role_id=role.value,
                        permission=new_value,
                        granted_by=granted_by,
                    ),
                )
            await session.commit()


class SqliteRbacRepository(_SqlAlchemyRbacRepository):
    """SQLite-backed RBAC repository (default dev backend)."""


class PostgresRbacRepository(_SqlAlchemyRbacRepository):
    """PostgreSQL-backed RBAC repository (recommended for production)."""


async def seed_default_role_permissions(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Idempotently insert :data:`DEFAULT_ROLE_PERMISSIONS` into an empty DB.

    Primarily used in tests and the dev-mode ``init_engine`` autocreate
    path — production seeding lives in the Alembic data migration so the
    initial state is captured in version control. Safe to call on an
    already-seeded database: the method only inserts rows that do not
    already exist.
    """

    async with session_factory() as session:
        for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
            role_row = await session.get(RoleRow, role.value)
            if role_row is None:
                session.add(RoleRow(id=role.value, name=role.value, is_default=True))
            for permission in permissions:
                existing = await session.get(RolePermissionRow, (role.value, permission.value))
                if existing is None:
                    session.add(
                        RolePermissionRow(
                            role_id=role.value,
                            permission=permission.value,
                            granted_by="system:default",
                        ),
                    )
        await session.commit()


__all__ = [
    "PostgresRbacRepository",
    "RbacRepository",
    "RolePermissionRow",
    "RoleRow",
    "SqliteRbacRepository",
    "seed_default_role_permissions",
]
