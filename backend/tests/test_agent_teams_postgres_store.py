"""Plugin-owned PostgreSQL storage and ownership lifecycle."""

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

pytestmark = pytest.mark.bundled_extension


@pytest.fixture(autouse=True)
def extension_path(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))


@pytest.mark.parametrize(
    "url",
    [None, "", "sqlite:///private", "host=private password=secret", "http://private"],
)
def test_postgres_store_rejects_invalid_urls_without_echoing_credentials(url):
    from deerflow_extension_agent_teams.postgres_store import PostgresStore

    with pytest.raises(ValueError, match="storage_url") as error:
        PostgresStore(url)
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "schema",
    [
        None,
        "",
        "public",
        "pg_catalog",
        "information_schema",
        "other.schema",
        "a" * 64,
        'x"; DROP SCHEMA public; --',
    ],
)
def test_postgres_store_rejects_invalid_schema(schema):
    from deerflow_extension_agent_teams.postgres_store import PostgresStore

    with pytest.raises(ValueError, match="storage_schema"):
        PostgresStore("postgresql://localhost/test", schema)


def test_postgres_constructor_is_lazy_and_closed_store_requires_acquisition():
    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from deerflow_extension_agent_teams.store import StoreUnavailable

    store = PostgresStore("postgresql://localhost/test")
    with pytest.raises(StoreUnavailable):
        store.list("alice")
    store.close()


@pytest.fixture
def postgres_store():
    url = os.environ.get("TEST_POSTGRES_URI")
    if not url:
        pytest.skip("requires TEST_POSTGRES_URI")
    psycopg = pytest.importorskip("psycopg")
    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from psycopg import sql

    schema = "teams_test_" + uuid.uuid4().hex
    store = PostgresStore(url, schema)
    store.acquire_service_lock()
    try:
        yield store, url, schema
    finally:
        store.close()
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def team(team_id, *, pending=False):
    return {
        "id": team_id,
        "jobs": [{"status": "queued"}] if pending else [],
        "artifacts": [
            {
                "id": "version",
                "artifact_id": "report",
                "version": 1,
                "status": "pending",
                "source": {},
            }
        ],
    }


def test_postgres_owner_scope_ordering_projection_and_rollback(postgres_store):
    store, _, _ = postgres_store
    store.create("alice", team("first"))
    store.create("alice", team("second", pending=True))
    store.create("bob", team("private"))
    assert [item["id"] for item in store.list("alice")] == ["second", "first"]
    assert list(store.scheduling_snapshots()) == [("alice", "second")]
    assert store.create("alice", team("first", pending=True))["jobs"] == []
    with pytest.raises(ValueError, match="unavailable"):
        store.get("bob", "first")
    store.delete("bob", "first")
    assert store.get("alice", "first")["id"] == "first"

    def fail(current):
        current["jobs"].append({"status": "queued"})
        raise ValueError("rollback")

    with pytest.raises(ValueError, match="rollback"):
        store.change("alice", "first", fail)
    assert not store.get("alice", "first")["jobs"]
    store.change("alice", "second", lambda current: current["jobs"][0].update(status="completed"))
    assert not store.scheduling_snapshots()


def test_postgres_concurrent_team_count_is_bounded(postgres_store):
    store, _, _ = postgres_store

    barrier = Barrier(8)

    def create(index):
        barrier.wait(timeout=10)
        try:
            store.create("alice", team(str(index)))
            return True
        except ValueError as error:
            assert "Team limit" in str(error)
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(create, range(24))) == 20
    assert len(store.list("alice")) == 20
    store.create("bob", team("other-owner"))


def test_postgres_artifact_quota_atomicity_restart_and_immutable_bytes(postgres_store, monkeypatch):
    import deerflow_extension_agent_teams.artifacts as artifacts
    import psycopg
    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from psycopg import sql

    store, url, schema = postgres_store
    monkeypatch.setattr(artifacts, "OWNER_BYTES", 5)
    for name in ("one", "two"):
        store.create("alice", team(name))

    barrier = Barrier(2)

    def capture(name):
        barrier.wait(timeout=10)
        try:
            store.capture_artifact("alice", name, "version", b"\x00\xffab", "run")
            return name
        except ValueError as error:
            assert "storage limit" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        captured = [name for name in executor.map(capture, ("one", "two")) if name]
    assert len(captured) == 1
    winner = captured[0]
    loser = "two" if winner == "one" else "one"
    assert store.get("alice", loser)["artifacts"][0]["status"] == "pending"
    store.capture_artifact("alice", winner, "version", b"ignored", "other-run")
    entry, content = store.artifact("alice", winner, "report", 1)
    assert content == b"\x00\xffab"
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["source"]["run_id"] == "run"
    with psycopg.connect(url, autocommit=True) as db:
        with pytest.raises(psycopg.errors.RaiseException, match="cannot be overwritten"):
            db.execute(
                sql.SQL("UPDATE {}.team_artifact_versions SET content = %s").format(sql.Identifier(schema)),
                (b"changed",),
            )
    store.close()
    replacement = PostgresStore(url, schema)
    replacement.acquire_service_lock()
    try:
        assert replacement.artifact("alice", winner, "report", 1) == (entry, content)
        replacement.delete("alice", winner)
        replacement.capture_artifact("alice", loser, "version", content, "new-run")
    finally:
        replacement.close()


def test_postgres_lock_loss_blocks_old_store_and_allows_new_owner(postgres_store):
    import psycopg
    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from deerflow_extension_agent_teams.store import StoreUnavailable

    store, url, schema = postgres_store
    store.create("alice", team("retained"))
    contender = PostgresStore(url, schema)
    with pytest.raises(StoreUnavailable, match="active"):
        contender.acquire_service_lock()
    with psycopg.connect(url, autocommit=True) as db:
        pid = db.execute(
            "SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=%s AND objid=%s AND objsubid=1 AND granted",
            (store.lock_key >> 32, store.lock_key & 0xFFFFFFFF),
        ).fetchone()[0]
        db.execute("SELECT pg_terminate_backend(%s)", (pid,))
    with pytest.raises(StoreUnavailable):
        store.check_service_lock()
    with pytest.raises(StoreUnavailable):
        store.create("alice", team("stale-write"))
    contender.acquire_service_lock()
    try:
        assert [item["id"] for item in contender.list("alice")] == ["retained"]
    finally:
        contender.close()


def test_postgres_missing_optional_dependency_has_an_actionable_error(monkeypatch):
    import builtins

    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from deerflow_extension_agent_teams.store import StoreUnavailable

    original_import = builtins.__import__

    def import_without_psycopg(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("optional dependency absent")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_psycopg)
    store = PostgresStore("postgresql://private:secret@localhost/test")
    with pytest.raises(StoreUnavailable, match=r"agent-teams\[postgres\]") as error:
        store.acquire_service_lock()
    assert "secret" not in str(error.value)
    with pytest.raises(StoreUnavailable):
        store.list("alice")


def test_postgres_explicit_unlock_fences_store_writes(postgres_store):
    from deerflow_extension_agent_teams.store import StoreUnavailable

    store, _, _ = postgres_store
    assert store._connection.execute("SELECT pg_advisory_unlock(%s)", (store.lock_key,)).fetchone() == (True,)
    with pytest.raises(StoreUnavailable):
        store.create("alice", team("after-unlock"))
    assert store._connection is None


def test_postgres_sql_failure_redacts_values_and_closes_connection(postgres_store):
    from deerflow_extension_agent_teams.store import StoreUnavailable

    store, _, _ = postgres_store
    store.create("alice", team("private-team-name"))
    with pytest.raises(StoreUnavailable) as error:
        store.create("bob", team("private-team-name"))
    assert "private-team-name" not in str(error.value)
    assert error.value.__suppress_context__
    assert store._connection is None


def test_postgres_schemas_have_independent_service_ownership(postgres_store):
    import psycopg
    from deerflow_extension_agent_teams.postgres_store import PostgresStore
    from psycopg import sql

    store, url, schema = postgres_store
    other_schema = schema + "_other"
    other = PostgresStore(url, other_schema)
    try:
        other.acquire_service_lock()
        store.create("alice", team("private"))
        assert not other.list("alice")
        other.create("alice", team("separate"))
        assert [item["id"] for item in store.list("alice")] == ["private"]
    finally:
        other.close()
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(other_schema)))
