from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.plugins.auth.storage import DbUserRepository, UserCreate
from app.plugins.auth.storage.contracts import User
from app.plugins.auth.storage.models import User as UserModel  # noqa: F401
from store.persistence import MappedBase


async def _make_repo(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'users.db'}",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory


class TestUserRepository:
    @pytest.mark.anyio
    async def test_create_and_get_by_id(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            created = await repo.create_user(
                UserCreate(
                    id="user-1",
                    email="user1@example.com",
                    password_hash="hash-1",
                )
            )
            await session.commit()
            fetched = await repo.get_user_by_id("user-1")
        await engine.dispose()

        assert created.id == "user-1"
        assert fetched is not None
        assert fetched.email == "user1@example.com"
        assert fetched.password_hash == "hash-1"
        assert fetched.system_role == "user"
        assert fetched.needs_setup is False
        assert fetched.token_version == 0

    @pytest.mark.anyio
    async def test_get_by_email_and_oauth(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            await repo.create_user(
                UserCreate(
                    id="user-2",
                    email="oauth@example.com",
                    oauth_provider="github",
                    oauth_id="gh-123",
                )
            )
            await session.commit()
            by_email = await repo.get_user_by_email("oauth@example.com")
            by_oauth = await repo.get_user_by_oauth("github", "gh-123")
        await engine.dispose()

        assert by_email is not None
        assert by_email.id == "user-2"
        assert by_oauth is not None
        assert by_oauth.email == "oauth@example.com"

    @pytest.mark.anyio
    async def test_update_user(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            created = await repo.create_user(
                UserCreate(
                    id="user-3",
                    email="before@example.com",
                    password_hash="old-hash",
                    needs_setup=True,
                )
            )
            updated = await repo.update_user(
                User(
                    id=created.id,
                    email="after@example.com",
                    password_hash="new-hash",
                    system_role="admin",
                    oauth_provider=None,
                    oauth_id=None,
                    needs_setup=False,
                    token_version=2,
                    created_time=created.created_time,
                    updated_time=created.updated_time,
                )
            )
            await session.commit()
            fetched = await repo.get_user_by_id("user-3")
        await engine.dispose()

        assert updated.email == "after@example.com"
        assert fetched is not None
        assert fetched.system_role == "admin"
        assert fetched.password_hash == "new-hash"
        assert fetched.needs_setup is False
        assert fetched.token_version == 2

    @pytest.mark.anyio
    async def test_count_users_and_admins(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            await repo.create_user(UserCreate(id="user-4", email="admin@example.com", system_role="admin"))
            await repo.create_user(UserCreate(id="user-5", email="user@example.com", system_role="user"))
            await session.commit()
            user_count = await repo.count_users()
            admin_count = await repo.count_admin_users()
        await engine.dispose()

        assert user_count == 2
        assert admin_count == 1

    @pytest.mark.anyio
    async def test_duplicate_email_raises_value_error(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            await repo.create_user(UserCreate(id="user-6", email="dup@example.com"))
            with pytest.raises(ValueError, match="User already exists"):
                await repo.create_user(UserCreate(id="user-7", email="dup@example.com"))
        await engine.dispose()

    @pytest.mark.anyio
    async def test_update_missing_user_raises_lookup_error(self, tmp_path):
        engine, session_factory = await _make_repo(tmp_path)
        async with session_factory() as session:
            repo = DbUserRepository(session)
            with pytest.raises(LookupError, match="not found"):
                await repo.update_user(
                    User(
                        id="missing-user",
                        email="missing@example.com",
                        password_hash=None,
                        system_role="user",
                        oauth_provider=None,
                        oauth_id=None,
                        needs_setup=False,
                        token_version=0,
                        created_time=datetime.now(UTC),
                        updated_time=None,
                    )
                )
        await engine.dispose()
