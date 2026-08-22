"""User-level settings persistence contract (issue #2595)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import user_preferences as user_preferences_router
from app.gateway.routers.user_preferences import (
    EXPECTED_USER_ID_HEADER,
    UserPreferencesInitializeRequest,
    UserPreferencesPatchRequest,
    get_user_preferences,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine


def _full_preferences(*, model_name: str = "model-a") -> dict:
    return {
        "notification": {"enabled": True},
        "tokenUsage": {"headerTotal": True, "inlineMode": "per_turn"},
        "context": {
            "model_name": model_name,
            "mode": "thinking",
            "reasoning_effort": "medium",
        },
    }


@pytest_asyncio.fixture
async def user_repository(tmp_path: Path):
    db_path = tmp_path / "preferences.db"
    await init_engine(
        "sqlite",
        url=f"sqlite+aiosqlite:///{db_path}",
        sqlite_dir=str(tmp_path),
    )
    try:
        session_factory = get_session_factory()
        assert session_factory is not None
        yield SQLiteUserRepository(session_factory)
    finally:
        await close_engine()


async def _create_user(repository: SQLiteUserRepository, email: str) -> User:
    user = User(id=uuid4(), email=email, password_hash="hash")
    await repository.create_user(user)
    return user


def _load_user_preferences_migration() -> ModuleType:
    migration_path = Path(__file__).parents[1] / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "versions" / "0015_user_preferences.py"
    spec = importlib.util.spec_from_file_location("migration_0015_user_preferences", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_preferences_are_isolated_by_authenticated_user(user_repository: SQLiteUserRepository) -> None:
    alice = await _create_user(user_repository, "alice@example.com")
    bob = await _create_user(user_repository, "bob@example.com")

    await user_repository.initialize_user_preferences(str(alice.id), _full_preferences(model_name="alice-model"))
    await user_repository.initialize_user_preferences(str(bob.id), _full_preferences(model_name="bob-model"))

    alice_preferences, _alice_revision = await user_repository.get_user_preferences(str(alice.id))
    bob_preferences, _bob_revision = await user_repository.get_user_preferences(str(bob.id))

    assert alice_preferences is not None
    assert bob_preferences is not None
    assert alice_preferences["context"]["model_name"] == "alice-model"
    assert bob_preferences["context"]["model_name"] == "bob-model"


@pytest.mark.asyncio
async def test_initialization_is_first_writer_wins(user_repository: SQLiteUserRepository) -> None:
    user = await _create_user(user_repository, "migration@example.com")

    (first, first_revision), (second, second_revision) = await asyncio.gather(
        user_repository.initialize_user_preferences(
            str(user.id),
            _full_preferences(model_name="first"),
        ),
        user_repository.initialize_user_preferences(
            str(user.id),
            _full_preferences(model_name="second"),
        ),
    )

    assert first["context"]["model_name"] in {"first", "second"}
    assert second["context"]["model_name"] == first["context"]["model_name"]
    assert first_revision == 1
    assert second_revision == first_revision


@pytest.mark.asyncio
async def test_partial_update_merges_nested_sections(user_repository: SQLiteUserRepository) -> None:
    user = await _create_user(user_repository, "merge@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())

    merged, revision = await user_repository.merge_user_preferences(
        str(user.id),
        {
            "tokenUsage": {"inlineMode": "step_debug"},
            "context": {"reasoning_effort": "high"},
        },
    )

    assert revision == 2
    assert merged == {
        "notification": {"enabled": True},
        "tokenUsage": {"headerTotal": True, "inlineMode": "step_debug"},
        "context": {
            "model_name": "model-a",
            "mode": "thinking",
            "reasoning_effort": "high",
        },
    }


@pytest.mark.asyncio
async def test_patch_can_clear_optional_context_values(user_repository: SQLiteUserRepository) -> None:
    user = await _create_user(user_repository, "clear@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())

    merged, _revision = await user_repository.merge_user_preferences(
        str(user.id),
        {"context": {"model_name": None, "reasoning_effort": None}},
    )

    assert "model_name" not in merged["context"]
    assert "reasoning_effort" not in merged["context"]
    assert merged["context"]["mode"] == "thinking"


@pytest.mark.asyncio
async def test_concurrent_disjoint_updates_do_not_lose_fields(user_repository: SQLiteUserRepository) -> None:
    user = await _create_user(user_repository, "concurrent@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())

    await asyncio.gather(
        user_repository.merge_user_preferences(
            str(user.id),
            {"notification": {"enabled": False}},
        ),
        user_repository.merge_user_preferences(
            str(user.id),
            {"tokenUsage": {"inlineMode": "off"}},
        ),
    )

    stored, revision = await user_repository.get_user_preferences(str(user.id))
    assert stored is not None
    assert stored["notification"]["enabled"] is False
    assert stored["tokenUsage"]["inlineMode"] == "off"
    assert revision == 3


def test_preferences_schema_rejects_unknown_private_or_system_fields() -> None:
    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"context": {"thread_id": "private-thread"}},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"notification": {"permission": "granted"}},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"token": "secret"},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"user_id": str(uuid4()), "notification": {"enabled": False}},
        )


def test_preferences_schema_rejects_oversized_or_invalid_values() -> None:
    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"context": {"model_name": "x" * 257}},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"tokenUsage": {"inlineMode": "verbose"}},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate(
            {"notification": {"enabled": "yes"}},
        )

    with pytest.raises(ValidationError):
        UserPreferencesPatchRequest.model_validate({"notification": None})


def test_initialize_requires_complete_valid_base_settings() -> None:
    request = UserPreferencesInitializeRequest.model_validate({"settings": _full_preferences()})
    assert request.settings.context.model_name == "model-a"

    with pytest.raises(ValidationError):
        UserPreferencesInitializeRequest.model_validate(
            {"settings": {"context": {"model_name": "model-a"}}},
        )


@pytest.mark.asyncio
async def test_route_derives_owner_from_authenticated_request(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(id=uuid4(), email="owner@example.com", password_hash="hash")
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    repository = SimpleNamespace(
        get_user_preferences=AsyncMock(
            return_value=(_full_preferences(model_name="owner-model"), 3),
        ),
    )
    monkeypatch.setattr(
        "app.gateway.routers.user_preferences.get_user_repository",
        lambda: repository,
    )

    response = await get_user_preferences(request)  # type: ignore[arg-type]

    repository.get_user_preferences.assert_awaited_once_with(str(user.id))
    assert response.settings is not None
    assert response.settings.context.model_name == "owner-model"


@pytest.mark.asyncio
async def test_route_rejects_a_stale_tab_after_the_session_owner_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    current_user = User(id=uuid4(), email="current@example.com", password_hash="hash")
    stale_user_id = str(uuid4())
    request = SimpleNamespace(
        state=SimpleNamespace(user=current_user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={EXPECTED_USER_ID_HEADER: stale_user_id},
    )
    repository = SimpleNamespace(get_user_preferences=AsyncMock())
    monkeypatch.setattr(
        "app.gateway.routers.user_preferences.get_user_repository",
        lambda: repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_user_preferences(request)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    repository.get_user_preferences.assert_not_awaited()


def test_http_response_keeps_absent_record_explicit_and_omits_unset_context_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(id=uuid4(), email="wire@example.com", password_hash="hash")
    repository = SimpleNamespace(get_user_preferences=AsyncMock(return_value=(None, 0)))
    monkeypatch.setattr(user_preferences_router, "get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: repository)
    app = FastAPI()
    app.include_router(user_preferences_router.router)

    response = TestClient(app).get("/api/user-preferences")

    assert response.status_code == 200
    assert response.json() == {"settings": None, "revision": 0}

    repository.get_user_preferences = AsyncMock(
        return_value=(
            {
                "notification": {"enabled": True},
                "tokenUsage": {"headerTotal": True, "inlineMode": "per_turn"},
                "context": {},
            },
            1,
        )
    )

    response = TestClient(app).get("/api/user-preferences")

    assert response.status_code == 200
    assert response.json() == {
        "settings": {
            "notification": {"enabled": True},
            "tokenUsage": {"headerTotal": True, "inlineMode": "per_turn"},
            "context": {},
        },
        "revision": 1,
    }


def test_user_preferences_migration_is_idempotent_and_reversible(tmp_path: Path) -> None:
    migration = _load_user_preferences_migration()

    db_path = tmp_path / "migration.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL)"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        assert {"preferences", "preferences_revision"} <= columns

        with Operations.context(context):
            migration.downgrade()
            migration.downgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        assert columns == {"id", "email"}
