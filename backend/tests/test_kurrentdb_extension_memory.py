"""Event-sourced DeerMem storage on KurrentDB: stream, fold, load/reload, save, change sets, clears, revisions."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import DeadlineExceededError, ServiceUnavailableError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    FileMemoryStorage,
    MemoryFactRevisionConflict,
    MemoryManifestRevisionConflict,
    MemoryStorageCorruption,
    create_storage,
)
from deerflow.agents.memory.manager import MemoryCorruptionError, MemoryReadError

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
STORAGE_CLASS = "deerflow_extension_kurrentdb.memory.KurrentdbMemoryStorage"
AGENT = "__default__"
GLOBAL_STREAM = "deerflow.memory-global"
ALICE_STREAM = "deerflow.memory-user.alice"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


def _storage(server: FakeKurrentDB, config: DeerMemConfig | None = None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    client = server.sync_client()
    return KurrentdbMemoryStorage(config or DeerMemConfig(), client_factory=lambda: client)


def _fact(fact_id: str, content: str, **extra) -> dict:
    return {"id": fact_id, "content": content, "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual", **extra}


def _summaries(work: str = "Builds DeerFlow", recent: str = "Shipped KurrentDB") -> dict:
    return {
        "user": {"workContext": {"summary": work, "updatedAt": "2026-11-01T00:00:00Z"}},
        "history": {"recentMonths": {"summary": recent, "updatedAt": "2026-11-01T00:00:00Z"}},
    }


def _types(server: FakeKurrentDB, stream: str) -> list[str]:
    return [event.type for event in server.sync_client().get_stream(stream)]


def _head(server: FakeKurrentDB, stream: str) -> int | StreamState:
    return server.sync_client().get_current_version(stream)


# --- load / save / revisions --------------------------------------------------


def test_load_empty_scope_revision_zero(server):
    storage = _storage(server)
    for agent, user in [(None, None), (AGENT, None), (None, "alice"), ("researcher", "alice")]:
        document = storage.load(agent, user_id=user)
        assert document["revision"] == 0
        assert document["facts"] == []
        assert document["user"]["workContext"] == {"summary": "", "updatedAt": ""}
        assert set(document) >= {"version", "revision", "lastUpdated", "user", "history", "facts"}
        assert storage.reload(agent, user_id=user)["revision"] == 0
    assert server.calls_to("append_to_stream") == []


def test_save_then_load_round_trip(server, tmp_path):
    storage = _storage(server)
    assert storage.save(_summaries(), None, user_id="alice", expected_revision=0) is True
    revision = storage.load(AGENT, user_id="alice")["revision"]
    facts = [_fact("fact_b", "Prefers Python"), _fact("fact_a", "Uses uv", topics=["tools"])]
    assert storage.save({"facts": facts}, AGENT, user_id="alice", expected_revision=revision) is True

    # A cold instance folds the same state from the stream alone.
    document = _storage(server).load(AGENT, user_id="alice")
    assert document["revision"] == _head(server, ALICE_STREAM) + 1
    assert document["version"] == "2.0"

    # Parity with the file storage for the same calls (facts normalized the same way).
    file_storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert file_storage.save(_summaries(), None, user_id="alice", expected_revision=0) is True
    assert file_storage.save({"facts": facts}, AGENT, user_id="alice", expected_revision=file_storage.load(AGENT, user_id="alice")["revision"]) is True
    expected = file_storage.load(AGENT, user_id="alice")
    assert document["facts"] == expected["facts"]
    assert [fact["id"] for fact in document["facts"]] == ["fact_a", "fact_b"]
    assert document["user"] == expected["user"]
    assert document["history"] == expected["history"]

    # Updating one fact bumps only that fact's revision; omitting one deletes it.
    updated = [dict(document["facts"][0], content="Uses uv everywhere")]
    assert storage.save({"facts": updated}, AGENT, user_id="alice", expected_revision=document["revision"]) is True
    after = _storage(server).load(AGENT, user_id="alice")
    assert [(fact["id"], fact["revision"], fact["content"]) for fact in after["facts"]] == [("fact_a", 2, "Uses uv everywhere")]
    assert after["user"] == expected["user"]


def test_save_summaries_only_on_global_scope(server):
    storage = _storage(server)
    # An agent save carries the agent's facts only; summaries in the payload are ignored.
    assert storage.save({**_summaries(work="ignored"), "facts": [_fact("fact_1", "Likes tea")]}, AGENT, user_id="alice", expected_revision=0) is True
    document = storage.load(AGENT, user_id="alice")
    assert document["user"]["workContext"]["summary"] == ""
    assert [fact["id"] for fact in document["facts"]] == ["fact_1"]

    # The global scope persists summaries only, and refuses facts.
    assert storage.save({**_summaries(), "facts": [_fact("fact_2", "x")]}, None, user_id="alice") is False
    assert storage.save(_summaries(), None, user_id="alice") is True
    assert storage.load(None, user_id="alice")["facts"] == []
    assert storage.load(AGENT, user_id="alice")["user"]["workContext"]["summary"] == "Builds DeerFlow"
    # An agent save needs an explicit fact list.
    assert storage.save(_summaries(), AGENT, user_id="alice") is False

    events = [json.loads(event.data) for event in server.sync_client().get_stream(ALICE_STREAM)]
    assert {event["agent"] for event in events if "fact" in event} == {AGENT}
    assert all("id" in event and "agent" in event for event in events)


def test_save_with_stale_expected_revision_conflicts(server):
    storage = _storage(server)
    other = _storage(server)
    assert storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0) is True
    head = _head(server, ALICE_STREAM)
    with pytest.raises(MemoryManifestRevisionConflict):
        other.save({"facts": [_fact("fact_2", "two")]}, AGENT, user_id="alice", expected_revision=0)
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.save({"facts": []}, AGENT, user_id="alice", expected_revision=head + 7)
    assert _head(server, ALICE_STREAM) == head
    assert [fact["id"] for fact in other.load(AGENT, user_id="alice")["facts"]] == ["fact_1"]


def test_revision_monotonic_may_skip(server):
    storage = _storage(server)
    assert storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0) is True
    first = storage.load(AGENT, user_id="alice")["revision"]
    assert first == 1

    # A no-op change set appends nothing and keeps the revision.
    assert storage.save({"facts": storage.load(AGENT, user_id="alice")["facts"]}, AGENT, user_id="alice", expected_revision=first) is True
    assert storage.load(AGENT, user_id="alice")["revision"] == first

    # A multi-event change set advances the revision by more than one.
    assert storage.save({"facts": [_fact("fact_1", "one"), _fact("fact_2", "two"), _fact("fact_3", "three")]}, AGENT, user_id="alice", expected_revision=first) is True
    second = storage.load(AGENT, user_id="alice")["revision"]
    assert second == first + 2

    # A lost-request append is fenced; the fence advances the revision too.
    server.fail_next("append_to_stream", DeadlineExceededError("lost"), stream_name=ALICE_STREAM)
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.save({"facts": []}, AGENT, user_id="alice", expected_revision=second)
    third = storage.load(AGENT, user_id="alice")["revision"]
    assert third == second + 1
    assert third == _head(server, ALICE_STREAM) + 1
    assert len(storage.load(AGENT, user_id="alice")["facts"]) == 3


def test_load_checks_head_and_folds_incrementally(server):
    writer = _storage(server)
    revision = 0
    for index in range(40):
        assert writer.save({"facts": [_fact(f"fact_{i}", f"fact {i}") for i in range(index + 1)]}, AGENT, user_id="alice", expected_revision=revision) is True
        revision = writer.load(AGENT, user_id="alice")["revision"]

    reader = _storage(server)
    assert len(reader.load(AGENT, user_id="alice")["facts"]) == 40

    # Unchanged head: one cheap head check, no event reads.
    server.calls.clear()
    for _ in range(3):
        assert len(reader.load(AGENT, user_id="alice")["facts"]) == 40
    assert [call.method for call in server.calls] == ["get_current_version"] * 3

    # Moved head: read only the new events.
    head = _head(server, ALICE_STREAM)
    assert writer.save({"facts": [_fact(f"fact_{i}", f"fact {i}") for i in range(41)]}, AGENT, user_id="alice", expected_revision=revision) is True
    server.calls.clear()
    document = reader.load(AGENT, user_id="alice")
    storage_calls = list(server.calls)
    assert len(document["facts"]) == 41
    reads = server.calls_to("get_stream")
    assert len(reads) == 1
    assert reads[0].kwargs["stream_position"] == head + 1
    assert reads[0].kwargs["backwards"] is False
    assert document["revision"] == _head(server, ALICE_STREAM) + 1
    # Every client call carries the configured deadline (R7).
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in storage_calls)

    # reload() agrees with the incremental fold.
    assert reader.reload(AGENT, user_id="alice") == document
    assert _storage(server).reload(AGENT, user_id="alice") == document


def test_reload_is_head_checked_and_incremental(server):
    """DeerMem reloads on every manifest-conflict retry: it must not re-read the history since the last snapshot."""
    writer = _storage(server)
    revision = 0
    for index in range(40):
        assert writer.save({"facts": [_fact(f"fact_{i}", f"fact {i}") for i in range(index + 1)]}, AGENT, user_id="alice", expected_revision=revision) is True
        revision = writer.load(AGENT, user_id="alice")["revision"]
    reader = _storage(server)
    assert len(reader.reload(AGENT, user_id="alice")["facts"]) == 40

    # Unchanged head: one head check, no event reads.
    server.calls.clear()
    assert len(reader.reload(AGENT, user_id="alice")["facts"]) == 40
    assert [call.method for call in server.calls] == ["get_current_version"]

    # Moved head: one forward read of only the new events.
    head = _head(server, ALICE_STREAM)
    assert writer.save({"facts": [_fact(f"fact_{i}", f"fact {i}") for i in range(41)]}, AGENT, user_id="alice", expected_revision=revision) is True
    server.calls.clear()
    document = reader.reload(AGENT, user_id="alice")
    assert len(document["facts"]) == 41
    reads = server.calls_to("get_stream")
    assert len(reads) == 1
    assert reads[0].kwargs["stream_position"] == head + 1
    assert reads[0].kwargs["backwards"] is False
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)


def test_reload_folds_from_newest_snapshot(server):
    from deerflow_extension_kurrentdb.memory import events

    storage = _storage(server)
    assert storage.save({"facts": [_fact("fact_old", "old")]}, AGENT, user_id="alice", expected_revision=0) is True
    cached = _storage(server)
    assert [fact["id"] for fact in cached.load(AGENT, user_id="alice")["facts"]] == ["fact_old"]
    snapshot_fact = storage.load(AGENT, user_id="alice")["facts"][0] | {"id": "fact_snap", "content": "from snapshot"}
    change_set = str(uuid.uuid4())
    snapshot = events.new_event(events.MEMORY_SNAPSHOT, change_set, 0, {"agent": None, "state": {"user": _summaries()["user"], "history": {}, "facts": {AGENT: [snapshot_fact]}, "lastUpdated": "2026-11-02T00:00:00Z"}})
    client = server.sync_client()
    client.append_to_stream(ALICE_STREAM, events=[snapshot], current_version=_head(server, ALICE_STREAM))
    client.set_stream_metadata(ALICE_STREAM, metadata={"$tb": _head(server, ALICE_STREAM)})

    for reader in (_storage(server), storage):
        document = reader.reload(AGENT, user_id="alice")
        assert [fact["id"] for fact in document["facts"]] == ["fact_snap"]
        assert document["user"]["workContext"]["summary"] == "Builds DeerFlow"
        assert document["revision"] == _head(server, ALICE_STREAM) + 1
    # A warm cache picks up the snapshot after truncation on a plain load.
    assert [fact["id"] for fact in cached.load(AGENT, user_id="alice")["facts"]] == ["fact_snap"]
    assert [fact["id"] for fact in _storage(server).load(AGENT, user_id="alice")["facts"]] == ["fact_snap"]


def test_two_instances_read_after_write(server):
    first, second = _storage(server), _storage(server)
    assert second.load(AGENT, user_id="alice")["facts"] == []
    assert first.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0) is True
    assert [fact["id"] for fact in second.load(AGENT, user_id="alice")["facts"]] == ["fact_1"]
    revision = second.load(AGENT, user_id="alice")["revision"]
    assert second.save({"facts": [_fact("fact_1", "one"), _fact("fact_2", "two")]}, AGENT, user_id="alice", expected_revision=revision) is True
    assert [fact["id"] for fact in first.load(AGENT, user_id="alice")["facts"]] == ["fact_1", "fact_2"]
    # Scopes stay disjoint.
    assert first.load(AGENT, user_id="bob")["facts"] == []
    assert first.load(AGENT)["facts"] == []
    assert _head(server, GLOBAL_STREAM) is StreamState.NO_STREAM


def test_two_instances_clear_visible(server):
    first, second = _storage(server), _storage(server)
    assert first.save(_summaries(), None, user_id="alice") is True
    assert first.save({"facts": [_fact("fact_1", "one")]}, "researcher", user_id="alice") is True
    assert second.load("researcher", user_id="alice")["facts"]

    assert first.save({"facts": []}, "researcher", user_id="alice") is True
    assert first.save({"user": {}, "history": {}}, None, user_id="alice") is True  # no-op: summaries merge per section
    empty = {"user": {"workContext": {"summary": "", "updatedAt": ""}}, "history": {"recentMonths": {"summary": "", "updatedAt": ""}}}
    assert first.save(empty, None, user_id="alice") is True

    document = second.load("researcher", user_id="alice")
    assert document["facts"] == []
    assert document["user"]["workContext"]["summary"] == ""
    assert document["history"]["recentMonths"]["summary"] == ""


def test_concurrent_saves_from_threads_serialize_per_scope(server):
    import threading

    storage = _storage(server)
    errors: list[BaseException] = []

    def add(index: int) -> None:
        try:
            for _ in range(20):
                document = storage.load(AGENT, user_id="alice")
                try:
                    storage.save({"facts": [*document["facts"], _fact(f"fact_{index}", f"fact {index}")]}, AGENT, user_id="alice", expected_revision=document["revision"])
                    return
                except MemoryManifestRevisionConflict:
                    continue
            raise AssertionError(f"thread {index} never committed")
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert [fact["id"] for fact in _storage(server).load(AGENT, user_id="alice")["facts"]] == [f"fact_{index}" for index in range(8)]


# --- ambiguous outcomes and failures --------------------------------------------


def test_ambiguous_save_committed_via_fence(server):
    storage = _storage(server)
    server.fail_next("append_to_stream", DeadlineExceededError("ack lost"), after_commit=True)
    assert storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0) is True
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)
    # One original append plus one rejected fence; the change set is never re-appended.
    assert len(server.calls_to("append_to_stream")) == 2
    assert _types(server, ALICE_STREAM).count("deerflow.memory.FactUpserted") == 1
    assert "deerflow.Fence" not in _types(server, ALICE_STREAM)
    assert [fact["id"] for fact in storage.load(AGENT, user_id="alice")["facts"]] == ["fact_1"]
    assert [fact["id"] for fact in _storage(server).load(AGENT, user_id="alice")["facts"]] == ["fact_1"]


def test_ambiguous_save_not_committed_raises_conflict(server):
    storage = _storage(server)
    server.fail_next("append_to_stream", DeadlineExceededError("request lost"))
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0)
    assert _types(server, ALICE_STREAM) == ["deerflow.Fence"]
    document = storage.load(AGENT, user_id="alice")
    assert document["facts"] == []
    assert document["revision"] == 1

    # A delayed server commit racing the fence can never land.
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("slow"))
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=1)
    pending.release()
    assert pending.committed is False
    assert _storage(server).load(AGENT, user_id="alice")["facts"] == []


def test_transport_failure_raises_memory_read_error(server):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryReadError

    storage = _storage(server)
    assert storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="alice", expected_revision=0) is True
    assert storage.load(AGENT, user_id="alice")["facts"]

    server.set_unavailable(ServiceUnavailableError("down"))
    # A warm cache is no excuse: the head check fails, so the read fails.
    for call in (lambda: storage.load(AGENT, user_id="alice"), lambda: storage.reload(AGENT, user_id="alice"), lambda: _storage(server).load(AGENT, user_id="alice")):
        with pytest.raises(KurrentdbMemoryReadError) as caught:
            call()
        assert isinstance(caught.value, MemoryReadError)
    with pytest.raises(KurrentdbMemoryReadError):
        storage.save({"facts": []}, AGENT, user_id="alice")
    server.set_unavailable(None)

    # The append and its fence both fail: unknown outcome, read error, no re-append.
    server.fail_next("append_to_stream", DeadlineExceededError("lost"), stream_name=ALICE_STREAM)
    server.fail_next("append_to_stream", ServiceUnavailableError("fence down"), stream_name=ALICE_STREAM)
    revision = storage.load(AGENT, user_id="alice")["revision"]
    server.calls.clear()
    with pytest.raises(KurrentdbMemoryReadError):
        storage.save({"facts": []}, AGENT, user_id="alice", expected_revision=revision)
    assert len(server.calls_to("append_to_stream", ALICE_STREAM)) == 2

    # A client that cannot be created is a read error too.
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    def refuse():
        raise ConnectionError("no route")

    with pytest.raises(KurrentdbMemoryReadError):
        KurrentdbMemoryStorage(DeerMemConfig(), client_factory=refuse).load(AGENT, user_id="alice")


def test_unknown_event_type_is_corruption(server):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryReadError

    client = server.sync_client()
    client.append_to_stream(ALICE_STREAM, events=[NewEvent(type="deerflow.memory.Bogus", data=b'{"id": "x", "agent": null}')], current_version=StreamState.NO_STREAM)
    with pytest.raises(MemoryStorageCorruption):
        _storage(server).load(AGENT, user_id="alice")

    # An invariant violation: a fact event without an agent bucket.
    client.append_to_stream("deerflow.memory-user.bob", events=[NewEvent(type="deerflow.memory.FactUpserted", data=json.dumps({"id": "x", "agent": None, "fact": {"id": "f"}}).encode())], current_version=StreamState.NO_STREAM)
    with pytest.raises(MemoryStorageCorruption):
        _storage(server).load(AGENT, user_id="bob")

    # Undecodable data is persistent bad state too, not a transient read failure.
    client.append_to_stream("deerflow.memory-user.carol", events=[NewEvent(type="deerflow.memory.SummariesUpdated", data=b"\xff not json")], current_version=StreamState.NO_STREAM)
    with pytest.raises(MemoryStorageCorruption) as caught:
        _storage(server).load(AGENT, user_id="carol")
    assert not isinstance(caught.value, KurrentdbMemoryReadError)

    # Events of an unknown type found by an incremental fold are corruption too.
    storage = _storage(server)
    assert storage.save({"facts": []}, AGENT, user_id="dave", expected_revision=0) is True
    assert storage.save({"facts": [_fact("fact_1", "one")]}, AGENT, user_id="dave", expected_revision=0) is True
    storage.load(AGENT, user_id="dave")
    client.append_to_stream("deerflow.memory-user.dave", events=[NewEvent(type="Unrelated", data=b"{}")], current_version=StreamState.ANY)
    with pytest.raises(MemoryStorageCorruption):
        storage.load(AGENT, user_id="dave")


# --- wiring ---------------------------------------------------------------------


def _patch_client(monkeypatch, server: FakeKurrentDB) -> list:
    import deerflow_extension_kurrentdb.memory.storage as storage_module

    created: list = []

    def factory(settings):
        def get_client():
            created.append(settings)
            return server.sync_client()

        return get_client

    monkeypatch.setattr(storage_module, "sync_client_factory", factory)
    return created


def test_storage_class_dotted_path_loads_via_create_storage(server, monkeypatch):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    created = _patch_client(monkeypatch, server)
    storage = create_storage(DeerMemConfig(storage_class=STORAGE_CLASS))
    assert isinstance(storage, KurrentdbMemoryStorage)
    assert created == [], "construction must not connect"
    assert storage.save(_summaries(), None, user_id="alice") is True
    assert created and created[0].timeout == TIMEOUT
    assert storage.load(AGENT, user_id="alice")["user"]["workContext"]["summary"] == "Builds DeerFlow"

    # Missing settings fail at construction, naming the variable, before any connect.
    monkeypatch.delenv("KURRENTDB_CONNECTION_STRING")
    with pytest.raises(ValueError, match="KURRENTDB_CONNECTION_STRING"):
        create_storage(DeerMemConfig(storage_class=STORAGE_CLASS))


def test_gateway_maps_read_error_and_corruption(server, monkeypatch):
    from app.gateway.routers import memory as memory_router
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

    _patch_client(monkeypatch, server)
    manager = DeerMem(backend_config={"storage_class": STORAGE_CLASS})
    app = make_authed_test_app()
    app.include_router(memory_router.router)

    def get(path: str):
        with patch("app.gateway.routers.memory.get_memory_manager", return_value=manager), TestClient(app, raise_server_exceptions=False) as client:
            return client.get(path)

    assert get("/api/memory").status_code == 200

    # Transport failure: the public MemoryReadError reaches the manager caller untouched.
    server.set_unavailable(ServiceUnavailableError("down"))
    with pytest.raises(MemoryReadError):
        manager.get_memory(user_id="alice")
    response = get("/api/memory")
    assert response.status_code == 500
    server.set_unavailable(None)

    # Corruption: translated to MemoryCorruptionError and the stable 500 detail.
    with patch("app.gateway.routers.memory.get_effective_user_id", return_value="mallory"):
        server.sync_client().append_to_stream("deerflow.memory-user.mallory", events=[NewEvent(type="deerflow.memory.Bogus", data=b"{}")], current_version=StreamState.NO_STREAM)
        with pytest.raises(MemoryCorruptionError):
            manager.get_memory(user_id="mallory")
        response = get("/api/memory")
    assert response.status_code == 500
    assert response.json()["detail"] == "Stored memory data is corrupted."


# --- change sets, clears and fact lookup ------------------------------------------


def _appends(server: FakeKurrentDB, stream: str = ALICE_STREAM) -> int:
    return len(server.calls_to("append_to_stream", stream))


def _seed(storage, facts: list[dict], *, agent: str = AGENT, user: str = "alice") -> dict:
    """Create ``facts`` in one change set and return the scope's fresh document."""
    revision = storage.load(agent, user_id=user)["revision"]
    storage.apply_changes({"upserts": facts, "upsertRevisions": {fact["id"]: None for fact in facts}}, agent_name=agent, user_id=user, expected_manifest_revision=revision)
    return storage.load(agent, user_id=user)


def _facts_by_id(document: dict) -> dict[str, dict]:
    return {fact["id"]: fact for fact in document["facts"]}


def test_apply_changes_multi_fact_single_append(server, tmp_path):
    import deerflow_extension_kurrentdb.memory.changes as changes_module

    from deerflow.agents.memory.backends.deermem.deermem.core import storage as deermem_storage

    # Facts are normalized by DeerMem's own function, not a copy.
    assert changes_module._normalize_fact is deermem_storage._normalize_fact

    storage = _storage(server)
    file_storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    change_set = {
        "upserts": [_fact("fact_b", "Prefers Python"), _fact("fact_a", "Uses uv"), _fact("fact_c", "Drinks tea")],
        "upsertRevisions": {"fact_a": None, "fact_b": None, "fact_c": None},
        # Agent-scoped extraction updates carry summaries; they persist with the facts.
        "summaries": _summaries(),
    }
    server.calls.clear()
    result = storage.apply_changes(json.loads(json.dumps(change_set)), agent_name=AGENT, user_id="alice", expected_manifest_revision=0)
    assert _appends(server) == 1
    expected = file_storage.apply_changes(json.loads(json.dumps(change_set)), agent_name=AGENT, user_id="alice", expected_manifest_revision=0)
    assert result["complete"] is False
    assert result["revision"] == _head(server, ALICE_STREAM) + 1
    assert set(result) >= {"complete", "version", "revision", "lastUpdated", "upsertedFacts", "deletedFactIds"}
    assert sorted(fact["id"] for fact in result["upsertedFacts"]) == ["fact_a", "fact_b", "fact_c"]
    assert result["deletedFactIds"] == []
    assert sorted(result["upsertedFacts"], key=lambda fact: fact["id"]) == sorted(expected["upsertedFacts"], key=lambda fact: fact["id"])

    document = _storage(server).load(AGENT, user_id="alice")
    assert document["revision"] == result["revision"]
    assert document["facts"] == file_storage.load(AGENT, user_id="alice")["facts"]
    assert document["user"]["workContext"]["summary"] == "Builds DeerFlow"
    assert document["history"]["recentMonths"]["summary"] == "Shipped KurrentDB"

    # Mixed: update one, create one, delete one. Still exactly one append to the memory stream.
    facts = _facts_by_id(document)
    mixed = {
        "upserts": [dict(facts["fact_a"], content="Uses uv everywhere"), _fact("fact_d", "Runs KurrentDB")],
        "upsertRevisions": {"fact_a": 1, "fact_d": None},
        "deletes": ["fact_b"],
        "deleteRevisions": {"fact_b": 1},
    }
    server.calls.clear()
    result = storage.apply_changes(mixed, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])
    assert _appends(server) == 1
    assert [(fact["id"], fact["revision"]) for fact in sorted(result["upsertedFacts"], key=lambda fact: fact["id"])] == [("fact_a", 2), ("fact_d", 1)]
    assert result["deletedFactIds"] == ["fact_b"]
    for reader in (storage, _storage(server)):
        after = reader.load(AGENT, user_id="alice")
        assert after["revision"] == result["revision"] == _head(server, ALICE_STREAM) + 1
        assert [(fact["id"], fact["revision"], fact["content"]) for fact in after["facts"]] == [("fact_a", 2, "Uses uv everywhere"), ("fact_c", 1, "Drinks tea"), ("fact_d", 1, "Runs KurrentDB")]
        assert after["user"]["workContext"]["summary"] == "Builds DeerFlow"

    # Fact changes need an agent bucket.
    with pytest.raises(ValueError):
        storage.apply_changes({"upserts": [_fact("fact_x", "x")]}, user_id="alice")


def test_apply_changes_noop_keeps_revision(server):
    storage = _storage(server)
    document = _seed(storage, [_fact("fact_1", "one"), _fact("fact_2", "two")])
    revision = document["revision"]
    server.calls.clear()
    for change_set in (
        {},
        {"upserts": [], "deletes": []},
        # Re-upserting a fact unchanged at its current revision.
        {"upserts": [document["facts"][0]], "upsertRevisions": {"fact_1": 1}},
        # Deleting a fact that does not exist.
        {"deletes": ["fact_missing"], "deleteRevisions": {"fact_missing": 1}},
        # Summaries equal to the stored ones.
        {"summaries": {"user": {}, "history": {}}},
    ):
        result = storage.apply_changes(change_set, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
        assert result["revision"] == revision
        assert result["upsertedFacts"] == []
        assert result["deletedFactIds"] == []
        assert result["complete"] is False
    assert _appends(server) == 0
    assert storage.load(AGENT, user_id="alice")["revision"] == revision


def test_apply_changes_fact_revision_conflict(server):
    storage = _storage(server)
    document = _seed(storage, [_fact("fact_1", "one")])
    fact = document["facts"][0]
    storage.apply_changes({"upserts": [dict(fact, content="one, revised")], "upsertRevisions": {"fact_1": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])
    revision = storage.load(AGENT, user_id="alice")["revision"]
    server.calls.clear()
    for change_set in (
        # Stale expected fact revision.
        {"upserts": [dict(fact, content="stale edit")], "upsertRevisions": {"fact_1": 1}},
        # A create of a fact that already exists.
        {"upserts": [_fact("fact_1", "duplicate create")], "upsertRevisions": {"fact_1": None}},
        # A delete at the wrong revision.
        {"deletes": ["fact_1"], "deleteRevisions": {"fact_1": 1}},
    ):
        with pytest.raises(MemoryFactRevisionConflict):
            storage.apply_changes(change_set, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
        with pytest.raises(MemoryFactRevisionConflict):
            storage.apply_changes(change_set, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision, allow_manifest_rebase=True)
    assert _appends(server) == 0
    assert [(f["revision"], f["content"]) for f in storage.load(AGENT, user_id="alice")["facts"]] == [(2, "one, revised")]


def test_apply_changes_manifest_conflict_without_rebase(server):
    first, second = _storage(server), _storage(server)
    document = _seed(first, [_fact("fact_1", "one")])
    stale = document["revision"]
    _seed(second, [_fact("fact_2", "two")])
    head = _head(server, ALICE_STREAM)
    for change_set, rebase in (
        ({"upserts": [_fact("fact_3", "three")], "upsertRevisions": {"fact_3": None}}, False),
        # Summaries are never rebased.
        ({"upserts": [_fact("fact_3", "three")], "upsertRevisions": {"fact_3": None}, "summaries": _summaries()}, True),
        ({"summaries": _summaries()}, True),
        # Deletes without their expected revisions are never rebased.
        ({"deletes": ["fact_1"]}, True),
    ):
        with pytest.raises(MemoryManifestRevisionConflict):
            first.apply_changes(change_set, agent_name=AGENT, user_id="alice", expected_manifest_revision=stale, allow_manifest_rebase=rebase)
    assert _head(server, ALICE_STREAM) == head
    assert sorted(_facts_by_id(first.load(AGENT, user_id="alice"))) == ["fact_1", "fact_2"]


def test_apply_changes_rebase_disjoint_edits(server):
    first, second = _storage(server), _storage(server)
    document = _seed(first, [_fact("fact_1", "one"), _fact("fact_2", "two")])
    stale = document["revision"]
    # Another writer moves the manifest revision with a disjoint change.
    _seed(second, [_fact("fact_3", "three")])

    result = first.apply_changes(
        {"upserts": [dict(_facts_by_id(document)["fact_1"], content="one, revised")], "upsertRevisions": {"fact_1": 1}, "deletes": ["fact_2"], "deleteRevisions": {"fact_2": 1}},
        agent_name=AGENT,
        user_id="alice",
        expected_manifest_revision=stale,
        allow_manifest_rebase=True,
    )
    assert result["deletedFactIds"] == ["fact_2"]
    after = second.load(AGENT, user_id="alice")
    assert after["revision"] == result["revision"] == _head(server, ALICE_STREAM) + 1
    assert [(fact["id"], fact["revision"]) for fact in after["facts"]] == [("fact_1", 2), ("fact_3", 1)]

    # An overlapping edit is re-checked after the rebase and conflicts, writing nothing.
    stale = after["revision"]
    second.apply_changes({"upserts": [dict(_facts_by_id(after)["fact_3"], content="three, by second")], "upsertRevisions": {"fact_3": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=stale)
    head = _head(server, ALICE_STREAM)
    with pytest.raises(MemoryFactRevisionConflict):
        first.apply_changes({"upserts": [dict(_facts_by_id(after)["fact_3"], content="three, by first")], "upsertRevisions": {"fact_3": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=stale, allow_manifest_rebase=True)
    assert _head(server, ALICE_STREAM) == head
    assert _facts_by_id(first.load(AGENT, user_id="alice"))["fact_3"]["content"] == "three, by second"

    # A lost append fenced off is a conflict too; the rebase re-appends at the new head, once.
    revision = first.load(AGENT, user_id="alice")["revision"]
    server.fail_next("append_to_stream", DeadlineExceededError("request lost"))
    result = first.apply_changes({"upserts": [_fact("fact_4", "four")], "upsertRevisions": {"fact_4": None}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision, allow_manifest_rebase=True)
    assert [fact["id"] for fact in result["upsertedFacts"]] == ["fact_4"]
    assert _types(server, ALICE_STREAM).count("deerflow.Fence") == 1
    upserted = [json.loads(event.data)["fact"]["id"] for event in server.sync_client().get_stream(ALICE_STREAM) if event.type == "deerflow.memory.FactUpserted"]
    assert upserted.count("fact_4") == 1
    assert "fact_4" in _facts_by_id(_storage(server).load(AGENT, user_id="alice"))


def test_apply_changes_never_partial_on_conflict(server):
    storage = _storage(server)
    document = _seed(storage, [_fact("fact_1", "one"), _fact("fact_2", "two")])
    revision = document["revision"]
    storage.apply_changes({"upserts": [dict(document["facts"][1], content="two, revised")], "upsertRevisions": {"fact_2": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
    revision = storage.load(AGENT, user_id="alice")["revision"]
    head = _head(server, ALICE_STREAM)

    # A valid create, a valid delete and summaries ride with one stale update: none of it lands.
    change_set = {
        "upserts": [_fact("fact_new", "new"), dict(document["facts"][1], content="stale")],
        "upsertRevisions": {"fact_new": None, "fact_2": 1},
        "deletes": ["fact_1"],
        "deleteRevisions": {"fact_1": 1},
        "summaries": _summaries(),
    }
    with pytest.raises(MemoryFactRevisionConflict):
        storage.apply_changes(change_set, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
    # Invalid input is rejected before anything is written.
    with pytest.raises(ValueError):
        storage.apply_changes({"upserts": [_fact("fact_ok", "ok"), _fact("fact_ok", "dup")]}, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
    with pytest.raises(ValueError):
        storage.apply_changes({"upserts": [_fact("fact_x", "x")], "upsertRevisions": {"fact_x": None}, "deletes": ["fact_x"]}, agent_name=AGENT, user_id="alice", expected_manifest_revision=revision)
    assert _head(server, ALICE_STREAM) == head

    # A fenced-off append without rebase raises, leaving the scope as it was.
    server.fail_next("append_to_stream", DeadlineExceededError("request lost"), stream_name=ALICE_STREAM)
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.apply_changes(
            {**change_set, "upserts": [_fact("fact_new", "new"), dict(document["facts"][1], content="lost", revision=2)], "upsertRevisions": {"fact_new": None, "fact_2": 2}},
            agent_name=AGENT,
            user_id="alice",
            expected_manifest_revision=revision,
        )
    for reader in (storage, _storage(server)):
        after = reader.load(AGENT, user_id="alice")
        assert [(fact["id"], fact["content"]) for fact in after["facts"]] == [("fact_1", "one"), ("fact_2", "two, revised")]
        assert after["user"]["workContext"]["summary"] == ""
    assert _types(server, ALICE_STREAM)[-1] == "deerflow.Fence"


def test_deletes_and_clears_write_a_snapshot_boundary(server):
    """Every destructive change set is one append whose newest snapshot holds the resulting state."""
    from deerflow_extension_kurrentdb.memory import events

    storage = _storage(server)
    _seed(storage, [_fact("fact_keep", "keep"), _fact("fact_secret", "first secret"), _fact("fact_gone", "second secret")])
    _seed(storage, [_fact("fact_r", "third secret")], agent="researcher")
    document = storage.load(AGENT, user_id="alice")
    for removed, call in (
        ("first secret", lambda: storage.apply_changes({"deletes": ["fact_secret"], "deleteRevisions": {"fact_secret": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])),
        ("second secret", lambda: storage.save({"facts": [_facts_by_id(storage.load(AGENT, user_id="alice"))["fact_keep"]]}, AGENT, user_id="alice")),
        ("third secret", lambda: storage.apply_changes({"deletes": ["fact_r"], "deleteRevisions": {"fact_r": 1}}, agent_name="researcher", user_id="alice")),
    ):
        server.calls.clear()
        call()
        assert _appends(server) == 1
        recorded = server.sync_client().get_stream(ALICE_STREAM)
        assert recorded[-1].type == events.MEMORY_SNAPSHOT
        assert removed not in recorded[-1].data.decode()
        assert "keep" in recorded[-1].data.decode()
    for reader in (storage, _storage(server)):
        assert [fact["id"] for fact in reader.reload(AGENT, user_id="alice")["facts"]] == ["fact_keep"]
        assert reader.load("researcher", user_id="alice")["facts"] == []

    server.calls.clear()
    storage.clear_all(user_id="alice")
    assert _appends(server) == 1
    recorded = server.sync_client().get_stream(ALICE_STREAM)
    assert recorded[-1].type == events.MEMORY_SNAPSHOT
    assert "keep" not in recorded[-1].data.decode()


def test_clear_all_clears_every_agent_and_summaries(server):
    storage = _storage(server)
    assert storage.save(_summaries(), None, user_id="alice") is True
    _seed(storage, [_fact("fact_1", "one"), _fact("fact_2", "two")])
    _seed(storage, [_fact("fact_r", "research")], agent="researcher")
    _seed(storage, [_fact("fact_bob", "bob's")], user="bob")
    assert storage.save(_summaries(work="Bob's work"), None, user_id="bob") is True
    bob_head = _head(server, "deerflow.memory-user.bob")

    server.calls.clear()
    cleared = storage.clear_all(user_id="alice")
    assert _appends(server) == 1
    assert cleared["facts"] == []
    assert cleared["user"]["workContext"]["summary"] == ""
    assert cleared["revision"] == _head(server, ALICE_STREAM) + 1
    for reader in (storage, _storage(server)):
        for agent in (None, AGENT, "researcher"):
            document = reader.load(agent, user_id="alice")
            assert document["facts"] == []
            assert document["user"]["workContext"]["summary"] == ""
            assert document["history"]["recentMonths"]["summary"] == ""
            assert document["revision"] == cleared["revision"]
    # Other users are untouched.
    assert _head(server, "deerflow.memory-user.bob") == bob_head
    assert [fact["id"] for fact in storage.load(AGENT, user_id="bob")["facts"]] == ["fact_bob"]
    assert storage.load(None, user_id="bob")["user"]["workContext"]["summary"] == "Bob's work"

    # Clearing an already-empty scope is a no-op.
    server.calls.clear()
    assert storage.clear_all(user_id="alice")["revision"] == cleared["revision"]
    assert storage.clear_all(user_id="nobody")["revision"] == 0
    assert server.calls_to("append_to_stream") == []

    # Memory written after a clear is kept; the global scope clears the same way.
    _seed(storage, [_fact("fact_after", "after")])
    assert [fact["id"] for fact in _storage(server).load(AGENT, user_id="alice")["facts"]] == ["fact_after"]
    _seed(storage, [_fact("fact_g", "global")], user=None)
    assert storage.clear_all()["facts"] == []
    assert _storage(server).load(AGENT)["facts"] == []
    with pytest.raises(ValueError):
        _storage(server, DeerMemConfig(strict_user_scope=True)).clear_all()


def test_get_fact(server):
    storage = _storage(server)
    _seed(storage, [_fact("fact_1", "one")])
    fact = storage.get_fact("fact_1", agent_name=AGENT, user_id="alice")
    assert fact == storage.load(AGENT, user_id="alice")["facts"][0]
    fact["content"] = "mutated by caller"
    assert storage.get_fact("fact_1", agent_name=AGENT, user_id="alice")["content"] == "one"
    assert storage.get_fact("fact_missing", agent_name=AGENT, user_id="alice") is None
    assert storage.get_fact("fact_1", agent_name="researcher", user_id="alice") is None
    assert storage.get_fact("fact_1", agent_name=AGENT, user_id="bob") is None
    with pytest.raises(ValueError):
        storage.get_fact("fact_1", user_id="alice")

    # Fresh across instances: another instance's update and delete are visible.
    other = _storage(server)
    other.apply_changes({"upserts": [dict(fact, content="one, revised")], "upsertRevisions": {"fact_1": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=other.load(AGENT, user_id="alice")["revision"])
    assert storage.get_fact("fact_1", agent_name=AGENT, user_id="alice")["revision"] == 2
    other.apply_changes({"deletes": ["fact_1"], "deleteRevisions": {"fact_1": 2}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=other.load(AGENT, user_id="alice")["revision"])
    assert storage.get_fact("fact_1", agent_name=AGENT, user_id="alice") is None


def test_updater_end_to_end_with_kurrent_storage(server):
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    storage = _storage(server)
    updater = MemoryUpdater(DeerMemConfig(), storage, None)
    # The updater switches every repository path to apply_changes / clear_all / get_fact.
    assert type(storage).apply_changes is not type(storage).__mro__[1].apply_changes

    # Create.
    _, first_id = updater.create_memory_fact("Prefers Python", "preference", 0.9, AGENT, user_id="alice")
    _, second_id = updater.create_memory_fact("Uses uv", "preference", 0.8, AGENT, user_id="alice")
    assert first_id and second_id
    with pytest.raises(ValueError, match="Duplicate fact"):
        updater.create_memory_fact("Prefers Python", "preference", 0.9, AGENT, user_id="alice")
    assert sorted(_facts_by_id(_storage(server).load(AGENT, user_id="alice"))) == sorted([first_id, second_id])

    # Update.
    updated = updater.update_memory_fact(first_id, content="Prefers Python 3.12", agent_name=AGENT, user_id="alice")
    assert (_facts_by_id(updated)[first_id]["content"], _facts_by_id(updated)[first_id]["revision"]) == ("Prefers Python 3.12", 2)

    # Delete.
    remaining = updater.delete_memory_fact(second_id, AGENT, user_id="alice")
    assert list(_facts_by_id(remaining)) == [first_id]
    with pytest.raises(KeyError):
        updater.delete_memory_fact(second_id, AGENT, user_id="alice")

    # Agent-scoped extraction: new facts and summaries land in one change set.
    revision = storage.load(AGENT, user_id="alice")["revision"]
    response = json.dumps(
        {
            "user": {"workContext": {"summary": "Builds DeerFlow", "shouldUpdate": True, "scope": "user", "durability": "durable", "authority": "descriptive"}},
            "history": {},
            "newFacts": [{"content": "Runs KurrentDB locally", "category": "context", "confidence": 0.95, "scope": "user", "durability": "durable", "authority": "descriptive"}],
            "factsToRemove": [],
        }
    )
    server.calls.clear()
    assert updater._finalize_update(storage.load(AGENT, user_id="alice"), response, "thread-1", AGENT, user_id="alice") is True
    assert _appends(server) == 1
    extracted = _storage(server).load(AGENT, user_id="alice")
    assert extracted["revision"] > revision
    assert extracted["user"]["workContext"]["summary"] == "Builds DeerFlow"
    assert sorted(fact["content"] for fact in extracted["facts"]) == ["Prefers Python 3.12", "Runs KurrentDB locally"]

    # Import replaces the agent's facts (deleting the rest) and the shared summaries.
    imported = updater.import_memory_data({**_summaries(work="Imported work"), "facts": [_fact("fact_imported", "Imported fact")]}, AGENT, user_id="alice")
    assert [fact["id"] for fact in imported["facts"]] == ["fact_imported"]
    assert imported["user"]["workContext"]["summary"] == "Imported work"

    # Scoped clear keeps the shared summaries and the other agents.
    _seed(storage, [_fact("fact_r", "research")], agent="researcher")
    cleared = updater.clear_memory_data(AGENT, user_id="alice")
    assert cleared["facts"] == []
    assert cleared["user"]["workContext"]["summary"] == "Imported work"
    assert [fact["id"] for fact in storage.load("researcher", user_id="alice")["facts"]] == ["fact_r"]

    # Clear all.
    everything = updater.clear_all_memory_data(user_id="alice")
    assert everything["facts"] == []
    cold = _storage(server)
    for agent in (None, AGENT, "researcher"):
        document = cold.load(agent, user_id="alice")
        assert document["facts"] == []
        assert document["user"]["workContext"]["summary"] == ""
