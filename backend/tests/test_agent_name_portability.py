"""A custom-agent name is a host directory component, so creation is portable.

``{base_dir}/users/{user_id}/agents/{name}/`` is created as a real directory.
Windows reserves device names (``NUL``, ``CON``, ``COM1`` …) in every
directory: ``mkdir`` appears to succeed and the first write inside it raises
``FileNotFoundError``. Creation therefore rejects those names on every
platform, matching ``validate_thread_id`` and the upload/skill/sandbox
creation paths; an agent that already exists stays readable, updatable and
deletable so a pre-fix Linux installation can still manage it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import yaml
from sqlalchemy import create_engine

from deerflow.config.agents_config import validate_agent_name
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base

RESERVED_NAMES = ["NUL", "nul", "CON", "PRN", "AUX", "COM1", "com9", "LPT1", "lpt9"]
ORDINARY_NAMES = ["reviewer", "a1-b2", "code-reviewer", "agent-9"]


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    """Root the file store at a temp home, like the other agent-store tests."""
    from deerflow.config import agents_config
    from deerflow.config import paths as paths_module

    paths_instance = paths_module.Paths(base_dir=tmp_path)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_module, "_paths", None)
    monkeypatch.setattr(agents_config, "get_paths", lambda: paths_instance)
    return paths_instance


@pytest.fixture()
def sql_store(tmp_path):
    url = f"sqlite:///{tmp_path}/agents.db"
    create_engine(url)  # touch the file
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()
    return SqlAgentStore(url)


@pytest.mark.parametrize("name", RESERVED_NAMES)
def test_creation_rejects_reserved_device_names(name):
    with pytest.raises(ValueError, match="reserved Windows device name"):
        validate_agent_name(name, for_creation=True)


@pytest.mark.parametrize("name", RESERVED_NAMES)
def test_reads_keep_accepting_reserved_device_names(name):
    # A pre-fix installation may hold one of these; listing, exporting and
    # deleting it must keep working.
    assert validate_agent_name(name) == name


@pytest.mark.parametrize("name", ORDINARY_NAMES)
def test_creation_accepts_ordinary_names(name):
    assert validate_agent_name(name, for_creation=True) == name


def test_file_store_create_rejects_a_reserved_name_without_touching_disk(paths):
    store = FileAgentStore()

    with pytest.raises(ValueError, match="reserved Windows device name"):
        store.create("nul", {"name": "nul"}, "soul", user_id="u1")

    assert not paths.user_agents_dir("u1").exists()


def test_file_store_update_to_a_missing_reserved_name_is_rejected(paths):
    store = FileAgentStore()

    # setup_agent/update_agent upsert through update(); a missing target is a
    # creation and takes the same guard. On Windows ``exists()`` is true for
    # the NUL device, so the store must key off a real directory instead.
    with pytest.raises(ValueError, match="reserved Windows device name"):
        store.update("nul", {"name": "nul"}, None, user_id="u1")

    assert not paths.user_agents_dir("u1").exists()


@pytest.mark.skipif(os.name == "nt", reason="a reserved-name directory cannot be created on Windows")
def test_existing_reserved_name_agent_stays_readable_updatable_and_deletable(paths):
    agent_dir = paths.user_agent_dir("u1", "nul")
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump({"name": "nul", "description": "old"}), encoding="utf-8")
    store = FileAgentStore()

    assert store.get("nul", user_id="u1").description == "old"

    store.update("nul", {"name": "nul", "description": "fixed"}, None, user_id="u1")
    assert store.get("nul", user_id="u1").description == "fixed"

    assert store.delete("nul", user_id="u1") == "deleted"


def test_sql_store_create_rejects_a_reserved_name(sql_store):
    with pytest.raises(ValueError, match="reserved Windows device name"):
        sql_store.create("nul", {"name": "nul"}, "soul", user_id="u1")

    assert sql_store.list(user_id="u1") == []


def test_sql_store_update_upsert_rejects_a_reserved_name(sql_store):
    with pytest.raises(ValueError, match="reserved Windows device name"):
        sql_store.update("nul", {"name": "nul"}, "soul", user_id="u1")

    assert sql_store.list(user_id="u1") == []


def test_sql_store_keeps_accepting_a_legacy_reserved_row(sql_store):
    legacy = AgentRow(
        id="legacy-nul",
        user_id="u1",
        name="nul",
        config={"name": "nul", "description": "old"},
        soul="s",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with sql_store._Session() as session:
        session.add(legacy)
        session.commit()

    sql_store.update("nul", {"name": "nul", "description": "fixed"}, None, user_id="u1")

    assert sql_store.get("nul", user_id="u1").description == "fixed"
