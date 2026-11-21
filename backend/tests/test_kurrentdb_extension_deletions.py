"""KurrentDB crash-safe deletions: intents in the deletions index and the primary side (boundary, sidecars, ``$tb``)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import DeadlineExceededError, ServiceUnavailableError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EvictedFact, FactEvictionDecision
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryManifestRevisionConflict

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
AGENT = "__default__"
ALICE_STREAM = "deerflow.memory-user.alice"
ALICE_META = "deerflow.memory-meta-user.alice"
INDEX = "deerflow.kurrent-deletions"
T0 = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


class Crash(BaseException):
    """The deleting process dies here (not an ``Exception``, so nothing swallows it)."""


class _Hooked:
    """A client whose calls run ``hook(method, stream, kwargs, phase)`` before and after the real call."""

    def __init__(self, client, hook):
        self._client = client
        self._hook = hook

    def __getattr__(self, name):
        method = getattr(self._client, name)
        if not callable(method):
            return method

        def call(stream_name, *args, **kwargs):
            self._hook(name, stream_name, kwargs, "before")
            result = method(stream_name, *args, **kwargs)
            self._hook(name, stream_name, kwargs, "after")
            return result

        return call


class _MetaDown:
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


def _storage(server: FakeKurrentDB, client=None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    client = client if client is not None else server.sync_client()
    return KurrentdbMemoryStorage(DeerMemConfig(), client_factory=lambda: client)


def _fact(fact_id: str) -> dict:
    return {"id": fact_id, "content": f"content of {fact_id}", "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual"}


def _decision(evicted: list[str]) -> FactEvictionDecision:
    return FactEvictionDecision(kept=[], evicted=[EvictedFact(fact_id=fact_id, category="preference", score=0.1, components={"confidence": 0.1}) for fact_id in evicted], scores={}, policy="confidence")


def _seed(storage) -> None:
    """fact_1 and fact_2 with usage, eviction evidence naming both, and a watermark."""
    assert storage.save({"facts": [_fact("fact_1"), _fact("fact_2")]}, AGENT, user_id="alice") is True
    storage.record_fact_accesses(["fact_1", "fact_2"], agent_name=AGENT, user_id="alice", accessed_at=T0)
    storage.record_capacity_eviction(_decision(["fact_1", "fact_2"]), max_facts=5, agent_name=AGENT, user_id="alice", occurred_at=T0)
    storage.set_extraction_watermark("thread-1", ["msg-1"], agent_name=AGENT, user_id="alice")


def _delete(storage, fact_id: str, *, expected: bool = True) -> dict:
    document = storage.load(AGENT, user_id="alice")
    revision = next(fact["revision"] for fact in document["facts"] if fact["id"] == fact_id)
    return storage.apply_changes(
        {"deletes": [fact_id], "deleteRevisions": {fact_id: revision}},
        agent_name=AGENT,
        user_id="alice",
        expected_manifest_revision=document["revision"] if expected else None,
    )


def _index(server: FakeKurrentDB) -> list[tuple[str, dict]]:
    try:
        recorded = server.sync_client().get_stream(INDEX, timeout=TIMEOUT)
    except Exception:
        return []
    # Primary-side protocol only: canonical cleanup also runs with canonical events off (R17), on its own schedule.
    return [(event.type.rsplit(".", 1)[-1], json.loads(event.data)) for event in recorded if not event.type.rsplit(".", 1)[-1].startswith("Canonical")]


def _tb(server: FakeKurrentDB, stream: str) -> int:
    return server.sync_client().get_stream_metadata(stream, timeout=TIMEOUT)[0].get("$tb", 0)


def _all_events(server: FakeKurrentDB, stream: str):
    """Every recorded event, including those below ``$tb`` (the fake's raw history)."""
    return list(server._streams[stream].events)


def _fact_ids(storage) -> list[str]:
    return [fact["id"] for fact in storage.load(AGENT, user_id="alice")["facts"]]


def _evicted_ids(storage) -> list[str]:
    return [item["factId"] for record in storage.get_eviction_audit(agent_name=AGENT, user_id="alice") for item in record["evicted"]]


def _sidecars_show(storage, fact_id: str) -> bool:
    return fact_id in storage.get_fact_usage(agent_name=AGENT, user_id="alice") or fact_id in _evicted_ids(storage)


# --- happy path ------------------------------------------------------------------------


def test_happy_path_writes_intent_boundary_tb_done(server):
    storage = _storage(server)
    _seed(storage)
    expected = server.sync_client().get_current_version(ALICE_STREAM)

    server.calls.clear()
    delta = _delete(storage, "fact_1")
    calls = list(server.calls)
    assert delta["deletedFactIds"] == ["fact_1"]

    index = _index(server)
    assert [kind for kind, _ in index] == ["DeletionIntended", "DeletionDone"]
    intended = index[0][1]
    intent_id = intended["intent_id"]
    assert uuid.UUID(intent_id)
    assert intended["op"] == "delete_facts"
    assert intended["criteria"] == {"op": "delete_facts", "agent": AGENT, "factIds": ["fact_1"], "cutoff": expected + 2}
    assert intended["primary_stream"] == ALICE_STREAM and intended["expected_position"] == expected
    assert isinstance(intended["created_at"], str)
    assert index[1][1]["intent_id"] == intent_id

    # Step 2: the boundary is the event at expected + 1, carrying the intent id; $tb points at it.
    boundary = server.sync_client().get_stream(ALICE_STREAM, stream_position=expected + 1, limit=1)[0]
    assert boundary.stream_position == expected + 1 and boundary.type.endswith("MemorySnapshot")
    assert json.loads(boundary.data)["intent_id"] == intent_id
    assert _tb(server, ALICE_STREAM) == expected + 1
    assert server.sync_client().get_stream(ALICE_STREAM)[0].stream_position == expected + 1

    # Step 3: the sidecar boundary carries the intent id, and the meta $tb points at it.
    meta = server.sync_client().get_stream(ALICE_META)
    assert meta[0].type.endswith("MetadataSnapshot") and json.loads(meta[0].data)["intent_id"] == intent_id
    assert _tb(server, ALICE_META) == meta[0].stream_position
    assert "fact_1" not in meta[0].data.decode()

    # Order: intent, boundary, sidecar boundary, sidecar $tb, primary $tb (after the sidecar cleanup), done.
    writes = [(call.method, call.stream_name) for call in calls if call.method in ("append_to_stream", "set_stream_metadata")]
    assert writes == [
        ("append_to_stream", INDEX),
        ("append_to_stream", ALICE_STREAM),
        ("append_to_stream", ALICE_META),
        ("set_stream_metadata", ALICE_META),
        ("set_stream_metadata", ALICE_STREAM),
        ("append_to_stream", INDEX),
    ]
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in calls)

    for reader in (storage, _storage(server)):
        assert _fact_ids(reader) == ["fact_2"]
        assert not _sidecars_show(reader, "fact_1")
        assert set(reader.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_2"}
        assert _evicted_ids(reader) == ["fact_2"]
        assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1"]

    # clear_all goes through the same protocol.
    server.calls.clear()
    storage.clear_all(user_id="alice")
    index = _index(server)
    assert [kind for kind, _ in index][-2:] == ["DeletionIntended", "DeletionDone"]
    assert index[-2][1]["op"] == "clear_all"
    head = server.sync_client().get_current_version(ALICE_STREAM)
    assert _tb(server, ALICE_STREAM) == head
    cold = _storage(server)
    assert _fact_ids(cold) == [] and cold.get_fact_usage(agent_name=AGENT, user_id="alice") == {}
    assert cold.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") is None


# --- crashes and recovery --------------------------------------------------------------


CRASH_POINTS = {
    1: ("append_to_stream", INDEX),
    2: ("append_to_stream", ALICE_STREAM),
    3: ("append_to_stream", ALICE_META),
    5: ("set_stream_metadata", ALICE_STREAM),
}


@pytest.mark.parametrize("step", sorted(CRASH_POINTS))
def test_crash_after_each_step_then_cold_recovery(server, step):
    armed = {"on": False}

    def hook(method, stream, kwargs, phase):
        if armed["on"] and phase == "after" and (method, stream) == CRASH_POINTS[step]:
            armed["on"] = False
            raise Crash(f"crashed after step {step}")

    storage = _storage(server, _Hooked(server.sync_client(), hook))
    _seed(storage)
    expected = server.sync_client().get_current_version(ALICE_STREAM)
    armed["on"] = True
    with pytest.raises(Crash):
        _delete(storage, "fact_1")
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended"]

    # Cold restart, no further calls: reads already hide everything a committed boundary removed.
    cold = _storage(server)
    if step == 1:
        assert _fact_ids(cold) == ["fact_1", "fact_2"] and _sidecars_show(cold, "fact_1")
    else:
        assert _fact_ids(cold) == ["fact_2"] and not _sidecars_show(cold, "fact_1")

    # Startup recovery finishes (or abandons) the primary side.
    metadata_writes = len(server.calls_to("set_stream_metadata"))
    meta_appends = len(server.calls_to("append_to_stream", ALICE_META))
    _storage(server).recover_deletions()
    kinds = [kind for kind, _ in _index(server)]
    if step == 1:
        assert kinds == ["DeletionIntended", "DeletionAbandoned"]
        # Abandoned only through the fence at the intended position.
        fence = server.sync_client().get_stream(ALICE_STREAM, stream_position=expected + 1, limit=1)[0]
        assert fence.type == "deerflow.Fence"
        assert _fact_ids(_storage(server)) == ["fact_1", "fact_2"] and _sidecars_show(_storage(server), "fact_1")
        assert _tb(server, ALICE_STREAM) == 0
    else:
        assert kinds == ["DeletionIntended", "DeletionDone"]
        assert _tb(server, ALICE_STREAM) == expected + 1
        meta_snapshots = [event for event in _all_events(server, ALICE_META) if event.type.endswith("MetadataSnapshot")]
        assert len(meta_snapshots) == 1, "the sidecar step is idempotent"
        assert _tb(server, ALICE_META) == meta_snapshots[0].stream_position
        if step >= 3:
            assert len(server.calls_to("append_to_stream", ALICE_META)) == meta_appends
        if step == 5:
            # The primary $tb was already raised: recovery only (re)checks the sidecar one, writing nothing.
            assert len(server.calls_to("set_stream_metadata")) == metadata_writes
        reader = _storage(server)
        assert _fact_ids(reader) == ["fact_2"] and not _sidecars_show(reader, "fact_1")
        assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1"]

    # Recovery is idempotent.
    server.calls.clear()
    _storage(server).recover_deletions()
    assert server.calls_to("append_to_stream") == [] and server.calls_to("set_stream_metadata") == []


def test_recovery_races_inflight_deleter(server):
    from deerflow_extension_kurrentdb.deletions import DeletionConflict, DeletionEngine, Intent

    stream = "deerflow.test-primary"
    client = server.sync_client()
    client.append_to_stream(stream, events=[NewEvent(id=uuid.uuid4(), type="seed", data=b"{}")], current_version=StreamState.NO_STREAM)
    deleter = DeletionEngine(client, timeout=TIMEOUT, derive=lambda intent: [])
    recoverer = DeletionEngine(server.sync_client(), timeout=TIMEOUT, derive=lambda intent: [])
    intent = Intent.new("delete_thread", {"op": "delete_thread"}, stream, 0)

    def build_boundary():
        # Another process's startup recovery runs between the deleter's steps 1 and 2.
        recoverer.recover_primary()
        return [NewEvent(id=uuid.uuid4(), type="boundary", data=json.dumps({"intent_id": intent.intent_id}).encode())]

    with pytest.raises(DeletionConflict):
        deleter.run(intent, build_boundary, [])
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionAbandoned"]
    assert [event.type for event in client.get_stream(stream)] == ["seed", "deerflow.Fence"]
    assert deleter.open_intents_for(stream) == [] and recoverer.open_intents_for(stream) == []

    # Through the memory storage, the racing recovery abandons the first intent and the change set is retried.
    armed = {"on": True}
    other = _storage(server)

    def hook(method, stream_name, kwargs, phase):
        if armed["on"] and phase == "before" and (method, stream_name) == ("append_to_stream", ALICE_STREAM) and kwargs["events"][0].type.endswith("MemorySnapshot"):
            armed["on"] = False
            other.recover_deletions()

    storage = _storage(server, _Hooked(server.sync_client(), hook))
    _seed(storage)
    _delete(storage, "fact_1", expected=False)
    kinds = [kind for kind, _ in _index(server)][2:]
    assert kinds == ["DeletionIntended", "DeletionAbandoned", "DeletionIntended", "DeletionDone"]
    assert _fact_ids(_storage(server)) == ["fact_2"]


def test_deleter_crash_right_after_boundary(server):
    armed = {"on": False}

    def hook(method, stream, kwargs, phase):
        if armed["on"] and phase == "after" and (method, stream) == ("append_to_stream", ALICE_STREAM):
            armed["on"] = False
            raise Crash("lost with the boundary in flight")

    storage = _storage(server, _Hooked(server.sync_client(), hook))
    _seed(storage)
    expected = server.sync_client().get_current_version(ALICE_STREAM)
    armed["on"] = True
    with pytest.raises(Crash):
        _delete(storage, "fact_1")

    # Another process sees the open, primary-committed intent and hides its records.
    other = _storage(server)
    assert not _sidecars_show(other, "fact_1") and _sidecars_show(other, "fact_2")
    assert _tb(server, ALICE_STREAM) == 0

    # Its next primary write first completes the open primary side.
    assert other.save({"facts": [_fact("fact_2"), _fact("fact_3")]}, AGENT, user_id="alice") is True
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionDone"]
    assert _tb(server, ALICE_STREAM) == expected + 1
    assert _fact_ids(_storage(server)) == ["fact_2", "fact_3"]
    assert not _sidecars_show(_storage(server), "fact_1")


@pytest.mark.parametrize("order", ["fence_first", "commit_first"])
def test_delayed_primary_commit_races_recovery_fence(server, order):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryReadError

    storage = _storage(server)
    _seed(storage)
    # The boundary's commit is delayed past the deleter's timeout, and the deleter's own fence fails.
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("slow"), stream_name=ALICE_STREAM)
    server.fail_next("append_to_stream", ServiceUnavailableError("fence lost"), stream_name=ALICE_STREAM)
    with pytest.raises(KurrentdbMemoryReadError):
        _delete(storage, "fact_1")
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended"]

    if order == "fence_first":
        _storage(server).recover_deletions()
        pending.release()
        assert pending.committed is False
        assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionAbandoned"]
        reader = _storage(server)
        assert _fact_ids(reader) == ["fact_1", "fact_2"] and _sidecars_show(reader, "fact_1")
    else:
        pending.release()
        assert pending.committed is True
        _storage(server).recover_deletions()
        assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionDone"]
        reader = _storage(server)
        assert _fact_ids(reader) == ["fact_2"] and not _sidecars_show(reader, "fact_1")


def test_concurrent_deletions_never_lower_tb(server):
    from deerflow_extension_kurrentdb.deletions import DeletionEngine

    stream = "deerflow.test-primary"
    client = server.sync_client()
    client.append_to_stream(stream, events=[NewEvent(id=uuid.uuid4(), type="e", data=b"{}") for _ in range(12)], current_version=StreamState.NO_STREAM)
    client.set_stream_metadata(stream, metadata={"keep": "me"}, current_version=StreamState.NO_STREAM)
    high = DeletionEngine(server.sync_client(), timeout=TIMEOUT)
    raced = {"done": False}

    def hook(method, stream_name, kwargs, phase):
        # Between the low raiser's metadata read and its write, the high raiser lands.
        if method == "set_stream_metadata" and phase == "before" and not raced["done"]:
            raced["done"] = True
            high.raise_truncate_before(stream, 10)

    low = DeletionEngine(_Hooked(server.sync_client(), hook), timeout=TIMEOUT)
    low.raise_truncate_before(stream, 5)
    metadata, _ = client.get_stream_metadata(stream)
    assert metadata == {"keep": "me", "$tb": 10}

    server.calls.clear()
    low.raise_truncate_before(stream, 7)
    high.raise_truncate_before(stream, 10)
    assert server.calls_to("set_stream_metadata") == []
    assert _tb(server, stream) == 10
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)

    # Two successive memory deletions only ever raise $tb.
    storage = _storage(server)
    _seed(storage)
    _delete(storage, "fact_1")
    first = _tb(server, ALICE_STREAM)
    _delete(storage, "fact_2")
    assert _tb(server, ALICE_STREAM) > first


def test_second_deletion_completes_open_intent_first(server):
    flag = {"down": False}
    storage = _storage(server, _MetaDown(server.sync_client(), flag))
    _seed(storage)

    # The first deletion commits its boundary; its sidecar cleanup fails, so the intent stays open.
    flag["down"] = True
    _delete(storage, "fact_1")
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended"]
    # The primary $tb waits for the sidecar cleanup, so the removal evidence stays readable.
    assert _tb(server, ALICE_STREAM) == 0
    flag["down"] = False
    assert not _sidecars_show(storage, "fact_1") and _sidecars_show(storage, "fact_2")

    # Once it can, the second deletion completes the first before writing its own intent.
    _delete(storage, "fact_2")
    index = _index(server)
    assert [kind for kind, _ in index] == ["DeletionIntended", "DeletionDone", "DeletionIntended", "DeletionDone"]
    assert index[1][1]["intent_id"] == index[0][1]["intent_id"]
    reader = _storage(server)
    assert _fact_ids(reader) == []
    assert reader.get_fact_usage(agent_name=AGENT, user_id="alice") == {} and _evicted_ids(reader) == []
    assert reader.get_extraction_watermark("thread-1", agent_name=AGENT, user_id="alice") == ["msg-1"]
    assert _tb(server, ALICE_STREAM) == index[2][1]["expected_position"] + 1


def test_deletion_during_sidecar_outage_defers_tb_in_order(server):
    """A committed but unfinished earlier deletion never fails a later one; $tb and Done follow index order."""
    flag = {"down": False}
    storage = _storage(server, _MetaDown(server.sync_client(), flag))
    _seed(storage)
    assert storage.save({"facts": [_fact("fact_1"), _fact("fact_2"), _fact("fact_3")]}, AGENT, user_id="alice") is True

    flag["down"] = True
    _delete(storage, "fact_1")
    _delete(storage, "fact_2")
    index = _index(server)
    assert [kind for kind, _ in index] == ["DeletionIntended", "DeletionIntended"]
    assert server.calls_to("set_stream_metadata") == []
    flag["down"] = False
    for reader in (storage, _storage(server)):
        assert _fact_ids(reader) == ["fact_3"]
        assert not _sidecars_show(reader, "fact_1") and not _sidecars_show(reader, "fact_2")

    # Recovery completes both, the earlier one first, and raises $tb to the later boundary.
    _storage(server).recover_deletions()
    first, second = index[0][1]["intent_id"], index[1][1]["intent_id"]
    assert [(kind, data["intent_id"]) for kind, data in _index(server)][2:] == [("DeletionDone", first), ("DeletionDone", second)]
    raised = [call.kwargs["metadata"]["$tb"] for call in server.calls_to("set_stream_metadata", ALICE_STREAM)]
    assert raised == sorted(raised) and raised[-1] == index[1][1]["expected_position"] + 1


def test_failed_boundary_append_abandons_via_fence(server):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryReadError

    storage = _storage(server)
    _seed(storage)
    expected = server.sync_client().get_current_version(ALICE_STREAM)

    # The boundary append fails before the server applies it: the deleter fences, then abandons.
    server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=ALICE_STREAM)
    with pytest.raises(MemoryManifestRevisionConflict):
        _delete(storage, "fact_1")
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionAbandoned"]
    fence = server.sync_client().get_stream(ALICE_STREAM, stream_position=expected + 1, limit=1)[0]
    assert fence.type == "deerflow.Fence"
    assert _fact_ids(_storage(server)) == ["fact_1", "fact_2"] and _sidecars_show(_storage(server), "fact_1")

    # Absence alone never abandons: with the boundary and every fence failing, the intent stays open.
    server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=ALICE_STREAM)
    server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=ALICE_STREAM)
    with pytest.raises(KurrentdbMemoryReadError):
        _delete(storage, "fact_1")
    server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=ALICE_STREAM)
    _storage(server).recover_deletions()
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionAbandoned", "DeletionIntended"]
    # While its boundary is unsettled, a new deletion of the stream is blocked before writing an intent.
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryReadError as ReadError

    for _ in range(2):  # the pre-write recovery and the deletion's own recovery both try the fence
        server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=ALICE_STREAM)
    with pytest.raises(ReadError, match="unsettled"):
        _delete(storage, "fact_2")
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionAbandoned", "DeletionIntended"]
    # Once the fence can land, recovery abandons it.
    _storage(server).recover_deletions()
    assert [kind for kind, _ in _index(server)][-1] == "DeletionAbandoned"
    assert _fact_ids(_storage(server)) == ["fact_1", "fact_2"]
    # Afterwards the deletion succeeds.
    _delete(storage, "fact_1")
    assert _fact_ids(_storage(server)) == ["fact_2"]


# --- engine details -------------------------------------------------------------------


def test_open_intents_are_primary_committed_only_and_cached(server):
    from deerflow_extension_kurrentdb.deletions import DeletionEngine, Intent

    stream = "deerflow.test-primary"
    client = server.sync_client()
    client.append_to_stream(stream, events=[NewEvent(id=uuid.uuid4(), type="seed", data=b"{}")], current_version=StreamState.NO_STREAM)
    engine = DeletionEngine(client, timeout=TIMEOUT, derive=lambda intent: [])
    assert engine.open_intents_for(stream) == []
    intent = Intent.new("delete_run", {"op": "delete_run", "runId": "r1"}, stream, 0)
    seen: list[list] = []

    def build_boundary():
        # Between intent and boundary, the intent is not primary-committed yet.
        seen.append(engine.open_intents_for(stream))
        return [NewEvent(id=uuid.uuid4(), type="boundary", data=json.dumps({"intent_id": intent.intent_id}).encode())]

    def crash(intent):
        raise Crash("after boundary")

    from deerflow_extension_kurrentdb.deletions import DerivedStep

    with pytest.raises(Crash):
        engine.run(intent, build_boundary, [DerivedStep("deerflow.test-side", crash)])
    assert seen == [[]]
    assert engine.open_intents_for(stream) == [intent]
    assert engine.open_intents_for("deerflow.other") == []
    # Cached: an unchanged index costs one head read; committed boundaries are not re-read.
    server.calls.clear()
    assert engine.open_intents_for(stream) == [intent]
    assert [(call.method, call.stream_name) for call in server.calls] == [("get_current_version", INDEX)]

    # A boundary without the intent id is refused before anything reaches the primary stream.
    bad = Intent.new("delete_run", {"op": "delete_run", "runId": "r2"}, stream, 1)
    engine.recover_primary(stream)
    with pytest.raises(ValueError):
        engine.run(bad, lambda: [NewEvent(id=uuid.uuid4(), type="boundary", data=b"{}")], [])
    # ...and the intent is recorded as abandoned at once (the boundary was never appended).
    assert _index(server)[-1] == ("DeletionAbandoned", {"intent_id": bad.intent_id})
    assert engine.recover_primary(stream) == []
    with pytest.raises(ValueError):
        Intent.new("drop_everything", {}, stream, 0)


def test_later_deletion_waits_for_earlier_open_intent(server):
    """When only the earlier intent's derived step fails, the later one still never raises $tb or closes first."""
    from deerflow_extension_kurrentdb.deletions import DeletionEngine, DerivedStep, Intent

    stream = "deerflow.test-primary"
    client = server.sync_client()
    client.append_to_stream(stream, events=[NewEvent(id=uuid.uuid4(), type="seed", data=b"{}")], current_version=StreamState.NO_STREAM, timeout=TIMEOUT)
    failing: set[str] = set()

    def side_step(intent):
        if intent.intent_id in failing:
            raise ServiceUnavailableError("side store down for this intent")
        return None

    engine = DeletionEngine(client, timeout=TIMEOUT, derive=lambda intent: [DerivedStep("deerflow.test-side", side_step)])

    def boundary_for(intent):
        return lambda: [NewEvent(id=uuid.uuid4(), type="boundary", data=json.dumps({"intent_id": intent.intent_id}).encode())]

    first = Intent.new("delete_run", {"op": "delete_run", "runId": "r1"}, stream, 0)
    failing.add(first.intent_id)
    engine.run(first, boundary_for(first), engine._derive(first))
    second = Intent.new("delete_run", {"op": "delete_run", "runId": "r2"}, stream, 1)
    engine.run(second, boundary_for(second), engine._derive(second))
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionIntended"]
    assert _tb(server, stream) == 0
    assert engine.open_intents_for(stream) == [first, second]

    failing.clear()
    assert DeletionEngine(server.sync_client(), timeout=TIMEOUT, derive=lambda intent: [DerivedStep("deerflow.test-side", side_step)]).recover_primary() == []
    assert [(kind, data["intent_id"]) for kind, data in _index(server)][2:] == [("DeletionDone", first.intent_id), ("DeletionDone", second.intent_id)]
    assert _tb(server, stream) == 2


def test_index_reads_are_safe_across_threads(server):
    """One engine serves every scope from DeerMem's timer threads: a refresh never mutates the index mid-iteration."""
    import threading

    from deerflow_extension_kurrentdb.deletions import DeletionEngine, Intent, intended_event

    client = server.sync_client()
    engine = DeletionEngine(client, timeout=TIMEOUT, derive=lambda intent: [])
    for position in range(3):
        client.append_to_stream(INDEX, events=[intended_event(Intent.new("delete_run", {"op": "delete_run"}, "deerflow.test-primary", position))], current_version=StreamState.ANY, timeout=TIMEOUT)
    assert len(engine.open_intents_for("deerflow.nothing")) == 0
    errors: list[BaseException] = []

    class _Racing(dict):
        def items(self):
            for index, item in enumerate(dict.items(self)):
                if index == 0 and not racing:
                    # Mid-iteration, another thread refreshes the index after a new intent landed.
                    client.append_to_stream(INDEX, events=[intended_event(Intent.new("delete_run", {"op": "delete_run"}, "deerflow.test-primary", 9))], current_version=StreamState.ANY, timeout=TIMEOUT)
                    other = threading.Thread(target=lambda: errors.append(None) if engine.open_intents_for("deerflow.nothing") == [] else None)
                    racing.append(other)
                    other.start()
                    other.join(timeout=0.3)
                yield item

    racing: list[threading.Thread] = []
    engine._index.intents = _Racing(engine._index.intents)
    assert len(engine._open("deerflow.test-primary")) == 3
    for thread in racing:
        thread.join()
    assert errors == [None]
    assert len(engine._open("deerflow.test-primary")) == 4


def test_orphan_usage_after_done_is_hidden(server):
    """A cross-process usage append landing after the deletion's sidecar boundary never shows a deleted fact."""
    storage = _storage(server)
    _seed(storage)
    _delete(storage, "fact_1")
    assert [kind for kind, _ in _index(server)][-1] == "DeletionDone"
    # Another process checked fact_1 before the delete and appends its access late.
    from deerflow_extension_kurrentdb.memory import sidecars

    late = sidecars.new_event(sidecars.FACTS_ACCESSED, {"agent": AGENT, "revision": 1, "factIds": ["fact_1", "fact_2"], "at": "2026-11-02T00:00:00Z"})
    server.sync_client().append_to_stream(ALICE_META, events=[late], current_version=StreamState.ANY)
    for reader in (storage, _storage(server)):
        assert set(reader.get_fact_usage(agent_name=AGENT, user_id="alice")) == {"fact_2"}


def test_async_engine_runs_and_recovers(server):
    from deerflow_extension_kurrentdb.deletions import AsyncDeletionEngine, DerivedStep, Intent

    stream = "deerflow.test-primary"
    side = "deerflow.test-side"

    async def scenario():
        client = server.async_client()
        await client.append_to_stream(stream, events=[NewEvent(id=uuid.uuid4(), type="seed", data=b"{}")], current_version=StreamState.NO_STREAM, timeout=TIMEOUT)
        cleaned: list[str] = []

        async def side_cleanup(intent):
            cleaned.append(intent.intent_id)
            await client.append_to_stream(side, events=[NewEvent(id=uuid.uuid5(uuid.UUID(intent.intent_id), "side"), type="side", data=b"{}")], current_version=StreamState.ANY, timeout=TIMEOUT)
            return 0

        engine = AsyncDeletionEngine(client, timeout=TIMEOUT, derive=lambda intent: [DerivedStep(side, side_cleanup)])
        intent = Intent.new("delete_thread", {"op": "delete_thread"}, stream, 0)
        boundary = [NewEvent(id=uuid.uuid4(), type="boundary", data=json.dumps({"intent_id": intent.intent_id}).encode())]
        await engine.run(intent, lambda: boundary, [DerivedStep(side, side_cleanup)])
        assert await engine.open_intents_for(stream) == []

        # A crash after step 1 is abandoned by recovery through the fence.
        second = Intent.new("delete_thread", {"op": "delete_thread"}, stream, 1)

        def crash():
            raise Crash("after intent")

        with pytest.raises(Crash):
            await engine.run(second, crash, [])
        await AsyncDeletionEngine(server.async_client(), timeout=TIMEOUT, derive=lambda intent: []).recover_primary()
        return cleaned, intent

    cleaned, intent = asyncio.run(scenario())
    assert cleaned == [intent.intent_id]
    assert [kind for kind, _ in _index(server)] == ["DeletionIntended", "DeletionDone", "DeletionIntended", "DeletionAbandoned"]
    assert _tb(server, stream) == 1 and _tb(server, side) == 0
    assert [event.type for event in _all_events(server, stream)] == ["seed", "boundary", "deerflow.Fence"]
    assert all(call.kwargs.get("timeout") == TIMEOUT for call in server.calls)
