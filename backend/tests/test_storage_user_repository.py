from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("DEER_FLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from store.repositories import UserCreate, UserNotFoundError, build_user_repository
from store.repositories.models import User as UserModel


@asynccontextmanager
async def _session_factory(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "storage-users.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(UserModel.metadata.create_all)

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _create_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "user@example.com",
    system_role: str = "user",
    oauth_provider: str | None = None,
    oauth_id: str | None = None,
):
    async with session_factory() as session:
        repo = build_user_repository(session)
        user = await repo.create_user(
            UserCreate(
                id=str(uuid4()),
                email=email,
                password_hash="hash",
                system_role=system_role,  # type: ignore[arg-type]
                oauth_provider=oauth_provider,
                oauth_id=oauth_id,
            )
        )
        await session.commit()
        return user


def test_create_and_get_user_by_id_and_email(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            created = await _create_user(session_factory)

            async with session_factory() as session:
                repo = build_user_repository(session)

                by_id = await repo.get_user_by_id(created.id)
                by_email = await repo.get_user_by_email(created.email)

            assert by_id == created
            assert by_email == created
            assert created.system_role == "user"
            assert created.needs_setup is False
            assert created.token_version == 0

    asyncio.run(run())


def test_duplicate_email_raises_value_error(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            await _create_user(session_factory, email="dupe@example.com")

            async with session_factory() as session:
                repo = build_user_repository(session)
                with pytest.raises(ValueError, match="Email already registered"):
                    await repo.create_user(
                        UserCreate(
                            id=str(uuid4()),
                            email="dupe@example.com",
                            password_hash="hash",
                        )
                    )

    asyncio.run(run())


def test_oauth_lookup_and_plain_users_without_oauth(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            await _create_user(session_factory, email="local-1@example.com")
            await _create_user(session_factory, email="local-2@example.com")
            oauth_user = await _create_user(
                session_factory,
                email="oauth@example.com",
                oauth_provider="github",
                oauth_id="gh-123",
            )

            async with session_factory() as session:
                repo = build_user_repository(session)

                assert await repo.count_users() == 3
                assert await repo.get_user_by_oauth("github", "gh-123") == oauth_user
                assert await repo.get_user_by_oauth("github", "missing") is None

    asyncio.run(run())


def test_count_admins_and_get_first_admin(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            await _create_user(session_factory, email="user@example.com")
            admin = await _create_user(
                session_factory,
                email="admin@example.com",
                system_role="admin",
            )

            async with session_factory() as session:
                repo = build_user_repository(session)

                assert await repo.count_users() == 2
                assert await repo.count_admin_users() == 1
                assert await repo.get_first_admin() == admin

    asyncio.run(run())


def test_update_user_round_trips_token_version_and_setup_state(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            created = await _create_user(session_factory)
            updated = created.model_copy(
                update={
                    "email": "renamed@example.com",
                    "token_version": 4,
                    "needs_setup": True,
                }
            )

            async with session_factory() as session:
                repo = build_user_repository(session)
                saved = await repo.update_user(updated)
                await session.commit()

            async with session_factory() as session:
                repo = build_user_repository(session)
                fetched = await repo.get_user_by_id(created.id)

            assert saved.email == "renamed@example.com"
            assert fetched == updated

    asyncio.run(run())


def test_update_missing_user_raises(tmp_path):
    async def run() -> None:
        async with _session_factory(tmp_path) as session_factory:
            missing = UserCreate(id=str(uuid4()), email="missing@example.com")

            async with session_factory() as session:
                repo = build_user_repository(session)
                created_shape = await repo.create_user(missing)
                await session.rollback()

                with pytest.raises(UserNotFoundError):
                    await repo.update_user(created_shape)

    asyncio.run(run())
