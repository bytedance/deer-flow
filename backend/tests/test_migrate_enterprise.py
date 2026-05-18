"""Tests for ``scripts.migrate_enterprise``.

The script promotes legacy ``system_role='admin'`` users into the new
RBAC ``roles=['admin']`` shape. Three contracts, three tests:

1. ``--dry-run`` reports candidates but never mutates.
2. Real run writes ``roles=['admin']`` on candidates and leaves
   non-admin / already-roled users alone.
3. Re-running on already-migrated rows is a no-op (idempotent).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow  # noqa: F401
from scripts.migrate_enterprise import migrate_admins


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm5.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SQLiteUserRepository(sf)
    finally:
        await engine.dispose()


def _u(email: str, *, system_role: str, roles: list[str] | None = None) -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="x",
        system_role=system_role,
        roles=roles or [],
        created_at=datetime.now(UTC),
        oauth_provider=None,
        oauth_id=None,
        needs_setup=False,
        token_version=0,
    )


@pytest.mark.asyncio
async def test_dry_run_lists_admins_without_modifying(repo) -> None:
    await repo.create_user(_u("alice@example.com", system_role="admin"))
    await repo.create_user(_u("bob@example.com", system_role="user"))

    report = await migrate_admins(repo, dry_run=True)

    assert [r["email"] for r in report["candidates"]] == ["alice@example.com"]
    assert report["upgraded"] == 0  # dry-run never writes

    # Repo state untouched.
    alice = await repo.get_user_by_email("alice@example.com")
    assert alice is not None
    assert alice.roles == []


@pytest.mark.asyncio
async def test_real_run_assigns_admin_role(repo) -> None:
    await repo.create_user(_u("alice@example.com", system_role="admin"))
    await repo.create_user(_u("bob@example.com", system_role="user"))

    report = await migrate_admins(repo, dry_run=False)

    assert report["upgraded"] == 1
    alice = await repo.get_user_by_email("alice@example.com")
    bob = await repo.get_user_by_email("bob@example.com")
    assert alice is not None and alice.roles == ["admin"]
    assert bob is not None and bob.roles == []  # untouched


@pytest.mark.asyncio
async def test_idempotent_does_not_overwrite_existing_roles(repo) -> None:
    """An admin who's been hand-curated to roles=['admin', 'auditor'] must NOT be reset."""
    await repo.create_user(
        _u("alice@example.com", system_role="admin", roles=["admin", "auditor"]),
    )

    report = await migrate_admins(repo, dry_run=False)

    assert report["upgraded"] == 0
    assert report["skipped"] == 1
    alice = await repo.get_user_by_email("alice@example.com")
    assert alice is not None
    assert sorted(alice.roles) == ["admin", "auditor"]  # preserved
