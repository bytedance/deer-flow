from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401 - register App-Key ORM rows
from deerflow.persistence.app_keys import AppKeyRepository
from deerflow.persistence.base import Base


@pytest.mark.asyncio
async def test_credential_lookup_is_database_backed_and_revocation_is_immediate():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = AppKeyRepository(session_factory)
    await repo.create_profile(
        app_id="review-api",
        name="Review API",
        description=None,
        capabilities={"agents": ["code-reviewer"]},
        actor_user_id="admin-1",
    )
    credential = await repo.generate_credential("review-api", actor_user_id="admin-1")

    assert credential is not None
    assert "app_key" in credential
    profile = await repo.find_active_profile_by_api_key(credential["app_key"])
    assert profile is not None
    assert profile["id"] == "review-api"
    assert await repo.revoke_credential(credential["key_hash"], actor_user_id="admin-1") is True
    assert await repo.find_active_profile_by_api_key(credential["app_key"]) is None

    updated = await repo.update_profile(
        "review-api",
        name="Updated Review API",
        description=None,
        disabled=True,
        capabilities={"agents": ["other-reviewer"], "models": ["fast-model"]},
        actor_user_id="admin-1",
    )
    assert updated is not None
    assert updated["disabled"] is True
    assert updated["agents"] == ["other-reviewer"]

    await engine.dispose()
