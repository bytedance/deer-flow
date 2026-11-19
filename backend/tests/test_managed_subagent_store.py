"""Persistence coverage for administrator-managed subagents."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url

from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.persistence.base import Base
from deerflow.persistence.managed_subagents import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    make_managed_subagent_store,
)
from deerflow.persistence.managed_subagents.base import normalize_managed_subagent_name
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow
from deerflow.persistence.managed_subagents.sql import SqlManagedSubagentStore
from deerflow.persistence.postgres_schema import dsn_with_search_path
from deerflow.subagents import registry


def _definition(name: str = "researcher", **changes) -> ManagedSubagentDefinition:
    return ManagedSubagentDefinition(
        name=name,
        description="Researches a bounded topic",
        system_prompt="You are a research specialist.",
        **changes,
    )


@pytest.fixture()
def file_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    return FileManagedSubagentStore()


@pytest.fixture()
def sql_store(tmp_path, request):
    if getattr(request, "param", "sqlite") == "sqlite":
        store = SqlManagedSubagentStore(f"sqlite:///{tmp_path}/managed.db")
        engine = store._Session.kw["bind"]
        try:
            Base.metadata.create_all(engine, tables=[ManagedSubagentRow.__table__])
            yield store
        finally:
            engine.dispose()
        return

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (managed subagents on PostgreSQL)")
    schema = f"managed_subagents_{uuid.uuid4().hex}"
    admin = create_engine(make_url(uri).set(drivername="postgresql+psycopg"))
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(dsn_with_search_path(uri, schema)).set(drivername="postgresql+psycopg")
    store = SqlManagedSubagentStore(url.render_as_string(hide_password=False))
    engine = store._Session.kw["bind"]
    try:
        Base.metadata.create_all(engine, tables=[ManagedSubagentRow.__table__])
        yield store
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("store_fixture", ["file_store", "sql_store"])
def test_crud_and_signature(request, store_fixture):
    store = request.getfixturevalue(store_fixture)
    empty_signature = store.signature()
    definition = _definition(thinking_enabled=True, reasoning_effort="xhigh")

    store.create(definition)
    assert store.get("RESEARCHER") == definition
    assert [item.name for item in store.list()] == ["researcher"]
    created_signature = store.signature()
    assert created_signature != empty_signature

    updated = definition.model_copy(update={"enabled": False, "max_turns": 75})
    store.update(updated)
    assert store.get("researcher").enabled is False
    assert store.get("researcher").max_turns == 75
    assert store.get("researcher").thinking_enabled is True
    assert store.get("researcher").reasoning_effort == "xhigh"
    updated_signature = store.signature()
    assert updated_signature != created_signature

    assert store.delete("researcher") is True
    assert store.signature() != updated_signature
    assert store.delete("researcher") is False
    with pytest.raises(FileNotFoundError):
        store.get("researcher")


@pytest.mark.parametrize("store_fixture", ["file_store", "sql_store"])
def test_legacy_definition_without_reasoning_fields_keeps_defaults(request, store_fixture, tmp_path):
    store = request.getfixturevalue(store_fixture)
    legacy = {"name": "researcher", "description": "Research", "system_prompt": "Research the task."}
    if store_fixture == "file_store":
        root = tmp_path / "managed-subagents"
        root.mkdir()
        (root / "researcher.json").write_text(json.dumps(legacy), encoding="utf-8")
    else:
        with store._Session() as session:
            session.add(ManagedSubagentRow(id="legacy", name="researcher", definition=legacy))
            session.commit()
    definition = store.get("researcher")
    assert definition.thinking_enabled is None
    assert definition.reasoning_effort is None
    assert store.list() == [definition]


def test_sql_signature_detects_update_behind_existing_max_timestamp(sql_store):
    sql_store.create(_definition("ahead"))
    sql_store.create(_definition("writer"))

    with sql_store._Session() as session:
        ahead = session.execute(select(ManagedSubagentRow).where(ManagedSubagentRow.name == "ahead")).scalar_one()
        ahead.updated_at = datetime.now(UTC) + timedelta(minutes=5)
        session.commit()

    before = sql_store.signature()
    writer = sql_store.get("writer").model_copy(update={"description": "Updated by a trailing node"})
    sql_store.update(writer)

    assert sql_store.get("writer").description == "Updated by a trailing node"
    assert sql_store.signature() != before


def test_sql_signature_changes_when_the_clock_does_not_advance(sql_store, monkeypatch):
    """An update inside one clock tick must still invalidate peer snapshots."""
    sql_store.create(_definition())
    fixed = datetime.now(UTC)

    # Pin the stored timestamp, then freeze the wall clock at exactly that
    # value. The ORM onupdate callback writes the very same timestamp back,
    # so without the fix the row's (id, updated_at) pair never moves.
    with sql_store._Session() as session:
        row = session.execute(select(ManagedSubagentRow).where(ManagedSubagentRow.name == "researcher")).scalar_one()
        row.updated_at = fixed.replace(tzinfo=None)  # SQLite persists naive datetimes
        session.commit()

    before = sql_store.signature()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr("deerflow.persistence.managed_subagents.model.datetime", FrozenDatetime)
    # The store's own clock only exists once the fix is in place; raising=False
    # keeps this test a behavioural check against unpatched code too.
    monkeypatch.setattr("deerflow.persistence.managed_subagents.sql.datetime", FrozenDatetime, raising=False)

    sql_store.update(_definition().model_copy(update={"description": "second"}))

    assert sql_store.get("researcher").description == "second"
    assert sql_store.signature() != before


@pytest.mark.parametrize("sql_store", ["sqlite", "postgresql"], indirect=True)
def test_concurrent_sql_updates_invalidate_the_registry_after_each_commit(sql_store, monkeypatch):
    fixed = datetime(2026, 1, 1, tzinfo=UTC)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr("deerflow.persistence.managed_subagents.model.datetime", FrozenDatetime)
    monkeypatch.setattr("deerflow.persistence.managed_subagents.sql.datetime", FrozenDatetime)
    definition = _definition()
    sql_store.create(definition)
    original_signature = sql_store.signature()
    first = definition.model_copy(update={"description": "First commit"})
    second = definition.model_copy(update={"description": "Second commit"})

    observer = SqlManagedSubagentStore(sql_store._url)
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda *_: observer)
    monkeypatch.setattr(registry, "_managed_definitions_cache", {})
    registry_clock = SimpleNamespace(monotonic=lambda: 0.0)
    monkeypatch.setattr(registry, "time", registry_clock)
    config = SubagentsAppConfig()

    writer_ready = Event()
    resume_writer = Event()
    reader_thread = get_ident()

    def pause_before_write(_conn, _cursor, statement, _params, _context, _executemany):
        if get_ident() == reader_thread:
            return
        if statement.startswith(("BEGIN IMMEDIATE", "UPDATE ")) or " FOR UPDATE" in statement:
            writer_ready.set()
            if not resume_writer.wait(timeout=10):
                raise TimeoutError("Second writer was not released")

    # Pause the second writer just before it takes a lock or issues its UPDATE.
    # The old code has already read the timestamp when it reaches this point.
    engine = sql_store._Session.kw["bind"]
    event.listen(engine, "before_cursor_execute", pause_before_write)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(sql_store.update, second)
            try:
                assert writer_ready.wait(timeout=10)
                sql_store.update(first)
                first_signature = observer.signature()
                assert first_signature[0][1] == original_signature[0][1] + timedelta(microseconds=1)
                assert registry.get_subagent_config(definition.name, app_config=config).description == first.description
            finally:
                resume_writer.set()
            pending.result(timeout=10)
    finally:
        event.remove(engine, "before_cursor_execute", pause_before_write)

    assert observer.get(definition.name).description == second.description
    registry_clock.monotonic = lambda: registry._MANAGED_SIGNATURE_TTL_SECONDS
    assert registry.get_subagent_config(definition.name, app_config=config).description == second.description
    assert observer.signature()[0][1] == first_signature[0][1] + timedelta(microseconds=1)


@pytest.mark.parametrize("store_fixture", ["file_store", "sql_store"])
def test_duplicate_create_is_a_conflict(request, store_fixture):
    store = request.getfixturevalue(store_fixture)
    store.create(_definition())
    with pytest.raises(ManagedSubagentExistsError):
        store.create(_definition())


def test_worker_boundary_is_always_enforced():
    definition = _definition(disallowed_tools=[])
    assert {"task", "ask_clarification", "present_files"}.issubset(definition.disallowed_tools)


def test_file_store_uses_one_atomic_file_per_definition(file_store, tmp_path):
    file_store.create(_definition("planner"))
    file_store.create(_definition("writer"))
    root = tmp_path / "managed-subagents"
    assert sorted(path.name for path in root.iterdir()) == ["planner.json", "writer.json"]
    assert not list(root.glob("*.tmp"))


def test_file_store_skips_one_corrupt_definition_without_hiding_valid_entries(file_store, tmp_path):
    file_store.create(_definition("planner"))
    root = tmp_path / "managed-subagents"
    (root / "broken.json").write_text("{not-json", encoding="utf-8")

    assert [item.name for item in file_store.list()] == ["planner"]


def test_store_factory_follows_agent_storage_backend(tmp_path):
    file_config = SimpleNamespace(agent_storage=SimpleNamespace(backend="file"))
    assert isinstance(make_managed_subagent_store(file_config), FileManagedSubagentStore)

    db_config = SimpleNamespace(
        agent_storage=SimpleNamespace(backend="db"),
        database=SimpleNamespace(
            backend="sqlite",
            app_sync_sqlalchemy_url=f"sqlite:///{tmp_path}/factory.db",
        ),
    )
    assert isinstance(make_managed_subagent_store(db_config), SqlManagedSubagentStore)


def test_store_factory_rejects_memory_database():
    config = SimpleNamespace(
        agent_storage=SimpleNamespace(backend="db"),
        database=SimpleNamespace(backend="memory"),
    )
    with pytest.raises(ValueError, match="sqlite.*postgres"):
        make_managed_subagent_store(config)


@pytest.mark.parametrize("name", ["nul", "NUL", "Nul", "con", "prn", "aux", "com1", "lpt9"])
def test_normalize_managed_subagent_name_rejects_windows_reserved_names(name: str):
    with pytest.raises(ValueError, match="reserved Windows device name"):
        normalize_managed_subagent_name(name, for_creation=True)


@pytest.mark.parametrize("name", ["nul", "con", "com1"])
def test_normalize_managed_subagent_name_allows_reserved_names_on_read(name: str):
    assert normalize_managed_subagent_name(name) == name.lower()


@pytest.mark.parametrize("name", ["planner", "code-reviewer-2", "researcher"])
def test_normalize_managed_subagent_name_accepts_valid_names(name: str):
    assert normalize_managed_subagent_name(name, for_creation=True) == name


@pytest.mark.parametrize("store_fixture", ["file_store", "sql_store"])
def test_store_rejects_windows_reserved_device_names(request, store_fixture):
    store = request.getfixturevalue(store_fixture)
    with pytest.raises(ValueError, match="reserved Windows device name"):
        store.create(_definition("nul"))
