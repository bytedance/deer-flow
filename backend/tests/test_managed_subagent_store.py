"""Persistence coverage for administrator-managed subagents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select

from deerflow.persistence.base import Base
from deerflow.persistence.managed_subagents import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    make_managed_subagent_store,
)
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow
from deerflow.persistence.managed_subagents.sql import SqlManagedSubagentStore


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
def sql_store(tmp_path):
    url = f"sqlite:///{tmp_path}/managed.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[ManagedSubagentRow.__table__])
    engine.dispose()
    return SqlManagedSubagentStore(url)


@pytest.mark.parametrize("store_fixture", ["file_store", "sql_store"])
def test_crud_and_signature(request, store_fixture):
    store = request.getfixturevalue(store_fixture)
    empty_signature = store.signature()
    definition = _definition()

    store.create(definition)
    assert store.get("RESEARCHER") == definition
    assert [item.name for item in store.list()] == ["researcher"]
    created_signature = store.signature()
    assert created_signature != empty_signature

    updated = definition.model_copy(update={"enabled": False, "max_turns": 75})
    store.update(updated)
    assert store.get("researcher").enabled is False
    assert store.get("researcher").max_turns == 75
    updated_signature = store.signature()
    assert updated_signature != created_signature

    assert store.delete("researcher") is True
    assert store.signature() != updated_signature
    assert store.delete("researcher") is False
    with pytest.raises(FileNotFoundError):
        store.get("researcher")


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
