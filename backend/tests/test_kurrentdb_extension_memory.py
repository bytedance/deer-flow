"""Event-sourced DeerMem storage on KurrentDB: stream, fold, load/reload, save, revisions."""

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
    server.fail_next("append_to_stream", DeadlineExceededError("lost"))
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

    # reload() re-reads from scratch and agrees with the incremental fold.
    server.calls.clear()
    assert reader.reload(AGENT, user_id="alice") == document
    assert server.calls_to("get_stream")


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
    server.fail_next("append_to_stream", DeadlineExceededError("lost"))
    server.fail_next("append_to_stream", ServiceUnavailableError("fence down"))
    revision = storage.load(AGENT, user_id="alice")["revision"]
    server.calls.clear()
    with pytest.raises(KurrentdbMemoryReadError):
        storage.save({"facts": []}, AGENT, user_id="alice", expected_revision=revision)
    assert len(server.calls_to("append_to_stream")) == 2

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

    # Undecodable data is a read failure, not corruption of the model.
    client.append_to_stream("deerflow.memory-user.carol", events=[NewEvent(type="deerflow.memory.SummariesUpdated", data=b"\xff not json")], current_version=StreamState.NO_STREAM)
    with pytest.raises(KurrentdbMemoryReadError):
        _storage(server).load(AGENT, user_id="carol")

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
