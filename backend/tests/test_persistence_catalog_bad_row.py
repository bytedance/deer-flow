"""The persisted catalogs answer what they can read, not an exception.

Both file backends already drop a row they cannot parse: ``FileManagedSubagentStore.list``
keeps the catalog alive for the same reason ``FileAgentStore.list`` does ("one bad agent must
not hide the rest"). The two SQL backends build their answer in one comprehension, so a single
row written by a newer release -- or edited by hand -- takes ``GET /api/subagents`` and
``GET /api/agents`` down for every entry of that user instead of skipping that row.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

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


def test_a_readable_row_with_unknown_legacy_keys_is_still_listed(agent_store):
    store, url = agent_store
    # ``parse_agent_config`` drops keys the model does not know (the legacy
    # ``prompt_file`` here); that is not a validation failure, so the row stays.
    store.create("legacy-agent", {"name": "legacy-agent", "prompt_file": "old.md"}, "You answer.", user_id="u1")

    assert _names_or_error(lambda: store.list(user_id="u1")) == ["legacy-agent"]
