from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.plugins.auth.domain.service import AuthService, AuthServiceError
from app.plugins.auth.storage.models import User as UserModel  # noqa: F401
from store.persistence import MappedBase


async def _make_service(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'auth-service.db'}",
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
    return engine, AuthService(session_factory)


class TestAuthService:
    @pytest.mark.anyio
    async def test_register_and_login_local(self, tmp_path):
        engine, service = await _make_service(tmp_path)
        try:
            created = await service.register("user@example.com", "Str0ng!Pass99")
            logged_in = await service.login_local("user@example.com", "Str0ng!Pass99")
        finally:
            await engine.dispose()

        assert created.email == "user@example.com"
        assert created.password_hash is not None
        assert logged_in.id == created.id

    @pytest.mark.anyio
    async def test_register_duplicate_email_raises(self, tmp_path):
        engine, service = await _make_service(tmp_path)
        try:
            await service.register("dupe@example.com", "Str0ng!Pass99")
            with pytest.raises(AuthServiceError) as exc_info:
                await service.register("dupe@example.com", "An0ther!Pass99")
        finally:
            await engine.dispose()

        assert exc_info.value.code.value == "email_already_exists"

    @pytest.mark.anyio
    async def test_initialize_admin_only_once(self, tmp_path):
        engine, service = await _make_service(tmp_path)
        try:
            admin = await service.initialize_admin("admin@example.com", "Str0ng!Pass99")
            with pytest.raises(AuthServiceError) as exc_info:
                await service.initialize_admin("other@example.com", "An0ther!Pass99")
        finally:
            await engine.dispose()

        assert admin.system_role == "admin"
        assert admin.needs_setup is False
        assert exc_info.value.code.value == "system_already_initialized"

    @pytest.mark.anyio
    async def test_change_password_updates_token_version_and_clears_setup(self, tmp_path):
        engine, service = await _make_service(tmp_path)
        try:
            user = await service.register("setup@example.com", "Str0ng!Pass99")
            user.needs_setup = True
            updated = await service.change_password(
                user,
                current_password="Str0ng!Pass99",
                new_password="N3wer!Pass99",
                new_email="final@example.com",
            )
            relogged = await service.login_local("final@example.com", "N3wer!Pass99")
        finally:
            await engine.dispose()

        assert updated.email == "final@example.com"
        assert updated.needs_setup is False
        assert updated.token_version == 1
        assert relogged.id == updated.id
