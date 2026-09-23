"""Owner isolation and disjoint concurrent preference updates."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def preference_repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/preferences.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([UserRow(id="alice", email="alice@example.com"), UserRow(id="bob", email="bob@example.com")])
        await session.commit()
    yield UserPreferencesRepository(sessions)
    await engine.dispose()


@pytest.mark.anyio
async def test_preferences_survive_repository_recreation_and_remain_owner_scoped(preference_repo):
    repo = preference_repo
    assert await repo.get("alice") == {}
    await repo.patch("alice", {"model_name": "model-a", "notification_enabled": False})
    assert await UserPreferencesRepository(repo.sessions).get("alice") == {"model_name": "model-a", "notification_enabled": False}
    assert await repo.get("bob") == {}
    await repo.patch("alice", {"model_name": None})
    assert await repo.get("alice") == {"model_name": None, "notification_enabled": False}


@pytest.mark.anyio
async def test_disjoint_updates_do_not_erase_each_other(preference_repo):
    await asyncio.gather(
        preference_repo.patch("alice", {"model_name": "new-model"}),
        preference_repo.patch("alice", {"notification_enabled": False}),
    )
    assert await preference_repo.get("alice") == {"model_name": "new-model", "notification_enabled": False}


@pytest.fixture
async def api(preference_repo, monkeypatch):
    from app.gateway.routers import user_preferences

    app = FastAPI()
    app.include_router(user_preferences.router)
    identity = SimpleNamespace(id="alice", source="session")

    @app.middleware("http")
    async def authenticated_session(request, call_next):
        if identity.id:
            request.state.user = SimpleNamespace(id=identity.id)
            request.state.auth_source = identity.source
        return await call_next(request)

    monkeypatch.setattr(user_preferences, "_repository", lambda: preference_repo)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.headers["X-Expected-User-Id"] = "alice"
        yield client, identity


@pytest.mark.anyio
async def test_preferences_api_partial_patch_reset_and_owner_isolation(api):
    client, identity = api
    path = "/api/v1/auth/preferences"
    assert (await client.patch(path, json={"notification_enabled": False, "mode": "pro"})).status_code == 204
    assert (await client.patch(path, json={"model_name": "model-a"})).status_code == 204
    assert (await client.get(path)).json() == {"notification_enabled": False, "model_name": "model-a", "mode": "pro", "reasoning_effort": None}
    assert (await client.patch(path, json={"mode": None})).status_code == 204
    identity.id = "bob"
    # A stale tab with Alice's expected identity must not write using Bob's cookie.
    assert (await client.patch(path, json={"mode": "ultra"})).status_code == 409
    assert (await client.get(path)).status_code == 409
    client.headers["X-Expected-User-Id"] = "bob"
    assert (await client.get(path)).json() == {"notification_enabled": None, "model_name": None, "mode": None, "reasoning_effort": None}
    identity.id = "alice"
    client.headers["X-Expected-User-Id"] = "alice"
    assert (await client.get(path)).json()["notification_enabled"] is False
    assert (await client.get(path)).json()["mode"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("body", [{"notification_enabled": "false"}, {"mode": "invalid"}, {"reasoning_effort": "max"}, {"model_name": "a" * 201}, {"context": {"github_token": "not-a-real-token"}}, {"user_id": "bob"}])
async def test_preferences_api_rejects_invalid_and_unrelated_fields(api, body):
    client, _ = api
    assert (await client.patch("/api/v1/auth/preferences", json=body)).status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["pat", "internal", "auth_disabled"])
async def test_preferences_requires_browser_session(api, source):
    client, identity = api
    identity.source = source
    assert (await client.get("/api/v1/auth/preferences")).status_code == 403
    assert (await client.patch("/api/v1/auth/preferences", json={})).status_code == 403


@pytest.mark.anyio
async def test_preferences_requires_authentication_and_expected_identity(api):
    client, identity = api
    del client.headers["X-Expected-User-Id"]
    assert (await client.get("/api/v1/auth/preferences")).status_code == 422
    client.headers["X-Expected-User-Id"] = "alice"
    identity.id = None
    assert (await client.get("/api/v1/auth/preferences")).status_code == 401


@pytest.mark.anyio
async def test_preferences_read_discards_only_malformed_fields(api, preference_repo):
    client, _ = api
    await preference_repo.patch("alice", {"notification_enabled": False, "mode": "invalid", "unknown": "ignored"})
    assert (await client.get("/api/v1/auth/preferences")).json() == {"notification_enabled": False, "model_name": None, "mode": None, "reasoning_effort": None}


def test_preferences_migration_preserves_existing_users_and_downgrades(tmp_path):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    revision = importlib.import_module("deerflow.persistence.migrations.versions.0023_user_preferences")
    engine = create_engine(f"sqlite:///{tmp_path}/migration.db")
    with engine.begin() as connection:
        UserRow.__table__.create(connection)
        connection.execute(UserRow.__table__.insert().values(id="alice", email="alice@example.com"))
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
            assert "user_preferences" in inspect(connection).get_table_names()
            connection.execute(text("INSERT INTO user_preferences (user_id, key, value) VALUES ('alice', 'mode', '\"pro\"')"))
            revision.upgrade()
            assert connection.execute(text("SELECT value FROM user_preferences WHERE user_id = 'alice'")).scalar() == '"pro"'
            revision.downgrade()
            revision.downgrade()
        assert "user_preferences" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT email FROM users WHERE id = 'alice'")).scalar() == "alice@example.com"
    engine.dispose()
