"""User-level settings persistence contract (issue #2595)."""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
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
from app.gateway.auth.repositories import sqlite as sqlite_repository
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import user_preferences as user_preferences_router
from app.gateway.routers.user_preferences import (
    EXPECTED_USER_ID_HEADER,
    UserPreferencesInitializeRequest,
    UserPreferencesPatchRequest,
    get_user_preferences,
    patch_user_preferences,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.user.model import UserRow


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


async def _overwrite_stored_preferences(user_id: str, settings: dict) -> None:
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        await session.execute(sa.update(UserRow).where(UserRow.id == user_id).values(preferences=settings))
        await session.commit()


def _load_user_preferences_migration() -> ModuleType:
    migration_path = Path(__file__).parents[1] / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "versions" / "0017_user_preferences.py"
    spec = importlib.util.spec_from_file_location("migration_0017_user_preferences", migration_path)
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


class _PreferenceReadBarrier:
    """Hold the first two preference readers on distinct SQLite snapshots."""

    def __init__(self) -> None:
        self._arrivals = 0
        self._ready = asyncio.Event()
        self._writer_committed = asyncio.Event()
        self.connection_ids: set[int] = set()

    async def wait(self, connection_id: int) -> bool:
        self.connection_ids.add(connection_id)
        self._arrivals += 1
        position = self._arrivals
        if self._arrivals >= 2:
            self._ready.set()
        await self._ready.wait()
        if position == 2:
            await self._writer_committed.wait()
        return position == 1

    def writer_committed(self) -> None:
        self._writer_committed.set()


class _BarrierSession:
    """AsyncSession proxy that pauses after its first preference SELECT."""

    def __init__(self, session, barrier: _PreferenceReadBarrier) -> None:
        self._session = session
        self._barrier = barrier
        self._first_execute = True
        self._is_first_writer = False

    async def __aenter__(self):
        await self._session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self._session.__aexit__(exc_type, exc_value, traceback)

    def __getattr__(self, name: str):
        return getattr(self._session, name)

    async def commit(self) -> None:
        await self._session.commit()
        if self._is_first_writer:
            self._barrier.writer_committed()

    async def execute(self, statement, *args, **kwargs):
        if not self._first_execute:
            return await self._session.execute(statement, *args, **kwargs)

        self._first_execute = False
        # Python's sqlite3 legacy transaction mode does not always begin a
        # database transaction for SELECT. An explicit BEGIN makes each SELECT
        # retain a real WAL read snapshot, matching modern transaction mode and
        # reproducing the read-to-write upgrade race deterministically.
        await self._session.execute(sa.text("BEGIN"))
        result = await self._session.execute(statement, *args, **kwargs)
        connection = await self._session.connection()
        dbapi_connection = connection.sync_connection.connection.dbapi_connection
        self._is_first_writer = await self._barrier.wait(id(dbapi_connection))
        return result


@pytest.mark.asyncio
async def test_concurrent_sqlite_snapshot_busy_retries_without_losing_patch(user_repository: SQLiteUserRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    user = await _create_user(user_repository, "snapshot-busy@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())

    session_factory = get_session_factory()
    assert session_factory is not None
    barrier = _PreferenceReadBarrier()
    repository = SQLiteUserRepository(lambda: _BarrierSession(session_factory(), barrier))  # type: ignore[arg-type]
    busy_error_codes: list[int | None] = []
    original_is_busy = sqlite_repository._is_sqlite_busy_error

    def capture_busy_error(exc) -> bool:
        busy_error_codes.append(getattr(exc.orig, "sqlite_errorcode", None))
        return original_is_busy(exc)

    monkeypatch.setattr(sqlite_repository, "_is_sqlite_busy_error", capture_busy_error)

    await asyncio.gather(
        repository.merge_user_preferences(
            str(user.id),
            {"notification": {"enabled": False}},
        ),
        repository.merge_user_preferences(
            str(user.id),
            {"tokenUsage": {"inlineMode": "off"}},
        ),
    )

    stored, revision = await user_repository.get_user_preferences(str(user.id))
    assert len(barrier.connection_ids) == 2
    assert busy_error_codes == [sqlite3.SQLITE_BUSY_SNAPSHOT]
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
async def test_get_resets_an_invalid_persisted_record(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "invalid-get@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())
    await _overwrite_stored_preferences(str(user.id), {"context": {}})
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await get_user_preferences(request)  # type: ignore[arg-type]

    assert response.settings is None
    assert response.revision == 2
    assert await user_repository.get_user_preferences(str(user.id)) == (None, 2)


@pytest.mark.asyncio
async def test_patch_resets_an_invalid_merged_record_for_client_reinitialization(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "invalid-patch@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())
    await _overwrite_stored_preferences(str(user.id), {"context": {}})
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await patch_user_preferences(
        UserPreferencesPatchRequest.model_validate({"context": {"mode": "pro"}}),
        request,  # type: ignore[arg-type]
    )

    assert response.settings is None
    assert response.revision == 3
    assert await user_repository.get_user_preferences(str(user.id)) == (None, 3)


@pytest.mark.asyncio
async def test_patch_resets_structurally_corrupt_record_before_merging(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "structurally-invalid-patch@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())
    await _overwrite_stored_preferences(str(user.id), {"context": []})
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await patch_user_preferences(
        UserPreferencesPatchRequest.model_validate({"context": {"mode": "pro"}}),
        request,  # type: ignore[arg-type]
    )

    assert response.settings is None
    assert response.revision == 2
    assert await user_repository.get_user_preferences(str(user.id)) == (None, 2)


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
        connection.execute(
            sa.text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": "existing-user", "email": "existing@example.com"},
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        assert {"preferences", "preferences_revision"} <= columns
        assert connection.execute(
            sa.text("SELECT preferences, preferences_revision FROM users WHERE id = 'existing-user'"),
        ).one() == (None, 0)

        with Operations.context(context):
            migration.downgrade()
            migration.downgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        assert columns == {"id", "email"}

        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()

        assert connection.execute(
            sa.text("SELECT preferences, preferences_revision FROM users WHERE id = 'existing-user'"),
        ).one() == (None, 0)

        with Operations.context(context):
            migration.downgrade()
            migration.downgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        assert columns == {"id", "email"}
