"""The persisted catalogs answer what they can read, not an exception.

Both file backends already drop a row they cannot parse: ``FileManagedSubagentStore.list``
keeps the catalog alive for the same reason ``FileAgentStore.list`` does ("one bad agent must
not hide the rest"). The two SQL backends build their answer in one comprehension, so a single
row written by a newer release -- or edited by hand -- takes ``GET /api/subagents`` and
``GET /api/agents`` down for every entry of that user instead of skipping that row.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow
from deerflow.persistence.managed_subagents.sql import SqlManagedSubagentStore


def _definition(name: str) -> ManagedSubagentDefinition:
    return ManagedSubagentDefinition(
        name=name,
        description="Researches a bounded topic",
        system_prompt="You are a research specialist.",
    )


def _insert_agent_row(url: str, *, user_id: str, name: str, config: dict) -> None:
    """Write a row the way a newer release, or a hand edit, leaves it behind."""
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(AgentRow.__table__.insert().values(id=uuid.uuid4().hex, user_id=user_id, name=name, config=config, soul=""))
    finally:
        engine.dispose()


def _insert_subagent_row(url: str, *, name: str, definition: dict) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(ManagedSubagentRow.__table__.insert().values(id=uuid.uuid4().hex, name=name, definition=definition))
    finally:
        engine.dispose()


def _insert_raw_agent_json(url: str, *, user_id: str, name: str, raw_config: str | None, soul: str = "") -> None:
    """Bypass ORM JSON serialization to store raw text (e.g. a truncated hand edit in SQLite)."""
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO agents (id, user_id, name, config, soul, created_at, updated_at) VALUES (:id, :user_id, :name, :config, :soul, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"id": uuid.uuid4().hex, "user_id": user_id, "name": name, "config": raw_config, "soul": soul},
            )
    finally:
        engine.dispose()


def _insert_raw_subagent_json(url: str, *, name: str, raw_definition: str | None) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO managed_subagents (id, name, definition, created_at, updated_at) VALUES (:id, :name, :definition, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"id": uuid.uuid4().hex, "name": name, "definition": raw_definition},
            )
    finally:
        engine.dispose()


def _names_or_error(read) -> list[str] | str:
    """What the catalog answered: the names it listed, or the error that replaced them."""
    try:
        return [item.name for item in read()]
    except ValidationError as exc:
        return f"{type(exc).__name__}: {exc}"


@pytest.fixture()
def agent_store(tmp_path):
    url = f"sqlite:///{tmp_path}/agents.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()
    return SqlAgentStore(url), url


@pytest.fixture()
def subagent_store(tmp_path):
    url = f"sqlite:///{tmp_path}/managed.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[ManagedSubagentRow.__table__])
    engine.dispose()
    return SqlManagedSubagentStore(url), url


def test_agent_catalog_skips_one_unreadable_row(agent_store):
    store, url = agent_store
    store.create("good-agent", {"name": "good-agent"}, "You answer.", user_id="u1")
    # ``reasoning_effort`` is a Literal; a value only a newer release accepts is a
    # validation error for this one, and nothing about the good row changed.
    _insert_agent_row(url, user_id="u1", name="future-agent", config={"name": "future-agent", "reasoning_effort": "extreme"})

    assert _names_or_error(lambda: store.list(user_id="u1")) == ["good-agent"], "one unreadable row took the whole agent catalog down"
    assert [config.name for _user, config in store.list_all()] == ["good-agent"]


def test_subagent_catalog_skips_one_unreadable_row(subagent_store):
    store, url = subagent_store
    store.create(_definition("planner"))
    # ``ManagedSubagentDefinition`` forbids extra fields, so a definition a newer
    # release writes does not validate against this release's model.
    future = {**_definition("legacy-worker").model_dump(mode="json"), "retry_policy": {"max_retries": 3}}
    _insert_subagent_row(url, name="legacy-worker", definition=future)

    assert _names_or_error(store.list) == ["planner"], "one unreadable definition took the catalog down"


def test_reading_one_damaged_row_by_name_still_reports_it(subagent_store):
    store, url = subagent_store
    store.create(_definition("planner"))
    future = {**_definition("legacy-worker").model_dump(mode="json"), "retry_policy": {"max_retries": 3}}
    _insert_subagent_row(url, name="legacy-worker", definition=future)

    # The skip is list-only: asking for that name still surfaces the damage, and the
    # row remains removable so an operator can clear it.
    with pytest.raises(ValidationError):
        store.get("legacy-worker")
    assert store.delete("legacy-worker") is True


def test_reading_one_damaged_agent_row_by_name_still_reports_it(agent_store):
    store, url = agent_store
    store.create("good-agent", {"name": "good-agent"}, "You answer.", user_id="u1")
    _insert_agent_row(url, user_id="u1", name="future-agent", config={"name": "future-agent", "reasoning_effort": "extreme"})

    # Same contract as the managed-subagent store: the skip belongs to the listing, so
    # asking for that name still surfaces the damage instead of answering None.
    with pytest.raises(ValidationError):
        store.get("future-agent", user_id="u1")
    assert store.delete("future-agent", user_id="u1") == "deleted"


def test_a_readable_row_with_unknown_legacy_keys_is_still_listed(agent_store):
    store, url = agent_store
    # ``parse_agent_config`` drops keys the model does not know (the legacy
    # ``prompt_file`` here); that is not a validation failure, so the row stays.
    store.create("legacy-agent", {"name": "legacy-agent", "prompt_file": "old.md"}, "You answer.", user_id="u1")

    assert _names_or_error(lambda: store.list(user_id="u1")) == ["legacy-agent"]


def test_agent_catalog_isolates_invalid_sqlite_json_middle_row(agent_store):
    store, url = agent_store
    store.create("alpha-agent", {"name": "alpha-agent"}, "Alpha.", user_id="u1")
    _insert_raw_agent_json(url, user_id="u1", name="broken-agent", raw_config='{"description": ', soul="Broken soul.")
    store.create("zeta-agent", {"name": "zeta-agent"}, "Zeta.", user_id="u1")

    assert [cfg.name for cfg in store.list(user_id="u1")] == ["alpha-agent", "zeta-agent"]
    assert [(u, cfg.name) for u, cfg in store.list_all()] == [("u1", "alpha-agent"), ("u1", "zeta-agent")]

    # Auxiliary read/metadata paths must not fail on the damaged JSON column, while
    # single-name get() stays strict.
    assert store.exists("broken-agent", user_id="u1") is True
    assert store.get_soul("broken-agent", user_id="u1") == "Broken soul."
    sig_broken = store.signature()
    with pytest.raises(json.JSONDecodeError):
        store.get("broken-agent", user_id="u1")

    # An operator can repair the row in place or delete it.
    store.update("broken-agent", {"name": "broken-agent", "description": "repaired"}, None, user_id="u1")
    assert store.get("broken-agent", user_id="u1").description == "repaired"
    assert store.signature() != sig_broken

    # Deleting an un-repaired invalid-JSON row also succeeds.
    _insert_raw_agent_json(url, user_id="u1", name="mid-bad", raw_config="{not-json")
    assert store.delete("mid-bad", user_id="u1") == "deleted"


@pytest.mark.parametrize("raw_config", ["[]", "[1, 2]", '"oops"', "42"])
def test_agent_catalog_skips_non_object_json_values_and_keeps_get_strict(agent_store, raw_config):
    store, url = agent_store
    store.create("alpha-agent", {"name": "alpha-agent"}, "Alpha.", user_id="u1")
    _insert_raw_agent_json(url, user_id="u1", name="non-object", raw_config=raw_config)
    store.create("zeta-agent", {"name": "zeta-agent"}, "Zeta.", user_id="u1")

    assert [cfg.name for cfg in store.list(user_id="u1")] == ["alpha-agent", "zeta-agent"]
    assert [(u, cfg.name) for u, cfg in store.list_all()] == [("u1", "alpha-agent"), ("u1", "zeta-agent")]
    with pytest.raises(TypeError):
        store.get("non-object", user_id="u1")


def test_subagent_catalog_isolates_invalid_sqlite_json_middle_row(subagent_store):
    store, url = subagent_store
    store.create(_definition("alpha-worker"))
    _insert_raw_subagent_json(url, name="broken-worker", raw_definition='{"name": "broken-worker"')
    _insert_raw_subagent_json(url, name="null-worker", raw_definition="null")
    _insert_raw_subagent_json(url, name="list-worker", raw_definition="[]")
    store.create(_definition("zeta-worker"))

    assert [item.name for item in store.list()] == ["alpha-worker", "zeta-worker"]
    assert store.signature() is not None
    with pytest.raises(json.JSONDecodeError):
        store.get("broken-worker")
    with pytest.raises(ValidationError):
        store.get("null-worker")

    # Repairing in place and deleting corrupt rows both succeed without decoding old JSON.
    store.update(_definition("broken-worker"))
    assert store.get("broken-worker").name == "broken-worker"
    assert store.delete("null-worker") is True
    assert store.delete("list-worker") is True
