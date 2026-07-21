"""Agent-storage backend selection, startup validation, and the db importer."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.gateway.deps import _validate_agent_storage
from deerflow.config.agent_storage_config import AgentStorageConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.agents import make_agent_store
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base


def _cfg(agent_backend: str, db_backend: str, sqlite_dir: str = "/tmp/agent-store-test") -> SimpleNamespace:
    return SimpleNamespace(
        agent_storage=AgentStorageConfig(backend=agent_backend),
        database=DatabaseConfig(backend=db_backend, sqlite_dir=sqlite_dir),
    )


# -- make_agent_store selection --------------------------------------------


def test_file_is_the_default_backend():
    assert isinstance(make_agent_store(_cfg("file", "memory")), FileAgentStore)


def test_db_backend_builds_sql_store(tmp_path):
    assert isinstance(make_agent_store(_cfg("db", "sqlite", str(tmp_path))), SqlAgentStore)


def test_db_backend_on_memory_database_is_rejected():
    with pytest.raises(ValueError, match="requires database.backend"):
        make_agent_store(_cfg("db", "memory"))


# -- startup validation (deps) ---------------------------------------------


def test_validation_rejects_db_on_memory_database():
    with pytest.raises(SystemExit):
        _validate_agent_storage(_cfg("db", "memory"))


def test_validation_allows_file_and_db_on_sql(tmp_path):
    _validate_agent_storage(_cfg("file", "memory"))  # no raise
    _validate_agent_storage(_cfg("db", "sqlite", str(tmp_path)))  # no raise


def test_validation_warns_on_file_under_multiworker_postgres(monkeypatch, caplog):
    monkeypatch.setenv("GATEWAY_WORKERS", "4")
    cfg = SimpleNamespace(
        agent_storage=AgentStorageConfig(backend="file"),
        database=DatabaseConfig(backend="postgres", postgres_url="postgresql://u:p@h/db"),
    )
    with caplog.at_level("WARNING"):
        _validate_agent_storage(cfg)
    assert any("not visible across workers" in r.message for r in caplog.records)


# -- importer: file layout → db --------------------------------------------


@pytest.fixture()
def file_home(tmp_path, monkeypatch):
    """Root the file store at a temp DEER_FLOW_HOME with two seeded agents."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    fs = FileAgentStore()
    fs.create("reviewer", {"name": "reviewer", "description": "reviews"}, "review soul", user_id="u1")
    fs.create("planner", {"name": "planner", "description": "plans", "model": "m1"}, "plan soul", user_id="u2")
    return tmp_path


def _patch_importer(monkeypatch, cfg):
    import pathlib

    import scripts.migrate_agents_to_db as importer

    async def _noop_init(_):
        return None

    # Pre-create the schema (stand in for the alembic bootstrap the real run
    # does, which also creates the sqlite directory).
    pathlib.Path(cfg.database.sqlite_dir).mkdir(parents=True, exist_ok=True)
    engine = create_engine(cfg.database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()

    monkeypatch.setattr(importer, "get_app_config", lambda: cfg)
    monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", _noop_init)
    return importer


def test_importer_copies_all_agents_into_db(file_home, monkeypatch):
    cfg = _cfg("db", "sqlite", str(file_home / "db"))
    importer = _patch_importer(monkeypatch, cfg)
    monkeypatch.setattr(sys, "argv", ["migrate_agents_to_db"])

    assert importer.main() == 0

    dest = SqlAgentStore(cfg.database.app_sync_sqlalchemy_url)
    assert dest.get("reviewer", user_id="u1").description == "reviews"
    assert dest.get_soul("reviewer", user_id="u1") == "review soul"
    assert dest.get("planner", user_id="u2").model == "m1"


def test_importer_is_idempotent(file_home, monkeypatch):
    cfg = _cfg("db", "sqlite", str(file_home / "db"))
    importer = _patch_importer(monkeypatch, cfg)
    monkeypatch.setattr(sys, "argv", ["migrate_agents_to_db"])

    assert importer.main() == 0
    # Second run must not raise on the already-present rows.
    assert importer.main() == 0
    dest = SqlAgentStore(cfg.database.app_sync_sqlalchemy_url)
    assert len(dest.list_all()) == 2


def test_importer_dry_run_writes_nothing(file_home, monkeypatch):
    cfg = _cfg("db", "sqlite", str(file_home / "db"))
    importer = _patch_importer(monkeypatch, cfg)
    monkeypatch.setattr(sys, "argv", ["migrate_agents_to_db", "--dry-run"])

    assert importer.main() == 0
    dest = SqlAgentStore(cfg.database.app_sync_sqlalchemy_url)
    assert dest.list_all() == []


def test_read_free_functions_dispatch_to_db_backend(file_home, monkeypatch):
    """The headline invariant: under the db backend the standard read path (the
    same free functions the per-run agent build calls) resolves from the shared
    DB, not from node-local files — so on-disk agents are invisible and db agents
    are visible everywhere."""
    cfg = _cfg("db", "sqlite", str(file_home / "db"))
    _patch_importer(monkeypatch, cfg)  # creates the schema
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: cfg)

    from deerflow.config.agents_config import list_custom_agents, load_agent_config, load_agent_soul

    # The file store seeded 'reviewer'/'planner' on disk; the db is empty, so
    # the free functions (now db-backed) do not see them.
    assert list_custom_agents(user_id="u1") == []
    with pytest.raises(FileNotFoundError):
        load_agent_config("reviewer", user_id="u1")

    # An agent written to the shared db is visible through the same free functions.
    SqlAgentStore(cfg.database.app_sync_sqlalchemy_url).create("dbonly", {"name": "dbonly", "description": "shared"}, "db soul", user_id="u1")
    assert [c.name for c in list_custom_agents(user_id="u1")] == ["dbonly"]
    assert load_agent_config("dbonly", user_id="u1").description == "shared"
    assert load_agent_soul("dbonly", user_id="u1") == "db soul"
