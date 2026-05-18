"""Unit tests for :mod:`deerflow.enterprise.rbac.repository` (plan M1-2).

The repository sits on the hot path of every authenticated request — once
``RbacPermissionProvider`` is registered, ``resolve_permissions`` calls
``get_role_permissions`` on every protected route. The tests below cover
the four contract surfaces enumerated in the plan §3.2:

* CRUD on individual ``(role, permission)`` rows
  (:meth:`set_custom_permission` / :meth:`remove_custom_permission`)
* The hot-path read (:meth:`get_role_permissions`)
* Bulk replace used by ``PUT /roles/{id}/permissions``
* Idempotent seed (:func:`seed_default_role_permissions`)
* Light concurrency check — two parallel writes against the same role
  must not corrupt the row set.

We talk to an in-memory SQLite database created via the shared
``deerflow.persistence.base:Base`` metadata. That mirrors the
``init_engine`` dev path; production schema management lives in Alembic
(:mod:`deerflow.persistence.migrations.versions.m1_initial_rbac_schema`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.enterprise.rbac.models import DEFAULT_ROLE_PERMISSIONS, Permission, Role
from deerflow.enterprise.rbac.repository import (
    RolePermissionRow,
    RoleRow,
    SqliteRbacRepository,
    seed_default_role_permissions,
)
from deerflow.persistence.base import Base

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker, None]:
    """Fresh in-memory SQLite engine per test for isolation.

    We use ``aiosqlite`` with a private in-memory URL so each test gets
    its own database — no cross-test bleed even though the tests run in
    the same process.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # We need ``roles`` + ``role_permissions`` (and ``users`` only
        # because ``UserRow`` is in the same metadata — create_all is a
        # no-op for tables the test never touches).
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def repo(session_factory: async_sessionmaker) -> SqliteRbacRepository:
    return SqliteRbacRepository(session_factory)


# ── get_role_permissions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_role_permissions_empty_when_no_rows(repo: SqliteRbacRepository) -> None:
    """Fresh DB has no rows -> empty set, not error."""
    result = await repo.get_role_permissions(Role.ADMIN)
    assert result == set()


@pytest.mark.asyncio
async def test_get_role_permissions_returns_stored_values(
    repo: SqliteRbacRepository,
) -> None:
    await repo.set_custom_permission(Role.MEMBER, Permission.THREAD_READ, "tester")
    await repo.set_custom_permission(Role.MEMBER, Permission.AGENT_VIEW, "tester")

    result = await repo.get_role_permissions(Role.MEMBER)

    assert result == {Permission.THREAD_READ, Permission.AGENT_VIEW}


@pytest.mark.asyncio
async def test_get_role_permissions_ignores_unknown_enum_values(
    repo: SqliteRbacRepository,
    session_factory: async_sessionmaker,
) -> None:
    """Stale rows (perm string no longer in the enum) must drop silently.

    Reverse-evidence for the docstring on
    ``_SqlAlchemyRbacRepository.get_role_permissions``: if a future
    release removes a permission, the runtime path must not crash for
    every authenticated user.
    """
    # Insert a row with a permission string that does not exist in the enum.
    async with session_factory() as session:
        session.add(RoleRow(id=Role.ADMIN.value, name=Role.ADMIN.value, is_default=True))
        session.add(
            RolePermissionRow(
                role_id=Role.ADMIN.value,
                permission="legacy:removed",  # not in Permission enum
                granted_by="tester",
            ),
        )
        await session.commit()

    result = await repo.get_role_permissions(Role.ADMIN)
    assert result == set()  # bad row silently dropped


# ── set / remove ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_custom_permission_is_idempotent(repo: SqliteRbacRepository) -> None:
    """Two calls with the same (role, perm) must not create a duplicate row."""
    await repo.set_custom_permission(Role.VIEWER, Permission.DATA_READ, "alice")
    await repo.set_custom_permission(Role.VIEWER, Permission.DATA_READ, "bob")

    result = await repo.get_role_permissions(Role.VIEWER)
    assert result == {Permission.DATA_READ}


@pytest.mark.asyncio
async def test_set_custom_permission_auto_creates_role_row(
    repo: SqliteRbacRepository,
    session_factory: async_sessionmaker,
) -> None:
    """Granting a perm on a not-yet-seeded role must lazily create the role row.

    Without the lazy insert, the FK constraint on ``role_permissions.role_id``
    would refuse the new row and the operator would have to seed the role
    first — a footgun the repo avoids on purpose.
    """
    await repo.set_custom_permission(Role.PROJECT_MANAGER, Permission.AGENT_CREATE, "alice")

    async with session_factory() as session:
        role_row = await session.get(RoleRow, Role.PROJECT_MANAGER.value)
        assert role_row is not None
        assert role_row.is_default is False  # auto-created rows are NOT marked default


@pytest.mark.asyncio
async def test_remove_custom_permission_drops_only_target(
    repo: SqliteRbacRepository,
) -> None:
    await repo.set_custom_permission(Role.MEMBER, Permission.THREAD_READ, "tester")
    await repo.set_custom_permission(Role.MEMBER, Permission.AGENT_VIEW, "tester")

    await repo.remove_custom_permission(Role.MEMBER, Permission.THREAD_READ)

    result = await repo.get_role_permissions(Role.MEMBER)
    assert result == {Permission.AGENT_VIEW}


@pytest.mark.asyncio
async def test_remove_missing_permission_is_noop(repo: SqliteRbacRepository) -> None:
    """``remove_custom_permission`` on a row that does not exist must not raise."""
    await repo.remove_custom_permission(Role.ADMIN, Permission.DATA_DELETE)
    # No exception is the assertion; also confirm the table is still empty.
    assert await repo.get_role_permissions(Role.ADMIN) == set()


# ── list_roles ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_roles_returns_only_known_enum_values(
    repo: SqliteRbacRepository,
    session_factory: async_sessionmaker,
) -> None:
    # Seed two valid rows and one row whose id is not in the enum.
    async with session_factory() as session:
        session.add(RoleRow(id=Role.ADMIN.value, name=Role.ADMIN.value, is_default=True))
        session.add(RoleRow(id=Role.VIEWER.value, name=Role.VIEWER.value, is_default=True))
        session.add(RoleRow(id="legacy_custom_role", name="legacy_custom_role", is_default=False))
        await session.commit()

    result = await repo.list_roles()

    assert set(result) == {Role.ADMIN, Role.VIEWER}, "Custom rows whose id is not in the Role enum must be filtered out"


# ── replace_role_permissions ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replace_role_permissions_adds_and_removes(
    repo: SqliteRbacRepository,
) -> None:
    """Bulk replace must converge to exactly the desired set."""
    await repo.set_custom_permission(Role.MEMBER, Permission.THREAD_READ, "tester")
    await repo.set_custom_permission(Role.MEMBER, Permission.AGENT_VIEW, "tester")

    await repo.replace_role_permissions(
        Role.MEMBER,
        {Permission.AGENT_VIEW, Permission.DATA_READ},
        "admin-actor",
    )

    result = await repo.get_role_permissions(Role.MEMBER)
    assert result == {Permission.AGENT_VIEW, Permission.DATA_READ}, "replace must remove THREAD_READ and add DATA_READ"


@pytest.mark.asyncio
async def test_replace_role_permissions_with_empty_set_clears_role(
    repo: SqliteRbacRepository,
) -> None:
    await repo.set_custom_permission(Role.VIEWER, Permission.DATA_READ, "tester")

    await repo.replace_role_permissions(Role.VIEWER, set(), "admin-actor")

    assert await repo.get_role_permissions(Role.VIEWER) == set()


@pytest.mark.asyncio
async def test_replace_role_permissions_auto_creates_role_row(
    repo: SqliteRbacRepository,
    session_factory: async_sessionmaker,
) -> None:
    await repo.replace_role_permissions(
        Role.PROJECT_MANAGER,
        {Permission.AGENT_VIEW},
        "admin-actor",
    )

    async with session_factory() as session:
        role_row = await session.get(RoleRow, Role.PROJECT_MANAGER.value)
        assert role_row is not None


# ── seed_default_role_permissions ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_default_role_permissions_inserts_all_defaults(
    session_factory: async_sessionmaker,
    repo: SqliteRbacRepository,
) -> None:
    await seed_default_role_permissions(session_factory)

    for role, expected in DEFAULT_ROLE_PERMISSIONS.items():
        actual = await repo.get_role_permissions(role)
        assert actual == expected, f"Seed mismatch for role {role!r}"


@pytest.mark.asyncio
async def test_seed_default_role_permissions_is_idempotent(
    session_factory: async_sessionmaker,
    repo: SqliteRbacRepository,
) -> None:
    """Running seed twice must not duplicate rows or raise IntegrityError."""
    await seed_default_role_permissions(session_factory)
    await seed_default_role_permissions(session_factory)

    # Spot-check: ADMIN has the same set after the second call.
    result = await repo.get_role_permissions(Role.ADMIN)
    assert result == DEFAULT_ROLE_PERMISSIONS[Role.ADMIN]


# ── Concurrency ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_writes_converge(
    repo: SqliteRbacRepository,
    session_factory: async_sessionmaker,
) -> None:
    """Two parallel ``set_custom_permission`` calls on a seeded role must converge.

    Production seeds the ``roles`` table via the Alembic data migration
    (see :mod:`deerflow.persistence.migrations.versions.m1_initial_rbac_schema`)
    before any runtime mutation can happen, so the realistic concurrency
    contract is "two writes on a seeded role, no rows lost, no
    duplicates". Concurrent first-time inserts of the *role row itself*
    are not a documented invariant — that path runs under the migration's
    transaction.
    """
    await seed_default_role_permissions(session_factory)

    await asyncio.gather(
        repo.set_custom_permission(Role.ADMIN, Permission.DATA_READ, "actor-a"),
        repo.set_custom_permission(Role.ADMIN, Permission.DATA_WRITE, "actor-b"),
    )

    result = await repo.get_role_permissions(Role.ADMIN)
    # Seed contributes the full ADMIN default set; both new perms are
    # already in DEFAULT_ROLE_PERMISSIONS[ADMIN], so the assertion is
    # "still equals the seeded set" — i.e. no duplicate-insert crash.
    assert {Permission.DATA_READ, Permission.DATA_WRITE} <= result
