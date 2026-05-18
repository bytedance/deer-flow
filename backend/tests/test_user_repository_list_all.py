"""Cover the new ``list_all_users`` repo method used by migrate_enterprise."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow  # noqa: F401 — register table


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'users.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SQLiteUserRepository(sf)
    finally:
        await engine.dispose()


def _u(email: str, *, system_role: str = "user", roles: list[str] | None = None) -> User:
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
async def test_list_all_users_returns_every_row(repo: SQLiteUserRepository) -> None:
    await repo.create_user(_u("a@example.com"))
    await repo.create_user(_u("b@example.com", system_role="admin"))
    await repo.create_user(_u("c@example.com", roles=["admin", "auditor"]))

    rows = await repo.list_all_users()

    emails = sorted(u.email for u in rows)
    assert emails == ["a@example.com", "b@example.com", "c@example.com"]


@pytest.mark.asyncio
async def test_list_all_users_empty_db_returns_empty_list(repo: SQLiteUserRepository) -> None:
    assert await repo.list_all_users() == []
