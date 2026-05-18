"""Unit tests for :class:`RbacPermissionProvider` (plan M1-4).

Covers the three ``_resolve_roles`` branches plus the merge contract of
``resolve_permissions``: the returned set must be the union of the
enterprise ``Permission`` strings (from the repo) and the legacy
``LEGACY_PERMISSIONS_FOR_ROLE`` strings — without the legacy half the
existing ``/api/threads/*`` and ``/api/runs/*`` routes 403 the moment
RBAC turns on (plan §3.4 risk register).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.enterprise.config import RbacConfig
from deerflow.enterprise.rbac.models import (
    DEFAULT_ROLE_PERMISSIONS,
    LEGACY_PERMISSIONS_FOR_ROLE,
    Permission,
    Role,
)
from deerflow.enterprise.rbac.permission_provider import RbacPermissionProvider
from deerflow.enterprise.rbac.repository import (
    SqliteRbacRepository,
    seed_default_role_permissions,
)
from deerflow.persistence.base import Base

# ── Fixtures ───────────────────────────────────────────────────────────────


@dataclass
class _FakeUser:
    """Duck-typed stand-in for ``app.gateway.auth.models.User``.

    The harness layer cannot import the real ``User`` (boundary test);
    the provider uses ``getattr`` so any object with these attributes
    works.
    """

    id: str = "user-1"
    system_role: str = ""
    roles: list[str] = field(default_factory=list)


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sf
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_repo(session_factory: async_sessionmaker) -> SqliteRbacRepository:
    await seed_default_role_permissions(session_factory)
    return SqliteRbacRepository(session_factory)


@pytest.fixture
def default_config() -> RbacConfig:
    """RbacConfig with the built-in default role (matches §8.2)."""
    return RbacConfig(enabled=True, default_role="viewer")


# ── _resolve_roles branches ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_roles_uses_roles_field_when_present(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """Branch 1: ``user.roles`` non-empty wins over everything else."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    user = _FakeUser(system_role="user", roles=["admin", "viewer"])
    assert provider._resolve_roles(user) == [Role.ADMIN, Role.VIEWER]


@pytest.mark.asyncio
async def test_resolve_roles_falls_back_to_system_role(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """Branch 2: empty ``roles`` → map ``system_role`` to a :class:`Role`."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    assert provider._resolve_roles(_FakeUser(system_role="admin")) == [Role.ADMIN]
    assert provider._resolve_roles(_FakeUser(system_role="user")) == [Role.MEMBER]


@pytest.mark.asyncio
async def test_resolve_roles_falls_back_to_default_role(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """Branch 3: unknown ``system_role`` → use ``config.default_role``."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    # system_role is empty AND roles is empty → default_role kicks in
    assert provider._resolve_roles(_FakeUser()) == [Role.VIEWER]
    # unknown system_role label also falls through to default
    assert provider._resolve_roles(_FakeUser(system_role="ghost")) == [Role.VIEWER]


@pytest.mark.asyncio
async def test_resolve_roles_drops_unknown_role_values(
    seeded_repo: SqliteRbacRepository,
    default_config: RbacConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown strings in ``user.roles`` are warned-and-dropped, never crash."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    with caplog.at_level(logging.WARNING):
        resolved = provider._resolve_roles(_FakeUser(roles=["admin", "ghost"]))
    assert resolved == [Role.ADMIN]
    assert any("unknown role" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_resolve_roles_all_unknown_falls_through_to_system_role(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """If every value in ``roles`` is unknown, fall through to system_role/default."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    user = _FakeUser(system_role="admin", roles=["ghost-only"])
    assert provider._resolve_roles(user) == [Role.ADMIN]


@pytest.mark.asyncio
async def test_resolve_roles_invalid_default_returns_empty(
    seeded_repo: SqliteRbacRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If even ``default_role`` is unknown, return [] rather than crash."""
    cfg = RbacConfig(enabled=True, default_role="bogus-role")
    provider = RbacPermissionProvider(cfg, seeded_repo)
    with caplog.at_level(logging.WARNING):
        assert provider._resolve_roles(_FakeUser()) == []
    assert any("Configured default_role" in rec.message for rec in caplog.records)


# ── resolve_permissions: enterprise + legacy union ─────────────────────────


@pytest.mark.asyncio
async def test_resolve_permissions_returns_enterprise_plus_legacy(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """Admin user must get every enterprise Permission AND every legacy string.

    This is the core regression guard for plan §3.4: omit the LEGACY half
    and ``/api/threads/*`` returns 403 the moment RBAC is enabled.
    """
    provider = RbacPermissionProvider(default_config, seeded_repo)
    user = _FakeUser(roles=["admin"])
    permissions = await provider.resolve_permissions(user)

    expected_enterprise = {p.value for p in DEFAULT_ROLE_PERMISSIONS[Role.ADMIN]}
    expected_legacy = LEGACY_PERMISSIONS_FOR_ROLE[Role.ADMIN]
    assert expected_enterprise.issubset(permissions)
    assert expected_legacy.issubset(permissions)


@pytest.mark.asyncio
async def test_resolve_permissions_unions_multiple_roles(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """A user with several roles should get the union of all role permissions."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    user = _FakeUser(roles=["member", "viewer"])
    permissions = await provider.resolve_permissions(user)

    # MEMBER has thread:write; VIEWER does not — union must include it
    assert Permission.THREAD_WRITE.value in permissions
    # Both have data:read
    assert Permission.DATA_READ.value in permissions
    # Neither has user:manage
    assert Permission.USER_MANAGE.value not in permissions


@pytest.mark.asyncio
async def test_resolve_permissions_empty_for_unknown_default(
    seeded_repo: SqliteRbacRepository,
) -> None:
    """If we cannot resolve any role at all, return the empty set (not crash)."""
    cfg = RbacConfig(enabled=True, default_role="bogus-role")
    provider = RbacPermissionProvider(cfg, seeded_repo)
    permissions = await provider.resolve_permissions(_FakeUser())
    assert permissions == set()


@pytest.mark.asyncio
async def test_resolve_permissions_returns_a_set_not_list(seeded_repo: SqliteRbacRepository, default_config: RbacConfig) -> None:
    """The contract is ``set[str]`` — callers rely on dedup semantics."""
    provider = RbacPermissionProvider(default_config, seeded_repo)
    result = await provider.resolve_permissions(_FakeUser(roles=["admin"]))
    assert isinstance(result, set)
