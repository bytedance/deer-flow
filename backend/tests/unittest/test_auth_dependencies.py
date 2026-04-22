from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.plugins.auth.domain.config import AuthConfig
from app.plugins.auth.security.dependencies import (
    get_current_user_from_request,
    get_current_user_id,
    get_optional_user_from_request,
)
from app.plugins.auth.domain.jwt import create_access_token
from app.plugins.auth.runtime.config_state import set_auth_config
from app.plugins.auth.storage import DbUserRepository, UserCreate
from store.persistence import MappedBase
from app.plugins.auth.storage.models import User as UserModel  # noqa: F401

_TEST_SECRET = "test-secret-auth-dependencies-min-32"


@pytest.fixture(autouse=True)
def _setup_auth_config():
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    yield
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))


async def _make_request(tmp_path, *, cookie: str | None = None, users: list[UserCreate] | None = None):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'auth-deps.db'}",
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
    session = session_factory()
    if users:
        repo = DbUserRepository(session)
        for user in users:
            await repo.create_user(user)
        await session.commit()
    request = SimpleNamespace(
        cookies={"access_token": cookie} if cookie is not None else {},
        state=SimpleNamespace(_auth_session=session),
    )
    return request, session, engine


class TestAuthDependencies:
    @pytest.mark.anyio
    async def test_no_cookie_returns_401(self, tmp_path):
        request, session, engine = await _make_request(tmp_path)
        try:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_request(request)
        finally:
            await session.close()
            await engine.dispose()

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "not_authenticated"

    @pytest.mark.anyio
    async def test_invalid_token_returns_401(self, tmp_path):
        request, session, engine = await _make_request(tmp_path, cookie="garbage")
        try:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_request(request)
        finally:
            await session.close()
            await engine.dispose()

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "token_invalid"

    @pytest.mark.anyio
    async def test_missing_user_returns_401(self, tmp_path):
        token = create_access_token("missing-user", token_version=0)
        request, session, engine = await _make_request(tmp_path, cookie=token)
        try:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_request(request)
        finally:
            await session.close()
            await engine.dispose()

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "user_not_found"

    @pytest.mark.anyio
    async def test_token_version_mismatch_returns_401(self, tmp_path):
        token = create_access_token("user-1", token_version=0)
        request, session, engine = await _make_request(
            tmp_path,
            cookie=token,
            users=[
                UserCreate(
                    id="user-1",
                    email="user1@example.com",
                    token_version=2,
                )
            ],
        )
        try:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_request(request)
        finally:
            await session.close()
            await engine.dispose()

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "token_invalid"

    @pytest.mark.anyio
    async def test_valid_token_returns_user(self, tmp_path):
        token = create_access_token("user-2", token_version=3)
        request, session, engine = await _make_request(
            tmp_path,
            cookie=token,
            users=[
                UserCreate(
                    id="user-2",
                    email="user2@example.com",
                    token_version=3,
                )
            ],
        )
        try:
            user = await get_current_user_from_request(request)
            user_id = await get_current_user_id(request)
        finally:
            await session.close()
            await engine.dispose()

        assert user.id == "user-2"
        assert user.email == "user2@example.com"
        assert user_id == "user-2"

    @pytest.mark.anyio
    async def test_optional_user_returns_none_on_failure(self, tmp_path):
        request, session, engine = await _make_request(tmp_path, cookie="bad-token")
        try:
            user = await get_optional_user_from_request(request)
        finally:
            await session.close()
            await engine.dispose()

        assert user is None
