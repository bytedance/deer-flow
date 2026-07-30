"""SqlAgentStore — the db agent-storage backend.

Exercises the synchronous SQL store against a real sqlite file: CRUD, the
config-document round trip (name excluded from the JSON, restored on read),
per-user isolation, the UNIQUE(user_id, name) conflict, and the change-token
signature the GitHub registry keys its cache off.
"""

from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy import create_engine

from deerflow.config.agents_config import AgentConfig
from deerflow.persistence.agents.base import AgentExistsError
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base


@pytest.fixture()
def store(tmp_path):
    # Unique file per test → the store's per-URL engine cache never collides.
    url = f"sqlite:///{tmp_path}/agents.db"
    create_engine(url)  # touch the file
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()
    return SqlAgentStore(url)


def test_create_and_get_round_trips_config_and_soul(store):
    store.create("reviewer", {"name": "reviewer", "description": "reviews code", "model": "gpt-x"}, "You review.", user_id="u1")

    cfg = store.get("reviewer", user_id="u1")
    assert isinstance(cfg, AgentConfig)
    assert cfg.name == "reviewer"
    assert cfg.description == "reviews code"
    assert cfg.model == "gpt-x"
    assert store.get_soul("reviewer", user_id="u1") == "You review."


def test_name_is_stored_lowercase_and_excluded_from_document(store):
    store.create("Mixed", {"name": "Mixed", "description": "d"}, "s", user_id="u1")
    # Stored lowercase (matches the on-disk layout), and the JSON document does
    # not duplicate the name column.
    with store._Session() as session:
        row = session.query(AgentRow).one()
    assert row.name == "mixed"
    assert "name" not in row.config
    assert store.get("mixed", user_id="u1").name == "mixed"


def test_get_missing_raises_file_not_found(store):
    # The historical contract routers/tools rely on for a 404 / "does not exist".
    with pytest.raises(FileNotFoundError):
        store.get("nope", user_id="u1")
    assert store.get_soul("nope", user_id="u1") is None
    assert store.exists("nope", user_id="u1") is False


def test_create_duplicate_raises_agent_exists(store):
    store.create("dup", {"name": "dup"}, "s", user_id="u1")
    with pytest.raises(AgentExistsError):
        store.create("dup", {"name": "dup"}, "s2", user_id="u1")


def test_update_is_upsert_and_partial(store):
    # Upsert: update on a missing agent creates it.
    store.update("a", {"name": "a", "description": "first"}, "soul1", user_id="u1")
    assert store.get("a", user_id="u1").description == "first"

    # config=None leaves config untouched, only soul changes.
    store.update("a", None, "soul2", user_id="u1")
    assert store.get("a", user_id="u1").description == "first"
    assert store.get_soul("a", user_id="u1") == "soul2"

    # soul=None leaves soul untouched, only config changes.
    store.update("a", {"name": "a", "description": "second"}, None, user_id="u1")
    assert store.get("a", user_id="u1").description == "second"
    assert store.get_soul("a", user_id="u1") == "soul2"


def test_update_insert_race_recovers_via_upsert(store):
    """update()'s insert-on-missing branch is a true upsert under a write race.

    Two concurrent first-time writes (e.g. two ``setup_agent`` handshakes) both
    see ``row is None`` and both insert; ``UNIQUE(user_id, name)`` rejects the
    loser. The loser must re-fetch the winner's row and apply its update rather
    than surfacing the raw ``IntegrityError`` as a 500. Simulated deterministically
    by making the first ``_row`` probe (the check-then-insert window) miss the
    already-committed winner, forcing the ``IntegrityError`` recovery path.
    """
    store.create("a", {"name": "a", "description": "winner"}, "winner-soul", user_id="u1")
    real_row = store._row  # bound method captured before patching
    seen = {"n": 0}

    def racing_row(session, name, user_id):
        seen["n"] += 1
        # First call is the pre-insert probe: pretend the winner isn't there yet.
        return None if seen["n"] == 1 else real_row(session, name, user_id)

    with mock.patch.object(store, "_row", side_effect=racing_row):
        # Must not raise: the loser recovers into a true upsert (last write wins).
        store.update("a", {"name": "a", "description": "loser"}, "loser-soul", user_id="u1")

    assert store.get("a", user_id="u1").description == "loser"
    assert store.get_soul("a", user_id="u1") == "loser-soul"


def test_list_and_list_all(store):
    store.create("b-agent", {"name": "b-agent"}, "s", user_id="u1")
    store.create("a-agent", {"name": "a-agent"}, "s", user_id="u1")
    store.create("c-agent", {"name": "c-agent"}, "s", user_id="u2")

    u1 = store.list(user_id="u1")
    assert [c.name for c in u1] == ["a-agent", "b-agent"]  # sorted by name
    assert store.list(user_id="u2") == store.list(user_id="u2")
    assert [c.name for c in store.list(user_id="u2")] == ["c-agent"]

    all_agents = store.list_all()
    assert sorted((uid, cfg.name) for uid, cfg in all_agents) == [
        ("u1", "a-agent"),
        ("u1", "b-agent"),
        ("u2", "c-agent"),
    ]


def test_user_isolation(store):
    store.create("shared-name", {"name": "shared-name", "description": "u1's"}, "s1", user_id="u1")
    # Same name under a different user is a distinct agent (no conflict).
    store.create("shared-name", {"name": "shared-name", "description": "u2's"}, "s2", user_id="u2")

    assert store.get("shared-name", user_id="u1").description == "u1's"
    assert store.get("shared-name", user_id="u2").description == "u2's"
    with pytest.raises(FileNotFoundError):
        store.get("shared-name", user_id="u3")


def test_delete_reports_outcome(store):
    store.create("gone", {"name": "gone"}, "s", user_id="u1")
    assert store.delete("gone", user_id="u1") == "deleted"
    assert store.delete("gone", user_id="u1") == "missing"
    with pytest.raises(FileNotFoundError):
        store.get("gone", user_id="u1")


def test_signature_changes_on_mutation(store):
    empty = store.signature()
    store.create("x", {"name": "x"}, "s", user_id="u1")
    after_create = store.signature()
    assert after_create != empty

    # A no-op read does not change the token.
    assert store.signature() == after_create

    store.update("x", {"name": "x", "description": "changed"}, None, user_id="u1")
    assert store.signature() != after_create


def test_sync_engine_mirrors_async_pragmas(tmp_path):
    # The db backend's sync engine must set the same per-connection SQLite PRAGMAs
    # the async engine does (persistence/engine.py), not leave synchronous=FULL
    # and pysqlite's default 5s busy_timeout. WAL is persistent on the file;
    # synchronous / busy_timeout are per-connection and must be re-applied here.
    from sqlalchemy import text

    from deerflow.persistence.agents.sql import _get_sessionmaker

    url = f"sqlite:///{tmp_path}/pragma.db"
    Session = _get_sessionmaker(url)
    with Session() as session:
        busy_timeout = session.execute(text("PRAGMA busy_timeout")).scalar()
        synchronous = session.execute(text("PRAGMA synchronous")).scalar()
        journal_mode = session.execute(text("PRAGMA journal_mode")).scalar()

    assert busy_timeout == 30000
    assert synchronous == 1  # NORMAL
    assert str(journal_mode).lower() == "wal"


def test_engine_cache_is_reused_per_url(tmp_path):
    # Two stores on the same URL share one cached engine (the lock-guarded
    # double-checked cache), so we never build duplicate engines/pools.
    from deerflow.persistence.agents.sql import _get_sessionmaker

    url = f"sqlite:///{tmp_path}/reuse.db"
    first = _get_sessionmaker(url)
    second = _get_sessionmaker(url)
    assert first.kw["bind"] is second.kw["bind"]


def test_delete_preserves_memory_only_dir_when_no_row(store, tmp_path, monkeypatch):
    # #4279 invariant carried into the db backend: with no agent row, a bare
    # on-disk directory holds only memory/facts data (config lives in the row in
    # db mode), so delete must preserve it and report "not-custom-agent" instead
    # of rmtree-ing a user's memory.
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    from deerflow.config.paths import get_paths

    facts_dir = get_paths().user_agent_dir("u1", "ghost") / "facts"
    facts_dir.mkdir(parents=True)
    fact = facts_dir / "fact_keep.md"
    fact.write_text("memory data", encoding="utf-8")

    assert store.delete("ghost", user_id="u1") == "not-custom-agent"
    assert fact.read_text(encoding="utf-8") == "memory data"


def test_delete_removes_memory_dir_when_row_exists(store, tmp_path, monkeypatch):
    # The complement: when the agent row exists, its co-located on-disk memory is
    # cleaned along with the row.
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    from deerflow.config.paths import get_paths

    store.create("real", {"name": "real"}, "s", user_id="u1")
    mem_dir = get_paths().user_agent_dir("u1", "real")
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "memory.json").write_text("{}", encoding="utf-8")

    assert store.delete("real", user_id="u1") == "deleted"
    assert not mem_dir.exists()
