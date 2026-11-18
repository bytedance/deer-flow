"""Canonical kurrent-agents events: memory ``FactRetained`` and live ``AgentSession`` events, emitted best-effort."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path

import pytest
from kurrent_agent_schema import EVENT_TYPE_BY_NAME, EVENT_TYPE_NAMES, SCHEMA_VERSION, FactRetained, agent_memory_stream, agent_session_stream, from_json, to_json
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import ServiceUnavailableError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

pytestmark = [pytest.mark.bundled_extension, pytest.mark.anyio]

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
AGENT = "__default__"
ALICE_PRIMARY = "deerflow.memory-user.alice"
ALICE_CANONICAL = agent_memory_stream("deerflow", "alice")
T1_CANONICAL = agent_session_stream("t1")
INDEX = "deerflow.kurrent-deletions"
WORKER_THREAD = "kurrentdb-canonical"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))
    monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", "on")


@pytest.fixture(autouse=True)
def _no_leaked_workers():
    yield
    assert not [thread for thread in threading.enumerate() if thread.name == WORKER_THREAD], "a canonical worker thread outlived its test"


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


class Hooked:
    """A client that runs ``hook`` once around a call to ``method`` on ``stream`` (before, or after it returns)."""

    def __init__(self, inner, method: str, stream: str, hook, *, after: bool = False):
        self._inner, self._method, self._stream, self._hook, self._after = inner, method, stream, hook, after

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        def call(stream_name, *args, **kwargs):
            if stream_name != self._stream or self._hook is None:
                return target(stream_name, *args, **kwargs)
            hook, self._hook = self._hook, None
            if not self._after:
                hook()
                return target(stream_name, *args, **kwargs)
            result = target(stream_name, *args, **kwargs)
            hook()
            return result

        return call


class AsyncHooked(Hooked):
    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        async def call(stream_name, *args, **kwargs):
            if stream_name != self._stream or self._hook is None:
                return await target(stream_name, *args, **kwargs)
            hook, self._hook = self._hook, None
            await hook()
            return await target(stream_name, *args, **kwargs)

        return call


class CapturedJobs:
    """Stands in for the memory storage's background queue: jobs run only when the test says so."""

    def __init__(self):
        self.jobs = []

    def submit(self, job) -> bool:
        self.jobs.append(job)
        return True

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()


class CapturedChains:
    """Stands in for the run-event store's per-thread emission chains."""

    def __init__(self):
        self.jobs = []

    def submit(self, key, factory) -> bool:
        self.jobs.append(factory)
        return True

    async def run_all(self):
        jobs, self.jobs = self.jobs, []
        for factory in jobs:
            await factory()


def _storage(server: FakeKurrentDB, client=None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    client = client if client is not None else server.sync_client()
    return KurrentdbMemoryStorage(DeerMemConfig(), client_factory=lambda: client)


def _store(server: FakeKurrentDB, client=None):
    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStore

    client = client if client is not None else server.async_client()

    async def factory():
        return client

    return KurrentRunEventStore({}, client_factory=factory)


def _fact(fact_id: str, content: str, **extra) -> dict:
    return {"id": fact_id, "content": content, "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual", **extra}


def _create(storage, *facts, user_id="alice", agent=AGENT):
    return storage.apply_changes({"upserts": list(facts), "upsertRevisions": {fact["id"]: None for fact in facts}}, user_id=user_id, agent_name=agent)


def _events(server: FakeKurrentDB, stream: str) -> list:
    try:
        return list(server.sync_client().get_stream(stream))
    except Exception:
        return []


def _decoded(server: FakeKurrentDB, stream: str) -> list[tuple[str, object, dict]]:
    return [(event.type, from_json(EVENT_TYPE_BY_NAME[event.type], event.data.decode()), json.loads(event.metadata)) for event in _events(server, stream)]


def _canonical_streams(server: FakeKurrentDB) -> list[str]:
    return sorted(name for name, stream in server._streams.items() if name.startswith(("AgentMemory-", "AgentSession-")) and stream.events)


def _index_types(server: FakeKurrentDB) -> list[tuple[str, str]]:
    return [(event.type.rsplit(".", 1)[-1], json.loads(event.data)["intent_id"]) for event in _events(server, INDEX)]


def _human(text: str, message_id: str = "h1") -> dict:
    return {"type": "human", "content": text, "id": message_id, "name": None, "additional_kwargs": {}}


def _ai(text, message_id: str = "a1", tool_calls=None) -> dict:
    return {"type": "ai", "content": text, "id": message_id, "name": "lead_agent", "tool_calls": tool_calls or [], "additional_kwargs": {}}


def _tool(text: str, call_id: str = "call-1", name: str = "web_search", message_id: str = "tool-1") -> dict:
    return {"type": "tool", "content": text, "id": message_id, "name": name, "tool_call_id": call_id, "additional_kwargs": {}}


async def _conversation(store, thread_id="t1", run_id="r1"):
    await store.put(thread_id=thread_id, run_id=run_id, event_type="run.start", category="trace", content={"chain": "lead_agent"}, metadata={"caller": "lead_agent", "agent_name": "lead_agent", "model_name": "gpt-x"})
    await store.put(thread_id=thread_id, run_id=run_id, event_type="llm.human.input", category="message", content=_human("What is KurrentDB?", f"{run_id}-h"), metadata={"caller": "lead_agent"})
    await store.put(
        thread_id=thread_id, run_id=run_id, event_type="llm.ai.response", category="message", content=_ai("", f"{run_id}-a1", [{"id": "call-1", "name": "web_search", "args": {"q": "kurrentdb"}}]), metadata={"caller": "lead_agent"}
    )
    await store.put(thread_id=thread_id, run_id=run_id, event_type="llm.tool.result", category="message", content=_tool("KurrentDB is an event store"), metadata={})
    await store.put(thread_id=thread_id, run_id=run_id, event_type="llm.ai.response", category="message", content=_ai([{"type": "text", "text": "An event-native database."}], f"{run_id}-a2"), metadata={"caller": "lead_agent"})
    await store.put(thread_id=thread_id, run_id=run_id, event_type="llm.error", category="trace", content="ignored", metadata={})
    await store.put(thread_id=thread_id, run_id=run_id, event_type="run.end", category="outputs", content={}, metadata={"status": "success"})


# --- flag ---------------------------------------------------------------------


async def test_flag_off_writes_nothing(server, monkeypatch):
    monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", "off")
    storage = _storage(server)
    _create(storage, _fact("f1", "Prefers tea"))
    storage.save({"facts": [_fact("f2", "Lives in Oslo")]}, AGENT, user_id="alice")
    assert storage.flush_canonical(timeout=5)
    store = _store(server)
    await _conversation(store)
    await store.flush_canonical()
    assert _canonical_streams(server) == []
    assert not [call for call in server.calls if call.stream_name.startswith(("AgentMemory-", "AgentSession-"))]
    assert not [thread for thread in threading.enumerate() if thread.name == WORKER_THREAD]


# --- memory -------------------------------------------------------------------


def test_fact_retained_on_create_and_update(server):
    storage = _storage(server)
    _create(storage, _fact("f1", "Prefers tea"), _fact("f2", "Lives in Oslo"))
    storage.apply_changes({"upserts": [_fact("f1", "Prefers green tea")], "upsertRevisions": {"f1": 1}}, user_id="alice", agent_name=AGENT)
    storage.save({"facts": [_fact("f1", "Prefers green tea", revision=2), _fact("f2", "Lives in Oslo"), _fact("f3", "Plays chess")]}, AGENT, user_id="alice")
    # Nothing canonical for: a no-op, summaries only, deletions, and the global scope (no per-user stream).
    storage.apply_changes({"upserts": [_fact("f3", "Plays chess")], "upsertRevisions": {"f3": 1}}, user_id="alice", agent_name=AGENT)
    # Same content, new confidence and confirmations: a new fact revision, but nothing canonical (FactRetained is content only).
    changed = storage.apply_changes({"upserts": [_fact("f3", "Plays chess", confidence=0.4, confirmationCount=3)], "upsertRevisions": {"f3": 1}}, user_id="alice", agent_name=AGENT)
    assert [fact["revision"] for fact in changed["upsertedFacts"]] == [2]
    storage.apply_changes({"summaries": {"user": {"workContext": {"summary": "Builds DeerFlow", "updatedAt": "2026-11-01T00:00:00Z"}}}}, user_id="alice")
    assert storage.flush_canonical(timeout=5)  # f2 is emitted before its deletion (a later emission would be suppressed)
    storage.apply_changes({"deletes": ["f2"]}, user_id="alice", agent_name=AGENT)
    _create(storage, _fact("g1", "Global fact"), user_id=None)
    assert storage.flush_canonical(timeout=5)

    decoded = _decoded(server, ALICE_CANONICAL)
    assert [type_name for type_name, _, _ in decoded] == ["FactRetained"] * 4
    assert [(message.fact, metadata["deerflow.fact_id"], metadata["deerflow.fact_revision"]) for _, message, metadata in decoded] == [
        ("Prefers tea", "f1", 1),
        ("Lives in Oslo", "f2", 1),
        ("Prefers green tea", "f1", 2),
        ("Plays chess", "f3", 1),
    ]
    assert decoded[0][1].retained_at.ToJsonString() == "2026-11-01T00:00:00Z"
    assert _canonical_streams(server) == [ALICE_CANONICAL]
    # Another user's facts go to that user's stream.
    _create(storage, _fact("b1", "Bob's fact"), user_id="bob")
    assert storage.flush_canonical(timeout=5)
    assert [message.fact for _, message, _ in _decoded(server, agent_memory_stream("deerflow", "bob"))] == ["Bob's fact"]


def test_memory_emission_keeps_commit_order_and_runs_off_the_caller_thread(server):
    seen: list[str] = []
    client = Hooked(server.sync_client(), "append_to_stream", ALICE_CANONICAL, lambda: seen.append(threading.current_thread().name))
    storage = _storage(server, client)
    for index in range(5):
        _create(storage, _fact(f"f{index}", f"Fact {index}"))
    assert storage.flush_canonical(timeout=5)
    assert [message.fact for _, message, _ in _decoded(server, ALICE_CANONICAL)] == [f"Fact {index}" for index in range(5)]
    assert seen == [WORKER_THREAD]


# --- sessions -----------------------------------------------------------------


async def test_session_events_live_on_put(server):
    store = _store(server)
    await store.put(thread_id="t0", run_id="r0", event_type="ai_message", category="message", content="first")
    # Emission runs after the put returned (off the critical path): nothing canonical yet.
    assert _events(server, agent_session_stream("t0")) == []
    await store.flush_canonical()
    assert [event.type for event in _events(server, agent_session_stream("t0"))] == ["SessionStarted", "AssistantTextGenerated"]
    await _conversation(store)
    await store.flush_canonical()
    decoded = _decoded(server, T1_CANONICAL)
    # One canonical session per thread (R16): SessionStarted opens the stream; run.start/run.end map to nothing.
    assert [type_name for type_name, _, _ in decoded] == ["SessionStarted", "UserMessageReceived", "AssistantToolCallsGenerated", "ToolResultReceived", "AssistantTextGenerated"]
    started, user, calls, result, text = (message for _, message, _ in decoded)
    owner = json.loads(_events(server, "deerflow.run-events-t1")[1].metadata)["user_id"]  # the context user of the creating put
    assert owner and (started.app_name, started.user_id) == ("deerflow", owner)
    assert decoded[0][2]["deerflow.seq"] == 2 and "deerflow.run_id" not in decoded[0][2]  # precedes the first mapped record
    assert (user.content, user.message_id) == ("What is KurrentDB?", "r1-h")
    assert [(call.call_id, call.tool_name, dict(call.arguments)) for call in calls.tool_calls] == [("call-1", "web_search", {"q": "kurrentdb"})]
    assert (result.call_id, result.tool_name, result.result, result.message_id) == ("call-1", "web_search", "KurrentDB is an event store", "tool-1")
    assert (text.content, text.message_id) == ("An event-native database.", "r1-a2")

    # put_batch and put_if_absent emit too, in commit order; a second run opens no second session.
    await store.put_batch(
        [
            {"thread_id": "t1", "run_id": "r2", "event_type": "human_message", "category": "message", "content": "plain text"},
            {"thread_id": "t1", "run_id": "r2", "event_type": "ai_message", "category": "message", "content": "plain answer"},
        ]
    )
    await store.put_if_absent(thread_id="t1", run_id="r2", event_type="run.end", category="outputs", content={}, metadata={"status": "success"})
    await store.put_if_absent(thread_id="t1", run_id="r2", event_type="run.end", category="outputs", content={}, metadata={"status": "success"})
    await store.flush_canonical()
    assert [(type_name, metadata.get("deerflow.run_id")) for type_name, _, metadata in _decoded(server, T1_CANONICAL)][5:] == [
        ("UserMessageReceived", "r2"),
        ("AssistantTextGenerated", "r2"),
    ]
    # The session's user is the owner of the record that created the stream.
    await store.put_batch([{"thread_id": "t2", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "hi", "user_id": "alice"}])
    await store.flush_canonical()
    (_, opened, _), _ = _decoded(server, agent_session_stream("t2"))
    assert opened.user_id == "alice"


def test_chains_forget_a_closed_loops_pending_drain():
    from deerflow_extension_kurrentdb.canonical import AsyncChains

    chains = AsyncChains()
    started = []

    async def never_finishes():
        started.append(True)
        await asyncio.Event().wait()

    async def submit_and_leave():
        chains.submit("t1", never_finishes)
        await asyncio.sleep(0)

    old = asyncio.new_event_loop()
    old.run_until_complete(submit_and_leave())
    old.close()  # the drain task is still pending
    assert started and len(chains._tasks) == 1

    async def submit_again():
        ran = asyncio.Event()

        async def job():
            ran.set()

        chains.submit("t1", job)
        assert all(not task.get_loop().is_closed() for task in chains._tasks.values())
        await chains.flush()
        assert ran.is_set()

    asyncio.run(submit_again())
    assert chains._tasks == {} and chains._queues == {}


# --- provenance ---------------------------------------------------------------


async def test_canonical_metadata_provenance(server):
    from deerflow_extension_kurrentdb.canonical import mapping

    storage = _storage(server)
    first = _create(storage, _fact("f1", "Prefers tea"))
    second = storage.apply_changes({"upserts": [_fact("f1", "Prefers green tea")], "upsertRevisions": {"f1": 1}}, user_id="alice", agent_name=AGENT)
    assert storage.flush_canonical(timeout=5)
    recorded = _events(server, ALICE_CANONICAL)
    metadata = [json.loads(event.metadata) for event in recorded]
    assert metadata == [
        {"$schema_version": SCHEMA_VERSION, "schema_version": SCHEMA_VERSION, "deerflow.origin": first["revision"], "deerflow.fact_id": "f1", "deerflow.fact_revision": 1, "deerflow.agent": AGENT},
        {"$schema_version": SCHEMA_VERSION, "schema_version": SCHEMA_VERSION, "deerflow.origin": second["revision"], "deerflow.fact_id": "f1", "deerflow.fact_revision": 2, "deerflow.agent": AGENT},
    ]
    # Deterministic event ids: mapping the same commit again gives the same ids.
    again = mapping.memory_events(second, user_id="alice", agent=AGENT, origin=second["revision"])
    assert [event.event_id for event in again] == [recorded[1].id]
    assert len({event.id for event in recorded}) == 2

    store = _store(server)
    secret = {"caller": "lead_agent", "auth_token": "s3cret", "task_id": "x"}
    record = await store.put(thread_id="t1", run_id="r1", event_type="llm.human.input", category="message", content=_human("hello"), metadata=secret)
    await store.flush_canonical()
    opened, event = _events(server, T1_CANONICAL)
    assert json.loads(opened.metadata) == {"$schema_version": SCHEMA_VERSION, "schema_version": SCHEMA_VERSION, "deerflow.origin": record["seq"], "deerflow.seq": record["seq"], "deerflow.event_type": "session.start"}
    session_metadata = json.loads(event.metadata)
    assert session_metadata == {
        "$schema_version": SCHEMA_VERSION,
        "schema_version": SCHEMA_VERSION,
        "deerflow.origin": record["seq"],
        "deerflow.run_id": "r1",
        "deerflow.seq": record["seq"],
        "deerflow.event_type": "llm.human.input",
        "deerflow.metadata": {"caller": "lead_agent", "task_id": "x"},
    }
    assert "s3cret" not in event.metadata.decode() and "s3cret" not in event.data.decode()
    assert [item.event_id for item in mapping.session_events([record])] == [event.id]
    # Every canonical event type is a schema type.
    assert {item.type for item in mapping.session_events([record])} <= set(EVENT_TYPE_NAMES.values())


# --- failure isolation ----------------------------------------------------------


async def test_canonical_failure_never_fails_primary(server, monkeypatch, caplog):
    from deerflow_extension_kurrentdb.canonical import mapping

    storage = _storage(server)
    server.fail_next("append_to_stream", ServiceUnavailableError("canonical down"), stream_name=ALICE_CANONICAL)
    assert _create(storage, _fact("f1", "Prefers tea"))["revision"] == 1
    assert storage.flush_canonical(timeout=5)
    server.fail_next("get_current_version", ServiceUnavailableError("canonical down"), stream_name=ALICE_CANONICAL)
    assert _create(storage, _fact("f2", "Lives in Oslo"))["revision"] == 2
    assert storage.flush_canonical(timeout=5)
    # The deletions index unreadable during the pre-check: still no failure for the caller.
    real_queue, jobs = storage._canonical_queue, CapturedJobs()
    storage._canonical_queue = jobs
    assert storage.save({"facts": [_fact("f1", "Prefers tea"), _fact("f2", "Lives in Oslo"), _fact("f3", "Plays chess")]}, AGENT, user_id="alice")
    server.fail_next("get_current_version", ServiceUnavailableError("index down"), stream_name=INDEX)
    jobs.run_all()
    assert storage.load(AGENT, user_id="alice")["revision"] == 3
    assert _events(server, ALICE_CANONICAL) == []  # every emission failed, none raised
    storage._canonical_queue = real_queue

    store = _store(server)
    server.fail_next("append_to_stream", ServiceUnavailableError("canonical down"), stream_name=T1_CANONICAL)
    record = await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="hi")
    assert record["seq"] == 1
    await store.flush_canonical()

    def broken(*args, **kwargs):
        raise RuntimeError("mapping bug")

    monkeypatch.setattr(mapping, "session_events", broken)
    monkeypatch.setattr(mapping, "memory_events", broken)
    assert (await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="again"))["seq"] == 2
    assert _create(storage, _fact("f4", "Reads novels"))["revision"] == 4
    await store.flush_canonical()
    assert storage.flush_canonical(timeout=5)
    assert _events(server, T1_CANONICAL) == []
    assert "canonical" in caplog.text.lower()


async def test_emitter_retries_conflicts_and_gives_up_after_its_lifetime(server, monkeypatch):
    from deerflow_extension_kurrentdb.canonical import emitter

    assert emitter.MAX_LIFETIME_SECONDS == 60.0
    foreign = NewEvent(id=uuid.uuid4(), type="FactRetained", data=to_json(FactRetained(fact="from another writer")).encode(), metadata=b"{}")
    client = Hooked(server.sync_client(), "get_current_version", ALICE_CANONICAL, lambda: server.sync_client().append_to_stream(ALICE_CANONICAL, events=[foreign], current_version=StreamState.ANY), after=True)
    storage = _storage(server, client)
    _create(storage, _fact("f1", "Prefers tea"))
    assert storage.flush_canonical(timeout=5)
    assert [message.fact for _, message, _ in _decoded(server, ALICE_CANONICAL)] == ["from another writer", "Prefers tea"]
    canonical_appends = server.calls_to("append_to_stream", ALICE_CANONICAL)
    assert all(call.kwargs["current_version"] is not StreamState.ANY for call in canonical_appends[1:])
    ours = [call for call in server.calls if call.stream_name == ALICE_CANONICAL and call.method != "get_stream" and call.kwargs.get("current_version") is not StreamState.ANY]
    assert ours and all(0 < call.kwargs["timeout"] <= TIMEOUT for call in ours)

    # A job that outlived the maximum emitter lifetime writes nothing.
    monkeypatch.setattr(emitter, "MAX_LIFETIME_SECONDS", 0.0)
    _create(storage, _fact("f2", "Lives in Oslo"))
    assert storage.flush_canonical(timeout=5)
    store = _store(server)
    await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="late")
    await store.flush_canonical()
    assert [message.fact for _, message, _ in _decoded(server, ALICE_CANONICAL)] == ["from another writer", "Prefers tea"]
    assert _events(server, T1_CANONICAL) == []


# --- stale-delivery suppression and repair ---------------------------------------


def _mark_cleanup_done(server: FakeKurrentDB, intent_id: str) -> None:
    from deerflow_extension_kurrentdb.deletions import CANONICAL_CLEANUP_DONE, index_event

    server.sync_client().append_to_stream(INDEX, events=[index_event(CANONICAL_CLEANUP_DONE, intent_id)], current_version=StreamState.ANY)


def _intent_ids(server: FakeKurrentDB, kind: str = "DeletionIntended") -> list[str]:
    return [intent_id for type_name, intent_id in _index_types(server) if type_name == kind]


async def test_stale_emitter_suppressed_after_cleanup_done(server):
    storage = _storage(server)
    jobs = storage._canonical_queue = CapturedJobs()
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    _create(storage, _fact("f3", "Also kept"))
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    (intent_id,) = _intent_ids(server)
    assert ("DeletionDone", intent_id) in _index_types(server)
    _mark_cleanup_done(server, intent_id)
    _create(storage, _fact("f1", "Recreated after the deletion"))
    jobs.run_all()  # the delayed emitters only now reach KurrentDB
    assert [(metadata["deerflow.fact_id"], message.fact) for _, message, metadata in _decoded(server, ALICE_CANONICAL)] == [("f2", "Kept"), ("f3", "Also kept"), ("f1", "Recreated after the deletion")]

    store = _store(server)
    chains = store._canonical_chains = CapturedChains()
    await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="doomed")
    await store.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message", content="kept")
    await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="doomed, owns the max seq")
    assert await store.delete_by_run("t1", "r1") == 2
    run_intent = _intent_ids(server)[-1]
    _mark_cleanup_done(server, run_intent)
    await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="r1 again, after the deletion")
    await chains.run_all()
    decoded = _decoded(server, T1_CANONICAL)
    assert [type_name for type_name, _, _ in decoded][:1] == ["SessionStarted"]
    assert [(metadata["deerflow.run_id"], message.content) for _, message, metadata in decoded[1:]] == [("r2", "kept"), ("r1", "r1 again, after the deletion")]
    assert not _intent_ids(server, "CanonicalCleanupReopened")


async def test_post_append_recheck_reopens(server):
    holder = {}

    def delete_concurrently():
        holder["storage"].apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)

    storage = holder["storage"] = _storage(server, Hooked(server.sync_client(), "get_current_version", ALICE_CANONICAL, delete_concurrently))
    jobs = storage._canonical_queue = CapturedJobs()
    _create(storage, _fact("f1", "Doomed"))
    jobs.run_all()  # pre-check passes, the deletion commits, then the stale append lands
    (intent_id,) = _intent_ids(server)
    assert [message.fact for _, message, _ in _decoded(server, ALICE_CANONICAL)] == ["Doomed"]
    assert _intent_ids(server, "CanonicalCleanupReopened") == [intent_id]

    # Sessions: a no-survivors cleanup soft-deleted the canonical stream before the stale append recreated it.
    async def delete_thread_and_clean_up():
        await store.delete_by_thread("t1")
        server.sync_client().delete_stream(T1_CANONICAL, current_version=StreamState.ANY)
        _mark_cleanup_done(server, _intent_ids(server)[-1])

    hooked = AsyncHooked(server.async_client(), "get_current_version", T1_CANONICAL, None)
    store = _store(server, hooked)
    await store.put(thread_id="t1", run_id="r0", event_type="ai_message", category="message", content="emitted before")
    await store.flush_canonical()
    hooked._hook = delete_thread_and_clean_up
    chains = store._canonical_chains = CapturedChains()
    await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="stale")
    await chains.run_all()
    thread_intent = _intent_ids(server)[-1]
    assert [(type_name, getattr(message, "content", None)) for type_name, message, _ in _decoded(server, T1_CANONICAL)] == [("SessionStarted", None), ("AssistantTextGenerated", "stale")]  # recreated, reopened
    assert _intent_ids(server, "CanonicalCleanupReopened") == [intent_id, thread_intent]
    # Each reopen is its own index event, so a second stale delivery reopens again.
    reopened = [event for event in _events(server, INDEX) if event.type.endswith("CanonicalCleanupReopened")]
    assert len({event.id for event in reopened}) == 2


# --- consumers ------------------------------------------------------------------


async def test_consumer_deserializes_every_event(server):
    storage = _storage(server)
    _create(storage, _fact("f1", "Prefers tea"), _fact("f2", "Lives in Oslo"))
    storage.apply_changes({"upserts": [_fact("f1", "Prefers green tea")], "upsertRevisions": {"f1": 1}}, user_id="alice", agent_name=AGENT)
    assert storage.flush_canonical(timeout=5)  # emitted before the delete (a later emission would be suppressed)
    storage.apply_changes({"deletes": ["f2"]}, user_id="alice", agent_name=AGENT)
    store = _store(server)
    await _conversation(store, run_id="r1")
    await _conversation(store, run_id="r2")
    await store.flush_canonical()
    await store.delete_by_run("t1", "r1")
    server.sync_client().delete_stream(T1_CANONICAL, current_version=StreamState.ANY)  # as a no-survivors cleanup would
    await _conversation(store, run_id="r3")  # recreates the soft-deleted stream
    assert storage.flush_canonical(timeout=5)
    await store.flush_canonical()

    counted = 0
    for stream in _canonical_streams(server):
        for event in _events(server, stream):
            message_type = EVENT_TYPE_BY_NAME[event.type]
            message = from_json(message_type, event.data.decode("utf-8"))
            assert EVENT_TYPE_NAMES[type(message)] == event.type
            metadata = json.loads(event.metadata)
            assert metadata["$schema_version"] == metadata["schema_version"] == SCHEMA_VERSION and isinstance(metadata["deerflow.origin"], int)
            counted += 1
    assert counted == 3 + 5  # three fact versions; the recreated session: SessionStarted + four messages of r3
    assert {metadata.get("deerflow.run_id") for _, _, metadata in _decoded(server, T1_CANONICAL)} == {None, "r3"}
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith(WORKER_THREAD)]  # no emission task left behind
