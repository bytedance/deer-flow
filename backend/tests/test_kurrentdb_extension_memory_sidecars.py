"""KurrentDB DeerMem sidecars: fact usage, eviction evidence and extraction watermarks in the memory-meta stream."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent
from kurrentdbclient.exceptions import ServiceUnavailableError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EvictedFact, FactEvictionDecision
from deerflow.agents.memory.backends.deermem.deermem.core.paths import agent_eviction_audit_path
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage, memory_file_path

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
AGENT = "__default__"
OTHER = "researcher"
ALICE_STREAM = "deerflow.memory-user.alice"
ALICE_META = "deerflow.memory-meta-user.alice"
BOB_META = "deerflow.memory-meta-user.bob"
T0 = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


class _MetaDown:
    """A client whose calls on memory-meta streams fail; the primary streams work."""

    def __init__(self, client, flag: dict):
        self._client = client
        self._flag = flag

    def __getattr__(self, name):
        method = getattr(self._client, name)

        def call(stream_name, *args, **kwargs):
            if self._flag["down"] and stream_name.startswith("deerflow.memory-meta"):
                raise ServiceUnavailableError("meta stream unavailable")
            return method(stream_name, *args, **kwargs)

        return call


def _storage(server: FakeKurrentDB, config: DeerMemConfig | None = None, *, intents=None, meta_down: dict | None = None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    client = server.sync_client()
    if meta_down is not None:
        client = _MetaDown(client, meta_down)
    kwargs = {} if intents is None else {"intents_provider": intents}
    return KurrentdbMemoryStorage(config or DeerMemConfig(), client_factory=lambda: client, **kwargs)


def _fact(fact_id: str, content: str) -> dict:
    return {"id": fact_id, "content": content, "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual"}


def _seed(storage, facts: list[str], agent: str = AGENT, user: str = "alice") -> None:
    assert storage.save({"facts": [_fact(fact_id, f"content of {fact_id}") for fact_id in facts]}, agent, user_id=user) is True


def _decision(evicted: list[str], *, policy: str = "confidence") -> FactEvictionDecision:
    return FactEvictionDecision(kept=[], evicted=[EvictedFact(fact_id=fact_id, category="preference", score=0.1, components={"confidence": 0.1}) for fact_id in evicted], scores={}, policy=policy)


def _record_all(storage, agent: str = AGENT, user: str = "alice") -> None:
    """Usage for fact_1/fact_2, eviction evidence naming fact_1 and fact_9, and one watermark."""
    storage.record_fact_accesses(["fact_1", "fact_2"], agent_name=agent, user_id=user, accessed_at=T0)
    storage.record_fact_accesses(["fact_1"], agent_name=agent, user_id=user, accessed_at=T0 + timedelta(days=3))
    storage.record_capacity_eviction(_decision(["fact_1", "fact_9"]), max_facts=5, agent_name=agent, user_id=user, occurred_at=T0, shadow_decision=_decision(["fact_1"], policy="hybrid_v1"))
    storage.set_extraction_watermark("thread-1", ["msg-1", "hello"], agent_name=agent, user_id=user)


def _types(server: FakeKurrentDB, stream: str) -> list[str]:
    return [event.type for event in server.sync_client().get_stream(stream)]


# --- round trips ----------------------------------------------------------------


def test_usage_round_trip(server, tmp_path):
    config = DeerMemConfig(storage_path=str(tmp_path), eviction_audit_max_entries=2)
    storage = _storage(server, config)
    file_storage = FileMemoryStorage(config)
    for target in (storage, file_storage):
        _seed(target, ["fact_1", "fact_2"])

    server.calls.clear()
    calls = [
        (["fact_1", "fact_2"], T0),
        (["fact_1", "fact_1", "missing"], T0 + timedelta(days=2)),
        (["fact_2"], T0 + timedelta(days=40)),
    ]
    for fact_ids, at in calls:
        for target in (storage, file_storage):
            target.record_fact_accesses(fact_ids, agent_name=AGENT, user_id="alice", accessed_at=at)
    # One append per call to the meta stream; the meta stream is never read before writing.
    assert len(server.calls_to("append_to_stream", ALICE_META)) == len(calls)
    assert server.calls_to("get_stream", ALICE_META) == [] and server.calls_to("get_current_version", ALICE_META) == []
    assert server.calls_to("append_to_stream", ALICE_STREAM) == []
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)

    expected = file_storage.get_fact_usage(agent_name=AGENT, user_id="alice")
    assert set(expected) == {"fact_1", "fact_2"}
    assert storage.get_fact_usage(agent_name=AGENT, user_id="alice") == expected
    assert _storage(server, config).get_fact_usage(agent_name=AGENT, user_id="alice") == expected
    # Usage never moves the primary revision, and is scoped per agent and user.
    assert storage.load(AGENT, user_id="alice")["revision"] == server.sync_client().get_current_version(ALICE_STREAM) + 1
    assert storage.get_fact_usage(agent_name=OTHER, user_id="alice") == {}
    assert storage.get_fact_usage(agent_name=AGENT, user_id="bob") == {}

    # Nothing to record appends nothing.
    server.calls.clear()
    storage.record_fact_accesses([], agent_name=AGENT, user_id="alice")
    storage.record_fact_accesses(["missing"], agent_name=AGENT, user_id="alice")
    assert server.calls_to("append_to_stream") == []

    # Every record carries agent, fact ids and the primary revision it was written under.
    data = [json.loads(event.data) for event in server.sync_client().get_stream(ALICE_META)]
    revision = storage.load(AGENT, user_id="alice")["revision"]
    assert [(item["agent"], item["revision"]) for item in data] == [(AGENT, revision)] * 3
    assert data[1]["factIds"] == ["fact_1"]

    # Eviction evidence matches the file storage's bounded audit.
    for index in range(3):
        for target in (storage, file_storage):
            target.record_capacity_eviction(_decision([f"fact_{index}"]), max_facts=5, agent_name=AGENT, user_id="alice", occurred_at=T0 + timedelta(days=index), shadow_decision=_decision(["fact_x"]))
    file_audit = json.loads(agent_eviction_audit_path(memory_file_path(config, AGENT, user_id="alice"), AGENT).read_text())
    assert len(file_audit) == 2
    assert storage.get_eviction_audit(agent_name=AGENT, user_id="alice") == file_audit
    assert _storage(server, config).get_eviction_audit(agent_name=AGENT, user_id="alice") == file_audit
    # An empty decision, or a disabled audit, writes nothing.
    server.calls.clear()
    storage.record_capacity_eviction(_decision([]), max_facts=5, agent_name=AGENT, user_id="alice")
    _storage(server, DeerMemConfig(eviction_audit_max_entries=0)).record_capacity_eviction(_decision(["fact_1"]), max_facts=5, agent_name=AGENT, user_id="alice")
    assert server.calls_to("append_to_stream") == []


def test_watermark_round_trip(server, tmp_path):
    config = DeerMemConfig(storage_path=str(tmp_path), watermark_max_keys=2)
    storage = _storage(server, config)
    file_storage = FileMemoryStorage(config)
    steps = [("t1", ["m1", "a"]), ("t2", ["m2", "b"]), ("t1", ["m3", "c"]), ("t3", ["m4", "d"]), ("t4", None)]
    server.calls.clear()
    for thread_id, watermark in steps:
        for target in (storage, file_storage):
            target.set_extraction_watermark(thread_id, watermark, agent_name=AGENT, user_id="alice")
    assert len(server.calls_to("append_to_stream", ALICE_META)) == len(steps)
    assert server.calls_to("get_stream", ALICE_META) == []

    for reader in (storage, _storage(server, config)):
        for thread_id in ("t1", "t2", "t3", "t4"):
            assert reader.get_extraction_watermark(thread_id, agent_name=AGENT, user_id="alice") == file_storage.get_extraction_watermark(thread_id, agent_name=AGENT, user_id="alice")
    # The cap drops the least recently advanced thread (t2), as the file storage does.
    assert storage.get_extraction_watermark("t2", agent_name=AGENT, user_id="alice") is None
    assert storage.get_extraction_watermark("t1", agent_name=AGENT, user_id="alice") == ["m3", "c"]

    # None drops one thread only; other agents and users are separate.
    storage.set_extraction_watermark("t1", None, agent_name=AGENT, user_id="alice")
    assert storage.get_extraction_watermark("t1", agent_name=AGENT, user_id="alice") is None
    assert storage.get_extraction_watermark("t3", agent_name=AGENT, user_id="alice") == ["m4", "d"]
    assert storage.get_extraction_watermark("t3", agent_name=OTHER, user_id="alice") is None
    assert storage.get_extraction_watermark("t3", agent_name=AGENT, user_id="bob") is None
    assert storage.get_extraction_watermark("t3", agent_name=AGENT) is None

    # A warm reader folds only the new events.
    reader = _storage(server, config)
    assert reader.get_extraction_watermark("t3", agent_name=AGENT, user_id="alice") == ["m4", "d"]
    head = server.sync_client().get_current_version(ALICE_META)
    storage.set_extraction_watermark("t5", ["m5", "e"], agent_name=AGENT, user_id="alice")
    server.calls.clear()
    assert reader.get_extraction_watermark("t5", agent_name=AGENT, user_id="alice") == ["m5", "e"]
    reads = server.calls_to("get_stream", ALICE_META)
    assert len(reads) == 1 and reads[0].kwargs["stream_position"] == head + 1


# --- deletion parity --------------------------------------------------------------


def test_delete_one_fact_keeps_other_usage(server, tmp_path):
    config = DeerMemConfig(storage_path=str(tmp_path))
    storage = _storage(server, config)
    file_storage = FileMemoryStorage(config)
    for target in (storage, file_storage):
        _seed(target, ["fact_1", "fact_2"])
        _record_all(target)
        target.clear_fact_metadata(agent_name=AGENT, user_id="alice", fact_ids=["fact_1"])
    file_audit = json.loads(agent_eviction_audit_path(memory_file_path(config, AGENT, user_id="alice"), AGENT).read_text())

    for reader in (storage, _storage(server, config)):
        assert reader.get_fact_usage(agent_name=AGENT, user_id="alice") == file_storage.get_fact_usage(agent_name=AGENT, user_id="alice")
        assert set(reader.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_2"}
        assert reader.get_eviction_audit(agent_name=AGENT, user_id="alice") == file_audit
        assert [item["factId"] for item in file_audit[0]["evicted"]] == ["fact_9"]
        assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1", "hello"]
    # The deletion is a boundary: the newest meta event is a snapshot without fact_1.
    newest = server.sync_client().get_stream(ALICE_META, backwards=True, limit=1)[0]
    assert newest.type.endswith("MetadataSnapshot") and "fact_1" not in newest.data.decode()

    # Deleting a fact through the primary store drops its sidecar records too.
    _record_all(storage)
    document = storage.load(AGENT, user_id="alice")
    storage.apply_changes({"deletes": ["fact_2"], "deleteRevisions": {"fact_2": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])
    cold = _storage(server, config)
    assert set(cold.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_1"}
    assert cold.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1", "hello"]
    # Evidence about fact_2 appended after its deletion (stamped at the deletion's cutoff) is
    # still removed by DeerMem's follow-up metadata clear of the same id.
    storage.record_capacity_eviction(_decision(["fact_2"]), max_facts=5, agent_name=AGENT, user_id="alice", occurred_at=T0)
    assert "fact_2" in [item["factId"] for record in _storage(server, config).get_eviction_audit(agent_name=AGENT, user_id="alice") for item in record["evicted"]]
    storage.clear_fact_metadata(agent_name=AGENT, user_id="alice", fact_ids=["fact_2"])
    for reader in (storage, _storage(server, config)):
        assert "fact_2" not in [item["factId"] for record in reader.get_eviction_audit(agent_name=AGENT, user_id="alice") for item in record["evicted"]]
    # A selected-fact clear that no deletion covers is a deletion of its own (the fact stays).
    head = server.sync_client().get_current_version(ALICE_STREAM)
    storage.clear_fact_metadata(agent_name=AGENT, user_id="alice", fact_ids=["fact_1"])
    assert server.sync_client().get_current_version(ALICE_STREAM) == head + 1
    assert [fact["id"] for fact in storage.load(AGENT, user_id="alice")["facts"]] == ["fact_1"]
    assert _storage(server, config).get_fact_usage(agent_name=AGENT, user_id="alice") == {}
    # ...and by omission from a full save.
    assert storage.save({"facts": [_fact("fact_3", "new")]}, AGENT, user_id="alice") is True
    assert _storage(server, config).get_fact_usage(agent_name=AGENT, user_id="alice") == {}
    # Accesses to a deleted fact are not recorded.
    storage.record_fact_accesses(["fact_1", "fact_3"], agent_name=AGENT, user_id="alice", accessed_at=T0)
    assert set(storage.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_3"}


def test_clear_agent_keeps_other_agents_sidecars(server):
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    storage = _storage(server)
    for agent, user in ((AGENT, "alice"), (OTHER, "alice"), (AGENT, "bob")):
        _seed(storage, ["fact_1", "fact_2"], agent, user)
        _record_all(storage, agent, user)

    MemoryUpdater(DeerMemConfig(), storage, None).clear_memory_data(AGENT, user_id="alice")
    for reader in (storage, _storage(server)):
        assert reader.load(AGENT, user_id="alice")["facts"] == []
        assert reader.get_fact_usage(agent_name=AGENT, user_id="alice") == {}
        assert reader.get_eviction_audit(agent_name=AGENT, user_id="alice") == []
        assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") is None
        for agent, user in ((OTHER, "alice"), (AGENT, "bob")):
            assert set(reader.get_fact_usage(agent_name=agent, user_id=user)) == {"fact_1", "fact_2"}
            assert len(reader.get_eviction_audit(agent_name=agent, user_id=user)) == 1
            assert reader.get_extraction_watermark("thread-1", agent_name=agent, user_id=user) == ["msg-1", "hello"]

    # A direct whole-agent clear also works for an agent with no facts.
    storage.set_extraction_watermark("thread-2", ["m"], agent_name="empty-agent", user_id="alice")
    storage.clear_fact_metadata(agent_name="empty-agent", user_id="alice")
    assert _storage(server).get_extraction_watermark("thread-2", agent_name="empty-agent", user_id="alice") is None
    # Clearing no fact ids writes nothing; a whole-agent clear is always a deletion
    # (it cannot know whether another process's sidecar append is in flight).
    server.calls.clear()
    storage.clear_fact_metadata(agent_name=OTHER, user_id="alice", fact_ids=[])
    assert server.calls_to("append_to_stream") == []
    head = server.sync_client().get_current_version(ALICE_STREAM)
    storage.clear_fact_metadata(agent_name="empty-agent", user_id="alice")
    assert server.sync_client().get_current_version(ALICE_STREAM) == head + 1
    assert [fact["id"] for fact in _storage(server).load(OTHER, user_id="alice")["facts"]] == ["fact_1", "fact_2"]


def test_clear_all_drops_all_sidecars(server):
    storage = _storage(server)
    _seed(storage, ["fact_1", "fact_2"])
    _record_all(storage)
    # An agent with zero facts but sidecar records.
    storage.set_extraction_watermark("thread-z", ["m"], agent_name=OTHER, user_id="alice")
    _seed(storage, ["fact_1", "fact_2"], AGENT, "bob")
    _record_all(storage, AGENT, "bob")

    storage.clear_all(user_id="alice")
    for reader in (storage, _storage(server)):
        assert reader.get_fact_usage(agent_name=AGENT, user_id="alice") == {}
        assert reader.get_eviction_audit(agent_name=AGENT, user_id="alice") == []
        assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") is None
        assert reader.get_extraction_watermark("thread-z", agent_name=OTHER, user_id="alice") is None
        assert set(reader.get_fact_usage(agent_name=AGENT, user_id="bob")) == {"fact_1", "fact_2"}

    # An already-empty primary scope still drops its sidecars.
    storage.set_extraction_watermark("thread-y", ["m"], agent_name=OTHER, user_id="alice")
    head = server.sync_client().get_current_version(ALICE_STREAM)
    storage.clear_all(user_id="alice")
    # ...as a sidecar-only deletion: one primary boundary that keeps the (empty) state.
    assert server.sync_client().get_current_version(ALICE_STREAM) == head + 1
    assert storage.load(AGENT, user_id="alice")["facts"] == []
    assert _storage(server).get_extraction_watermark("thread-y", agent_name=OTHER, user_id="alice") is None
    # Records written after a clear survive.
    _seed(storage, ["fact_5"])
    storage.record_fact_accesses(["fact_5"], agent_name=AGENT, user_id="alice", accessed_at=T0)
    assert set(_storage(server).get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_5"}


# --- interruption, intents, failures ------------------------------------------------


def test_interrupted_cleanup_never_resurrects_after_restart(server):
    flag = {"down": False}
    storage = _storage(server, meta_down=flag)
    _seed(storage, ["fact_1", "fact_2"])
    _seed(storage, ["fact_1", "fact_2"], OTHER)
    _record_all(storage)
    _record_all(storage, OTHER)

    # The primary deletion commits; the sidecar cleanup fails (crash between steps 2 and 3).
    flag["down"] = True
    document = storage.load(AGENT, user_id="alice")
    delta = storage.apply_changes({"deletes": ["fact_1"], "deleteRevisions": {"fact_1": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])
    assert delta["deletedFactIds"] == ["fact_1"]
    cutoff = delta["revision"]
    flag["down"] = False
    # Without the intent the stale records would still be there (usage is also dropped for non-facts)...
    assert "fact_1" in [item["factId"] for item in _storage(server, intents=lambda stream: []).get_eviction_audit(agent_name=AGENT, user_id="alice")[0]["evicted"]]
    # ...while the default provider (the deletion engine's open intents) hides them.
    assert [item["factId"] for item in _storage(server).get_eviction_audit(agent_name=AGENT, user_id="alice")[0]["evicted"]] == ["fact_9"]

    open_intents: list[dict] = [{"op": "delete_facts", "agent": AGENT, "factIds": ["fact_1"], "cutoff": cutoff}]
    seen: list[str] = []

    def intents(stream: str):
        seen.append(stream)
        return list(open_intents) if stream == ALICE_STREAM else []

    restarted = _storage(server, intents=intents)
    assert set(restarted.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_2"}
    assert [item["factId"] for item in restarted.get_eviction_audit(agent_name=AGENT, user_id="alice")[0]["evicted"]] == ["fact_9"]
    assert restarted.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1", "hello"]
    assert set(restarted.get_fact_usage(agent_name=OTHER, user_id="alice")) == {"fact_1", "fact_2"}
    assert ALICE_STREAM in seen
    # A record written after the deletion (at or above its cutoff) survives the intent.
    _seed(restarted, ["fact_1"])
    restarted.record_fact_accesses(["fact_1"], agent_name=AGENT, user_id="alice", accessed_at=T0 + timedelta(days=9))
    usage = restarted.get_fact_usage(agent_name=AGENT, user_id="alice")
    assert usage["fact_1"]["accessCount"] == 1

    # An interrupted clear_all: every agent's records stay hidden while its intent is open.
    flag["down"] = True
    storage.clear_all(user_id="alice")
    flag["down"] = False
    open_intents[:] = [{"op": "clear_all", "agents": [AGENT, OTHER], "cutoff": storage.load(AGENT, user_id="alice")["revision"]}]
    restarted = _storage(server, intents=intents)
    for agent in (AGENT, OTHER):
        assert restarted.get_fact_usage(agent_name=agent, user_id="alice") == {}
        assert restarted.get_eviction_audit(agent_name=agent, user_id="alice") == []
        assert restarted.get_extraction_watermark("thread-1", agent_name=agent, user_id="alice") is None


def _delete_fact_1(storage) -> None:
    document = storage.load(AGENT, user_id="alice")
    storage.apply_changes({"deletes": ["fact_1"], "deleteRevisions": {"fact_1": 1}}, agent_name=AGENT, user_id="alice", expected_manifest_revision=document["revision"])


def _clear_agent(storage) -> None:
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    MemoryUpdater(DeerMemConfig(), storage, None).clear_memory_data(AGENT, user_id="alice")


def _write_watermark(storage) -> None:
    storage.set_extraction_watermark("thread-1", ["msg-1"], agent_name=AGENT, user_id="alice")


def _write_eviction(storage) -> None:
    storage.record_capacity_eviction(_decision(["fact_1"]), max_facts=5, agent_name=AGENT, user_id="alice", occurred_at=T0)


def _write_usage(storage) -> None:
    storage.record_fact_accesses(["fact_1"], agent_name=AGENT, user_id="alice", accessed_at=T0)


def _sees_watermark(storage) -> bool:
    return storage.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") is not None


def _sees_eviction(storage) -> bool:
    return storage.get_eviction_audit(agent_name=AGENT, user_id="alice") != []


def _sees_usage(storage) -> bool:
    return storage.get_fact_usage(agent_name=AGENT, user_id="alice") != {}


def _clear_all(storage) -> None:
    storage.clear_all(user_id="alice")


def _clear_fact_1_metadata(storage) -> None:
    storage.clear_fact_metadata(agent_name=AGENT, user_id="alice", fact_ids=["fact_1"])


def _clear_agent_metadata(storage) -> None:
    storage.clear_fact_metadata(agent_name=AGENT, user_id="alice")


@pytest.mark.parametrize(
    ("seeded", "deletion", "write", "visible"),
    [
        pytest.param(True, _clear_all, _write_watermark, _sees_watermark, id="watermark-clear_all"),
        pytest.param(True, _clear_all, _write_eviction, _sees_eviction, id="eviction-clear_all"),
        pytest.param(True, _delete_fact_1, _write_eviction, _sees_eviction, id="eviction-delete_facts"),
        pytest.param(True, _clear_all, _write_usage, _sees_usage, id="usage-clear_all"),
        pytest.param(True, _clear_agent, _write_watermark, _sees_watermark, id="watermark-clear_agent"),
        pytest.param(True, _clear_agent, _write_eviction, _sees_eviction, id="eviction-clear_agent"),
        pytest.param(True, _clear_fact_1_metadata, _write_eviction, _sees_eviction, id="eviction-clear_fact_metadata"),
        pytest.param(True, _clear_fact_1_metadata, _write_usage, _sees_usage, id="usage-clear_fact_metadata"),
        pytest.param(False, _clear_agent_metadata, _write_watermark, _sees_watermark, id="watermark-clear_agent-no-facts"),
        pytest.param(False, _clear_all, _write_watermark, _sees_watermark, id="watermark-empty-clear_all"),
        pytest.param(False, _clear_all, _write_eviction, _sees_eviction, id="eviction-empty-clear_all"),
    ],
)
def test_late_cross_process_sidecar_append_after_closed_deletion_stays_hidden(server, seeded, deletion, write, visible):
    """A writer reads the old primary revision, a deletion in another process completes and closes, then the writer appends."""
    writer, deleter = _storage(server), _storage(server)
    _seed(writer, ["fact_1", "fact_2"])
    if seeded:
        _seed(deleter, ["fact_3"], OTHER)
    else:
        # An already-empty scope (the primary stream exists and holds nothing) that still holds sidecars.
        writer.clear_all(user_id="alice")
        writer.set_extraction_watermark("thread-0", ["m"], agent_name=OTHER, user_id="alice")
    original = writer._meta_append
    written: list[int] = []

    def late_append(meta, event_type, data):
        deletion(deleter)
        assert deleter._engine().open_intents_for(ALICE_STREAM) == []
        assert deleter.recover_deletions(ALICE_STREAM) == []
        written.append(data["revision"])
        original(meta, event_type, data)

    writer._meta_append = late_append
    write(writer)
    assert any(event_type.endswith(("CapacityEvicted", "ExtractionWatermarkSet", "FactsAccessed")) for event_type in _types(server, ALICE_META)[-1:])
    for reader in (_storage(server), deleter):
        assert not visible(reader)
    assert written[0] < deleter.load(AGENT, user_id="alice")["revision"]
    # A record written after the deletion (at or above its cutoff) is still served.
    _seed(deleter, ["fact_1"])
    write(deleter)
    assert visible(_storage(server))


def test_sidecar_failures_never_fail_memory_calls(server):
    flag = {"down": True}
    storage = _storage(server, meta_down=flag)
    _seed(storage, ["fact_1", "fact_2"])
    storage.record_fact_accesses(["fact_1"], agent_name=AGENT, user_id="alice")
    storage.record_capacity_eviction(_decision(["fact_1"]), max_facts=5, agent_name=AGENT, user_id="alice")
    storage.set_extraction_watermark("t1", ["m"], agent_name=AGENT, user_id="alice")
    assert storage.get_fact_usage(agent_name=AGENT, user_id="alice") == {}
    assert storage.get_eviction_audit(agent_name=AGENT, user_id="alice") == []
    assert storage.get_extraction_watermark("t1", agent_name=AGENT, user_id="alice") is None
    storage.clear_fact_metadata(agent_name=AGENT, user_id="alice")
    assert storage.save({"facts": [_fact("fact_2", "content of fact_2")]}, AGENT, user_id="alice") is True
    assert storage.clear_all(user_id="alice")["facts"] == []

    # A failing intents provider hides everything rather than serve stale records.
    flag["down"] = False
    _seed(storage, ["fact_1"])
    storage.record_fact_accesses(["fact_1"], agent_name=AGENT, user_id="alice")

    def broken(stream):
        raise RuntimeError("deletion index unreadable")

    assert _storage(server, intents=broken).get_fact_usage(agent_name=AGENT, user_id="alice") == {}
    assert set(storage.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_1"}

    # Undecodable or unknown meta events are skipped, not corruption.
    server.sync_client().append_to_stream(
        ALICE_META,
        events=[NewEvent(id=uuid.uuid4(), type="deerflow.memory.Bogus", data=b"{}"), NewEvent(id=uuid.uuid4(), type="deerflow.memory.FactsAccessed", data=b"not json")],
        current_version=server.sync_client().get_current_version(ALICE_META),
    )
    assert set(_storage(server).get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_1"}


def test_long_sidecar_history_is_compacted(server, monkeypatch):
    from deerflow_extension_kurrentdb.memory import storage as storage_module

    monkeypatch.setattr(storage_module, "SIDECAR_SNAPSHOT_EVERY", 5)
    storage = _storage(server)
    _seed(storage, ["fact_1"])
    for day in range(12):
        storage.record_fact_accesses(["fact_1"], agent_name=AGENT, user_id="alice", accessed_at=T0 + timedelta(days=day))
        storage.get_fact_usage(agent_name=AGENT, user_id="alice")
    assert any(event_type.endswith("MetadataSnapshot") for event_type in _types(server, ALICE_META))

    expected = storage.get_fact_usage(agent_name=AGENT, user_id="alice")
    assert expected["fact_1"]["accessCount"] == 12
    server.calls.clear()
    cold = _storage(server)
    assert cold.get_fact_usage(agent_name=AGENT, user_id="alice") == expected
    # A cold read starts from the newest snapshot, not from position 0.
    reads = server.calls_to("get_stream", ALICE_META)
    assert len(reads) == 1 and reads[0].kwargs["backwards"] is True
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)
