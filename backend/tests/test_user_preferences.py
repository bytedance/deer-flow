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
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite as sqlite_dialect

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
    initialize_user_preferences,
    patch_user_preferences,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.user.model import MALFORMED_USER_PREFERENCES, UserRow


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


async def _store_raw_preferences(user_id: str, settings: object, revision: int) -> None:
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        await session.execute(
            sa.update(UserRow).where(UserRow.id == user_id).values(preferences=settings, preferences_revision=revision),
        )
        await session.commit()


async def _store_malformed_preferences(user_id: str, raw_settings: str, revision: int) -> None:
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        await session.execute(
            sa.text(
                "UPDATE users SET preferences = :preferences, preferences_revision = :revision WHERE id = :user_id",
            ),
            {
                "preferences": raw_settings,
                "revision": revision,
                "user_id": user_id,
            },
        )
        await session.commit()


async def _read_raw_preferences(user_id: str) -> tuple[object, bool, int]:
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        return (
            await session.execute(
                sa.text(
                    "SELECT preferences, preferences IS NULL, preferences_revision FROM users WHERE id = :user_id",
                ),
                {"user_id": user_id},
            )
        ).one()


def _load_user_preferences_migration() -> ModuleType:
    migration_path = Path(__file__).parents[1] / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "versions" / "0018_user_preferences.py"
    spec = importlib.util.spec_from_file_location("migration_0018_user_preferences", migration_path)
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
async def test_json_null_initialization_is_first_writer_wins(user_repository: SQLiteUserRepository) -> None:
    user = await _create_user(user_repository, "json-null-race@example.com")
    user_id = str(user.id)
    await _store_raw_preferences(user_id, sa.JSON.NULL, revision=7)

    (first, first_revision), (second, second_revision) = await asyncio.gather(
        user_repository.initialize_user_preferences(
            user_id,
            _full_preferences(model_name="first-json-null"),
        ),
        user_repository.initialize_user_preferences(
            user_id,
            _full_preferences(model_name="second-json-null"),
        ),
    )

    assert first["context"]["model_name"] in {"first-json-null", "second-json-null"}
    assert second == first
    assert first_revision == 8
    assert second_revision == first_revision
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert (stored, revision) == (first, 8)


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

    def has_writer_committed(self) -> bool:
        return self._writer_committed.is_set()


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


class _RepairBarrierSession:
    """Pause two invalid-record repairs after each captures a WAL snapshot."""

    def __init__(self, session, barrier: _PreferenceReadBarrier) -> None:
        self._session = session
        self._barrier = barrier
        self._execute_count = 0
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
        self._execute_count += 1
        if self._execute_count == 1:
            # The initial first-writer-wins UPDATE cannot match an invalid,
            # non-NULL record. End that no-op write transaction so both real
            # SQLite connections can establish independent read snapshots.
            result = await self._session.execute(statement, *args, **kwargs)
            assert result.rowcount == 0
            await self._session.rollback()
            return result
        if self._execute_count == 2 and not self._barrier.has_writer_committed():
            await self._session.execute(sa.text("BEGIN"))
            result = await self._session.execute(statement, *args, **kwargs)
            connection = await self._session.connection()
            dbapi_connection = connection.sync_connection.connection.dbapi_connection
            self._is_first_writer = await self._barrier.wait(id(dbapi_connection))
            return result
        return await self._session.execute(statement, *args, **kwargs)


class _CasMissResult:
    def __init__(self, row=None, *, rowcount: int | None = None) -> None:
        self._row = row
        self.rowcount = rowcount

    def one_or_none(self):
        return self._row


class _CasMissSession:
    def __init__(self, attempts: list[int]) -> None:
        self._attempts = attempts

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, statement, *args, **kwargs):
        if isinstance(statement, sa.sql.Select):
            return _CasMissResult((_full_preferences(), 1, False))
        self._attempts.append(1)
        return _CasMissResult(rowcount=0)

    async def rollback(self) -> None:
        return None


class _RepairRaceSession:
    """Script an invalid-record repair losing its revision CAS."""

    def __init__(self, responses: list[_CasMissResult]) -> None:
        self._responses = responses
        self.rollback_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, statement, *args, **kwargs):
        assert self._responses, f"Unexpected statement after scripted repair race: {statement}"
        return self._responses.pop(0)

    async def rollback(self) -> None:
        self.rollback_count += 1


class _BusyInitializeSession:
    def __init__(self, attempts: list[int], rollbacks: list[int], error_code: int) -> None:
        self._attempts = attempts
        self._rollbacks = rollbacks
        self._error_code = error_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, statement, *args, **kwargs):
        self._attempts.append(1)
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = self._error_code
        raise sa.exc.OperationalError(
            str(statement),
            {},
            error,
        )

    async def rollback(self) -> None:
        self._rollbacks.append(1)


@pytest.mark.asyncio
async def test_invalid_preference_repair_cas_loser_returns_valid_winner() -> None:
    invalid = {"context": {}}
    winner = _full_preferences(model_name="winner")
    session = _RepairRaceSession(
        [
            _CasMissResult(rowcount=0),
            _CasMissResult((invalid, 7, False)),
            _CasMissResult(rowcount=0),
            _CasMissResult((winner, 8, False)),
        ]
    )
    repository = SQLiteUserRepository(lambda: session)  # type: ignore[arg-type]

    stored, revision = await repository.initialize_user_preferences(
        "user-id",
        _full_preferences(model_name="loser"),
        existing_is_valid=lambda settings: settings == winner,
    )

    assert stored == winner
    assert stored is not winner
    assert revision == 8
    assert session.rollback_count == 1
    assert session._responses == []


@pytest.mark.asyncio
async def test_preference_initialization_busy_snapshot_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    rollbacks: list[int] = []
    delays = AsyncMock()
    monkeypatch.setattr(sqlite_repository, "_sleep_before_preference_retry", delays)
    repository = SQLiteUserRepository(
        lambda: _BusyInitializeSession(attempts, rollbacks, sqlite3.SQLITE_BUSY_SNAPSHOT),  # type: ignore[arg-type]
    )

    with pytest.raises(sqlite_repository.UserPreferencesWriteConflict, match="initialization.*did not settle"):
        await repository.initialize_user_preferences(
            "user-id",
            _full_preferences(),
            existing_is_valid=user_preferences_router._stored_preferences_are_valid,
        )

    assert len(attempts) == sqlite_repository._PREFERENCE_WRITE_MAX_ATTEMPTS
    assert len(rollbacks) == sqlite_repository._PREFERENCE_WRITE_MAX_ATTEMPTS
    assert [call.args for call in delays.await_args_list] == [(0,), (1,), (2,), (3,)]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["initialize", "merge"])
async def test_preference_plain_busy_propagates_without_retry(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    rollbacks: list[int] = []
    delays = AsyncMock()
    monkeypatch.setattr(sqlite_repository, "_sleep_before_preference_retry", delays)
    repository = SQLiteUserRepository(
        lambda: _BusyInitializeSession(attempts, rollbacks, sqlite3.SQLITE_BUSY),  # type: ignore[arg-type]
    )

    with pytest.raises(sa.exc.OperationalError) as exc_info:
        if operation == "initialize":
            await repository.initialize_user_preferences(
                "user-id",
                _full_preferences(),
                existing_is_valid=user_preferences_router._stored_preferences_are_valid,
            )
        else:
            await repository.merge_user_preferences(
                "user-id",
                {"notification": {"enabled": False}},
                current_is_valid=user_preferences_router._stored_preferences_are_valid,
            )

    assert getattr(exc_info.value.orig, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY
    assert attempts == [1]
    assert rollbacks == []
    delays.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_sqlite_invalid_preference_repairs_return_one_winner(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "concurrent-repair@example.com")
    user_id = str(user.id)
    await _store_raw_preferences(user_id, {"context": {}}, revision=7)

    session_factory = get_session_factory()
    assert session_factory is not None
    barrier = _PreferenceReadBarrier()
    repository = SQLiteUserRepository(lambda: _RepairBarrierSession(session_factory(), barrier))  # type: ignore[arg-type]
    busy_error_codes: list[int | None] = []
    delays = AsyncMock()
    original_is_busy = sqlite_repository._is_sqlite_busy_snapshot_error

    def capture_busy_error(exc) -> bool:
        busy_error_codes.append(getattr(exc.orig, "sqlite_errorcode", None))
        return original_is_busy(exc)

    monkeypatch.setattr(sqlite_repository, "_is_sqlite_busy_snapshot_error", capture_busy_error)
    monkeypatch.setattr(sqlite_repository, "_sleep_before_preference_retry", delays)

    first, second = await asyncio.gather(
        repository.initialize_user_preferences(
            user_id,
            _full_preferences(model_name="first-repair"),
            existing_is_valid=user_preferences_router._stored_preferences_are_valid,
        ),
        repository.initialize_user_preferences(
            user_id,
            _full_preferences(model_name="second-repair"),
            existing_is_valid=user_preferences_router._stored_preferences_are_valid,
        ),
    )

    assert len(barrier.connection_ids) == 2
    assert busy_error_codes == [sqlite3.SQLITE_BUSY_SNAPSHOT]
    delays.assert_awaited_once_with(0)
    assert first == second
    assert first[0]["context"]["model_name"] in {"first-repair", "second-repair"}
    assert first[1] == 8
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert (stored, revision) == first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("winner_row", "error_type", "message"),
    [
        (None, sqlite_repository.UserNotFoundError, "no longer exists"),
        ((None, 8, False), sqlite_repository.UserPreferencesWriteConflict, "being initialized"),
        (({"context": {"still": "invalid"}}, 8, False), sqlite_repository.UserPreferencesWriteConflict, "changed while being repaired"),
    ],
)
async def test_invalid_preference_repair_cas_loser_preserves_precise_errors(
    winner_row,
    error_type: type[Exception],
    message: str,
) -> None:
    session = _RepairRaceSession(
        [
            _CasMissResult(rowcount=0),
            _CasMissResult(({"context": {}}, 7, False)),
            _CasMissResult(rowcount=0),
            _CasMissResult(winner_row),
        ]
    )
    repository = SQLiteUserRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(error_type, match=message):
        await repository.initialize_user_preferences(
            "user-id",
            _full_preferences(model_name="loser"),
            existing_is_valid=lambda settings: settings == _full_preferences(model_name="winner"),
        )

    assert session.rollback_count == 1
    assert session._responses == []


@pytest.mark.asyncio
async def test_preference_cas_retries_back_off_before_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    delays = AsyncMock()
    monkeypatch.setattr(sqlite_repository, "_sleep_before_preference_retry", delays)
    repository = SQLiteUserRepository(lambda: _CasMissSession(attempts))  # type: ignore[arg-type]

    with pytest.raises(sqlite_repository.UserPreferencesWriteConflict):
        await repository.merge_user_preferences(
            "user-id",
            {"notification": {"enabled": False}},
        )

    assert len(attempts) == sqlite_repository._PREFERENCE_WRITE_MAX_ATTEMPTS
    assert [call.args for call in delays.await_args_list] == [(0,), (1,), (2,), (3,)]


@pytest.mark.asyncio
async def test_concurrent_sqlite_snapshot_busy_retries_without_losing_patch(user_repository: SQLiteUserRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    user = await _create_user(user_repository, "snapshot-busy@example.com")
    await user_repository.initialize_user_preferences(str(user.id), _full_preferences())

    session_factory = get_session_factory()
    assert session_factory is not None
    barrier = _PreferenceReadBarrier()
    repository = SQLiteUserRepository(lambda: _BarrierSession(session_factory(), barrier))  # type: ignore[arg-type]
    busy_error_codes: list[int | None] = []
    delays = AsyncMock()
    original_is_busy = sqlite_repository._is_sqlite_busy_snapshot_error

    def capture_busy_error(exc) -> bool:
        busy_error_codes.append(getattr(exc.orig, "sqlite_errorcode", None))
        return original_is_busy(exc)

    monkeypatch.setattr(sqlite_repository, "_is_sqlite_busy_snapshot_error", capture_busy_error)
    monkeypatch.setattr(sqlite_repository, "_sleep_before_preference_retry", delays)

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
    delays.assert_awaited_once_with(0)
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


def test_uninitialized_preferences_predicate_compiles_for_sqlite_and_postgres() -> None:
    statement = sa.select(UserRow.id).where(sqlite_repository._preferences_are_uninitialized())

    for dialect in (sqlite_dialect.dialect(), postgresql.dialect()):
        compiled = str(statement.compile(dialect=dialect))
        assert "users.preferences IS NULL" in compiled
        assert "CAST(users.preferences AS TEXT)" in compiled


def test_lenient_preferences_json_processor_preserves_dialect_native_values() -> None:
    column_type = UserRow.__table__.c.preferences.type

    sqlite = sqlite_dialect.dialect()
    sqlite_processor = column_type.dialect_impl(sqlite).result_processor(sqlite, None)
    assert sqlite_processor is not None
    assert sqlite_processor('{"notification":{"enabled":true}}') == {"notification": {"enabled": True}}
    assert sqlite_processor("{broken") is MALFORMED_USER_PREFERENCES
    assert sqlite_processor("null") is None

    postgres = postgresql.dialect()
    postgres_processor = column_type.dialect_impl(postgres).result_processor(postgres, None)
    native_value = {"notification": {"enabled": True}}
    processed = native_value if postgres_processor is None else postgres_processor(native_value)
    assert processed is native_value


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


@pytest.mark.asyncio
async def test_invalid_stored_preferences_degrade_on_get_and_self_heal_on_put(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "repair@example.com")
    user_id = str(user.id)
    await _store_raw_preferences(user_id, {"context": {}}, revision=7)
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await get_user_preferences(request)  # type: ignore[arg-type]

    assert response.settings is None
    assert response.revision == 7

    repaired = await initialize_user_preferences(
        UserPreferencesInitializeRequest.model_validate(
            {"settings": _full_preferences(model_name="repaired-model")},
        ),
        request,  # type: ignore[arg-type]
    )

    assert repaired.settings is not None
    assert repaired.settings.context.model_name == "repaired-model"
    assert repaired.revision == 8
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert stored == _full_preferences(model_name="repaired-model")
    assert revision == 8


@pytest.mark.asyncio
async def test_json_null_preferences_degrade_on_get_and_self_heal_on_put(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "json-null-repair@example.com")
    user_id = str(user.id)
    await _store_raw_preferences(user_id, sa.JSON.NULL, revision=7)
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        raw_value = await session.scalar(
            sa.select(sa.cast(UserRow.preferences, sa.String)).where(UserRow.id == user_id),
        )
        sql_null = await session.scalar(
            sa.select(UserRow.preferences.is_(None)).where(UserRow.id == user_id),
        )
    assert raw_value == "null"
    assert sql_null is False

    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await get_user_preferences(request)  # type: ignore[arg-type]

    assert response.settings is None
    assert response.revision == 7

    repaired = await initialize_user_preferences(
        UserPreferencesInitializeRequest.model_validate(
            {"settings": _full_preferences(model_name="json-null-repaired")},
        ),
        request,  # type: ignore[arg-type]
    )

    assert repaired.settings is not None
    assert repaired.settings.context.model_name == "json-null-repaired"
    assert repaired.revision == 8
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert stored == _full_preferences(model_name="json-null-repaired")
    assert revision == 8


@pytest.mark.asyncio
async def test_malformed_json_preferences_do_not_break_auth_and_self_heal_on_put(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "malformed-json-repair@example.com")
    user_id = str(user.id)
    await _store_malformed_preferences(user_id, "{broken", revision=7)
    assert await _read_raw_preferences(user_id) == ("{broken", False, 7)

    loaded_user = await user_repository.get_user_by_id(user_id)
    assert loaded_user is not None
    assert loaded_user.id == user.id

    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    response = await get_user_preferences(request)  # type: ignore[arg-type]

    assert response.settings is None
    assert response.revision == 7

    repaired = await initialize_user_preferences(
        UserPreferencesInitializeRequest.model_validate(
            {"settings": _full_preferences(model_name="malformed-json-repaired")},
        ),
        request,  # type: ignore[arg-type]
    )

    assert repaired.settings is not None
    assert repaired.settings.context.model_name == "malformed-json-repaired"
    assert repaired.revision == 8
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert stored == _full_preferences(model_name="malformed-json-repaired")
    assert revision == 8


@pytest.mark.asyncio
async def test_patch_rejects_invalid_stored_preferences_without_mutating_them(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "invalid-patch@example.com")
    user_id = str(user.id)
    invalid = {"context": {}}
    await _store_raw_preferences(user_id, invalid, revision=4)
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    with pytest.raises(HTTPException) as exc_info:
        await patch_user_preferences(
            UserPreferencesPatchRequest.model_validate(
                {"notification": {"enabled": False}},
            ),
            request,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    stored, revision = await user_repository.get_user_preferences(user_id)
    assert stored == invalid
    assert revision == 4


@pytest.mark.asyncio
async def test_patch_rejects_json_null_preferences_without_mutating_them(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "json-null-patch@example.com")
    user_id = str(user.id)
    await _store_raw_preferences(user_id, sa.JSON.NULL, revision=4)
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    with pytest.raises(HTTPException) as exc_info:
        await patch_user_preferences(
            UserPreferencesPatchRequest.model_validate(
                {"notification": {"enabled": False}},
            ),
            request,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        raw_value, sql_null, revision = (
            await session.execute(
                sa.select(
                    sa.cast(UserRow.preferences, sa.String),
                    UserRow.preferences.is_(None),
                    UserRow.preferences_revision,
                ).where(UserRow.id == user_id),
            )
        ).one()
    assert (raw_value, sql_null, revision) == ("null", False, 4)


@pytest.mark.asyncio
async def test_patch_rejects_malformed_json_preferences_without_mutating_them(
    user_repository: SQLiteUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(user_repository, "malformed-json-patch@example.com")
    user_id = str(user.id)
    await _store_malformed_preferences(user_id, "{broken", revision=4)
    request = SimpleNamespace(
        state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION),
        cookies={},
        headers={},
    )
    monkeypatch.setattr(user_preferences_router, "get_user_repository", lambda: user_repository)

    with pytest.raises(HTTPException) as exc_info:
        await patch_user_preferences(
            UserPreferencesPatchRequest.model_validate(
                {"notification": {"enabled": False}},
            ),
            request,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert await _read_raw_preferences(user_id) == ("{broken", False, 4)


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
