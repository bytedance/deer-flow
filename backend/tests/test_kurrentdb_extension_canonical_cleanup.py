"""Canonical cleanup (deletion step 4), its verification pass, and the extension's recovery service."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from kurrent_agent_schema import EVENT_TYPE_BY_NAME, EVENT_TYPE_NAMES, agent_memory_stream, agent_session_stream, from_json
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient.exceptions import DeadlineExceededError, ServiceUnavailableError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryManifestRevisionConflict

pytestmark = [pytest.mark.bundled_extension, pytest.mark.anyio]

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
#: Past the maximum emitter lifetime (60 s) plus one timeout of margin.
PAST_VERIFICATION = 60.0 + TIMEOUT + 1
AGENT = "__default__"
ALICE_PRIMARY = "deerflow.memory-user.alice"
ALICE_CANONICAL = agent_memory_stream("deerflow", "alice")
BOB_CANONICAL = agent_memory_stream("deerflow", "bob")
T1_PRIMARY = "deerflow.run-events-t1"
T1_CANONICAL = agent_session_stream("t1")
INDEX = "deerflow.kurrent-deletions"
WORKER_THREADS = ("kurrentdb-canonical", "kurrentdb-recovery")


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))
    monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", "on")


@pytest.fixture(autouse=True)
def _no_leaked_workers():
    yield
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and [thread for thread in threading.enumerate() if thread.name.startswith(WORKER_THREADS)]:
        time.sleep(0.01)
    assert not [thread for thread in threading.enumerate() if thread.name.startswith(WORKER_THREADS)], "a worker thread outlived its test"


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


class Clock:
    """Wall-clock seconds the test moves by hand (verification waits on it, never on real time)."""

    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


class Hooked:
    """A sync client that runs ``hook`` once, before a call to ``method`` on ``stream``."""

    def __init__(self, inner, method: str, stream: str, hook=None):
        self._inner, self._method, self._stream, self.hook = inner, method, stream, hook

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        def call(stream_name, *args, **kwargs):
            if stream_name == self._stream and self.hook is not None:
                hook, self.hook = self.hook, None
                hook()
            return target(stream_name, *args, **kwargs)

        return call


class AsyncHooked(Hooked):
    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        async def call(stream_name, *args, **kwargs):
            if stream_name == self._stream and self.hook is not None:
                hook, self.hook = self.hook, None
                await hook()
            return await target(stream_name, *args, **kwargs)

        return call


def _is_canonical(stream_name: str) -> bool:
    return stream_name.startswith(("AgentMemory-", "AgentSession-"))


class CanonicalDown:
    """A sync client whose canonical-stream calls fail while ``down`` (and record the calling thread)."""

    def __init__(self, inner):
        self._inner = inner
        self.down = True
        self.threads: list[str] = []

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(stream_name, *args, **kwargs):
            if _is_canonical(stream_name):
                self.threads.append(threading.current_thread().name)
                if self.down:
                    raise ServiceUnavailableError("canonical stream unavailable")
            return target(stream_name, *args, **kwargs)

        return call


class AsyncCanonicalDown(CanonicalDown):
    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target) or name in ("connect", "close"):
            return target

        async def call(stream_name, *args, **kwargs):
            if _is_canonical(stream_name):
                self.threads.append("async")
                if self.down:
                    raise ServiceUnavailableError("canonical stream unavailable")
            return await target(stream_name, *args, **kwargs)

        return call


class CapturedJobs:
    def __init__(self):
        self.jobs = []

    def submit(self, job) -> bool:
        self.jobs.append(job)
        return True

    def run_all(self):
        while self.jobs:
            self.jobs.pop(0)()

    def flush(self, timeout=None) -> bool:
        return True


class CapturedChains:
    def __init__(self):
        self.jobs = []

    def submit(self, key, factory) -> bool:
        self.jobs.append(factory)
        return True

    async def run_all(self):
        while self.jobs:
            await self.jobs.pop(0)()

    async def flush(self):
        await self.run_all()


def _storage(server: FakeKurrentDB, client=None, clock=None, config=None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    client = client if client is not None else server.sync_client()
    return KurrentdbMemoryStorage(config or DeerMemConfig(), client_factory=lambda: client, clock=clock)


KURRENT_STORAGE_CLASS = "deerflow_extension_kurrentdb.memory.KurrentdbMemoryStorage"


def _both_backends():
    """The Gateway config the service reads: both KurrentDB backends on, default DeerMem settings."""
    from deerflow_extension_kurrentdb.service import Backends

    return Backends(memory={"storage_class": KURRENT_STORAGE_CLASS}, run_events=True)


def _store(server: FakeKurrentDB, client=None, clock=None):
    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStore

    client = client if client is not None else server.async_client()

    async def factory():
        return client

    return KurrentRunEventStore({}, client_factory=factory, clock=clock)


def _fact(fact_id: str, content: str) -> dict:
    return {"id": fact_id, "content": content, "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual"}


def _create(storage, *facts, user_id="alice", agent=AGENT, **kwargs):
    return storage.apply_changes({"upserts": list(facts), "upsertRevisions": {fact["id"]: None for fact in facts}}, user_id=user_id, agent_name=agent, **kwargs)


def _events(server: FakeKurrentDB, stream: str) -> list:
    try:
        return list(server.sync_client().get_stream(stream))
    except Exception:
        return []


def _metadata(event) -> dict:
    return json.loads(event.metadata)


def _facts(server: FakeKurrentDB, stream: str = ALICE_CANONICAL) -> list[str]:
    return [from_json(EVENT_TYPE_BY_NAME[event.type], event.data.decode()).fact for event in _events(server, stream)]


def _session(server: FakeKurrentDB, stream: str = T1_CANONICAL) -> list[tuple[str, str | None, str | None]]:
    """``(type, run id, text)`` of every readable session event."""
    out = []
    for event in _events(server, stream):
        message = from_json(EVENT_TYPE_BY_NAME[event.type], event.data.decode())
        out.append((event.type, _metadata(event).get("deerflow.run_id"), getattr(message, "content", None)))
    return out


def _index(server: FakeKurrentDB) -> list[tuple[str, str]]:
    return [(event.type.rsplit(".", 1)[-1], json.loads(event.data)["intent_id"]) for event in _events(server, INDEX)]


def _intents(server: FakeKurrentDB) -> list[str]:
    return [intent_id for kind, intent_id in _index(server) if kind == "DeletionIntended"]


def _kinds(server: FakeKurrentDB, intent_id: str) -> list[str]:
    return [kind for kind, other in _index(server) if other == intent_id]


def _assert_consumable(server: FakeKurrentDB) -> None:
    """Every readable canonical event deserializes as a kurrent-agents type and carries the provenance keys."""
    for name in [name for name, stream in server._streams.items() if _is_canonical(name) and stream.events]:
        for event in _events(server, name):
            message = from_json(EVENT_TYPE_BY_NAME[event.type], event.data.decode())
            assert EVENT_TYPE_NAMES[type(message)] == event.type
            assert isinstance(_metadata(event)["deerflow.origin"], int)


def _identities(server: FakeKurrentDB, stream: str) -> list:
    from deerflow_extension_kurrentdb.canonical.cleanup import identity

    return [identity(_metadata(event)) for event in _events(server, stream)]


async def _say(store, text: str, run_id: str, thread_id: str = "t1"):
    return await store.put(thread_id=thread_id, run_id=run_id, event_type="ai_message", category="message", content=text)


# --- obligations follow the primary side -----------------------------------------


async def test_canonical_cleanup_starts_only_after_primary_commit(server, clock):
    from deerflow_extension_kurrentdb.deletions import DeletionOutcomeUnknown

    store = _store(server, clock=clock)
    await _say(store, "doomed", "r1")
    await _say(store, "kept", "r2")
    await store.flush_canonical()
    # The boundary's commit is delayed and the settling fence fails: the deletion's outcome is unknown.
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("lost"), stream_name=T1_PRIMARY)
    server.fail_next("append_to_stream", ServiceUnavailableError("fence lost"), stream_name=T1_PRIMARY)
    with pytest.raises(DeletionOutcomeUnknown):
        await store.delete_by_run("t1", "r1")
    (intent_id,) = _intents(server)
    await store.flush_canonical()
    await store.run_canonical_obligations()
    assert _kinds(server, intent_id) == ["DeletionIntended"]  # no canonical step before the boundary is proven present
    assert [text for _, _, text in _session(server)] == [None, "doomed", "kept"]

    pending.release()  # the boundary commits late
    report = await store.run_canonical_obligations()
    assert report.cleaned == 1
    assert [text for _, _, text in _session(server)] == [None, "kept"]
    assert "CanonicalCleanupDone" in _kinds(server, intent_id)


def test_abandoned_intent_keeps_canonical_data(server, clock):
    storage = _storage(server, clock=clock)
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept, its deletion is abandoned"))
    assert storage.flush_canonical(timeout=5)
    jobs = storage._canonical_queue = CapturedJobs()
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)  # deletion A commits; its cleanup waits
    # Deletion B: the boundary request is lost and the fence lands, so B is abandoned (and not retried: a pinned revision).
    revision = storage.load(AGENT, user_id="alice")["revision"]
    server.fail_next("append_to_stream", ServiceUnavailableError("request lost"), stream_name=ALICE_PRIMARY)
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.apply_changes({"deletes": ["f2"]}, user_id="alice", agent_name=AGENT, expected_manifest_revision=revision)
    first, second = _intents(server)
    assert "DeletionAbandoned" in _kinds(server, second)
    jobs.run_all()
    storage.run_canonical_obligations()
    assert _facts(server) == ["Kept, its deletion is abandoned"]
    assert "CanonicalCleanupDone" in _kinds(server, first)
    assert [kind for kind in _kinds(server, second) if kind.startswith("Canonical")] == []
    assert storage.load(AGENT, user_id="alice")["facts"][0]["id"] == "f2"


# --- serialization: live appends and outstanding deletions -------------------------


async def test_live_append_and_two_deletions_race_rewrite(server, clock):
    live = _store(server)  # another writer, emitting for real

    async def live_append(text):
        await _say(live, text, "r3")
        await live.flush_canonical()

    truncation_race = AsyncHooked(server.async_client(), "get_stream_metadata", T1_CANONICAL)
    rewrite_race = AsyncHooked(truncation_race, "append_to_stream", T1_CANONICAL)
    store = _store(server, rewrite_race, clock=clock)
    for run_id in ("r1", "r2", "r3"):
        await _say(store, f"{run_id} first", run_id)
        await _say(store, f"{run_id} second", run_id)
    await store.flush_canonical()
    chains = store._canonical_chains = CapturedChains()
    assert await store.delete_by_run("t1", "r1") == 2
    assert await store.delete_by_run("t1", "r2") == 2  # two outstanding deletions, neither cleaned yet
    first, second = _intents(server)
    # A live event lands between the cleanup's read and its append (conflict, reselect),
    # and another between the append and the $tb raise (after the copies, so it stays readable).
    rewrite_race.hook = lambda: live_append("live during the rewrite")
    truncation_race.hook = lambda: live_append("live during the truncation")
    await chains.run_all()

    texts = [text for _, _, text in _session(server)]
    assert texts == [None, "r3 first", "r3 second", "live during the rewrite", "live during the truncation"]
    identities = _identities(server, T1_CANONICAL)
    assert len(identities) == len(set(identities))
    assert "CanonicalCleanupDone" in _kinds(server, first) and "CanonicalCleanupDone" in _kinds(server, second)
    # The primary agrees: r1 and r2 are gone, every live event survived.
    assert [message["content"] for message in await store.list_messages("t1")] == ["r3 first", "r3 second", "live during the rewrite", "live during the truncation"]

    clock.advance(PAST_VERIFICATION)
    report = await store.run_canonical_obligations()
    assert report.verified == 2
    assert [text for _, _, text in _session(server)] == texts
    _assert_consumable(server)


def test_post_clear_save_survives_delayed_cleanup_and_second_deletion(server, clock):
    storage = _storage(server, clock=clock)
    _create(storage, _fact("f1", "Before the clear"), _fact("f2", "Also before"))
    assert storage.flush_canonical(timeout=5)
    jobs = storage._canonical_queue = CapturedJobs()
    storage.clear_all(user_id="alice")  # its canonical cleanup is delayed
    _create(storage, _fact("f3", "Saved after the clear"), _fact("f4", "Also after, deleted later"))
    storage.apply_changes({"deletes": ["f4"]}, user_id="alice", agent_name=AGENT)  # the second deletion
    jobs.run_all()  # emissions and both cleanups, in commit order
    assert _facts(server) == ["Saved after the clear"]
    clock.advance(PAST_VERIFICATION)
    assert storage.run_canonical_obligations().verified == 2
    assert _facts(server) == ["Saved after the clear"]


async def test_post_delete_new_run_survives_delayed_cleanup_and_second_deletion(server, clock):
    store = _store(server, clock=clock)
    await _say(store, "r0 before", "r0")
    await _say(store, "r1 before", "r1")
    await store.flush_canonical()
    chains = store._canonical_chains = CapturedChains()
    await store.delete_by_run("t1", "r1")  # its canonical cleanup is delayed
    await _say(store, "r2 after the deletion", "r2")
    await _say(store, "r1 again, after the deletion", "r1")
    await store.delete_by_run("t1", "r0")  # the second deletion
    await chains.run_all()
    assert [(kind, text) for kind, _, text in _session(server)] == [("SessionStarted", None), ("AssistantTextGenerated", "r2 after the deletion"), ("AssistantTextGenerated", "r1 again, after the deletion")]
    clock.advance(PAST_VERIFICATION)
    assert (await store.run_canonical_obligations()).verified == 2


async def test_no_survivor_soft_delete_conflicts_with_valid_live_append(server, clock):
    live = _store(server)
    hooked = AsyncHooked(server.async_client(), "delete_stream", T1_CANONICAL)
    store = _store(server, hooked, clock=clock)
    await _say(store, "doomed", "r1")
    await store.flush_canonical()

    async def live_append():
        await _say(live, "valid, after the clear", "r2")
        await live.flush_canonical()

    hooked.hook = live_append  # lands between the cleanup's read and its conditional soft delete
    chains = store._canonical_chains = CapturedChains()
    assert await store.delete_by_thread("t1") == 1
    (intent_id,) = _intents(server)
    await chains.run_all()
    assert [text for _, _, text in _session(server)] == ["valid, after the clear"]
    assert [message["content"] for message in await store.list_messages("t1")] == ["valid, after the clear"]
    assert "CanonicalCleanupDone" in _kinds(server, intent_id)
    clock.advance(PAST_VERIFICATION)
    assert (await store.run_canonical_obligations()).verified == 1
    _assert_consumable(server)


# --- stale deliveries --------------------------------------------------------------


async def test_emitter_paused_past_soft_delete_is_removed_by_reopen(server, clock):
    hooked = AsyncHooked(server.async_client(), "get_current_version", T1_CANONICAL)
    store = _store(server, hooked, clock=clock)
    await _say(store, "emitted before", "r0")
    await store.flush_canonical()

    async def delete_thread_and_clean_up():
        await store.delete_by_thread("t1")
        await store._cleaner.run(stream=T1_PRIMARY, verify=False)  # soft-deletes the session stream, CleanupDone
        assert _events(server, T1_CANONICAL) == []

    chains = store._canonical_chains = CapturedChains()
    await _say(store, "stale", "r1")
    hooked.hook = delete_thread_and_clean_up  # the stale emitter passed its pre-check, then pauses here
    await chains.jobs.pop(0)()  # the paused emission: the deletion and its cleanup run, then the stale append lands
    (intent_id,) = _intents(server)
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupReopened"  # the post-append check caught it
    assert [text for _, _, text in _session(server)] == [None, "stale"]  # recreated stream
    await chains.run_all()  # the cleanup the deletion queued: the reopened cleanup soft-deletes the stream again
    assert _events(server, T1_CANONICAL) == []
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupDone"
    clock.advance(PAST_VERIFICATION)
    assert (await store.run_canonical_obligations()).verified == 1
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupVerified"


@pytest.mark.parametrize("failure", ["crash_after_append", "post_check_read_fails"])
def test_crash_after_stale_append_verification_removes(server, clock, failure):
    hooked = Hooked(server.sync_client(), "get_current_version", ALICE_CANONICAL)
    storage = _storage(server, hooked, clock=clock)
    _create(storage, _fact("f0", "Kept"))
    assert storage.flush_canonical(timeout=5)
    jobs = storage._canonical_queue = CapturedJobs()
    _create(storage, _fact("f1", "Doomed"))

    def delete_and_clean_up():
        storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
        storage._cleaner.run(verify=False)  # nothing to remove yet: done at the current head
        if failure == "crash_after_append":
            storage._canonical._post_check = lambda *args: None  # the process dies right after its append
        else:
            server.fail_next("get_current_version", ServiceUnavailableError("index down"), stream_name=INDEX)

    hooked.hook = delete_and_clean_up
    jobs.run_all()
    (intent_id,) = _intents(server)
    assert _facts(server) == ["Kept", "Doomed"]  # the stale delivery landed, unnoticed
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupDone"

    restarted = _storage(server, clock=clock)  # cold restart
    report = restarted.run_canonical_obligations()
    assert report.verified == 0 and report.next_due == pytest.approx(clock.now + 60.0 + TIMEOUT)  # waits out the emitter lifetime
    assert _facts(server) == ["Kept", "Doomed"]
    clock.advance(PAST_VERIFICATION)
    report = restarted.run_canonical_obligations()
    assert (report.reopened, report.cleaned, report.verified) == (1, 1, 0)
    assert _facts(server) == ["Kept"]
    assert _kinds(server, intent_id)[-2:] == ["CanonicalCleanupReopened", "CanonicalCleanupDone"]
    clock.advance(PAST_VERIFICATION)
    assert restarted.run_canonical_obligations().verified == 1
    assert _facts(server) == ["Kept"]


def test_rewrite_never_re_emits_what_another_deletion_removed(server, clock):
    storage = _storage(server, clock=clock)
    _create(storage, _fact("f0", "Kept"))
    assert storage.flush_canonical(timeout=5)
    jobs = storage._canonical_queue = CapturedJobs()
    _create(storage, _fact("f1", "Doomed by A"))
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)  # deletion A
    first = _intents(server)[0]
    pending_emission, *kicks = jobs.jobs
    jobs.jobs = kicks
    jobs.run_all()  # A's cleanup runs before the delayed emission of f1
    assert "CanonicalCleanupDone" in _kinds(server, first)
    storage._canonical._post_check = lambda *args: None  # the stale emitter's process dies right after its append
    from deerflow_extension_kurrentdb.canonical import emitter

    real_keep = emitter._keep
    emitter._keep = lambda pending, intents: list(pending)  # it passed its pre-check before A committed
    try:
        pending_emission()
    finally:
        emitter._keep = real_keep
    assert _facts(server) == ["Kept", "Doomed by A"]  # stale, unverified
    _create(storage, _fact("f2", "Doomed by B"))
    storage.apply_changes({"deletes": ["f2"]}, user_id="alice", agent_name=AGENT)  # deletion B rewrites the stream
    jobs.run_all()
    assert _facts(server) == ["Kept"]  # B's rewrite drops A's stale event too (any primary-committed intent), never copies it


def test_cleanup_retry_after_failed_truncation_appends_no_second_copies(server, clock):
    storage = _storage(server, clock=clock)
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    assert storage.flush_canonical(timeout=5)
    server.fail_next("set_stream_metadata", ServiceUnavailableError("metadata down"), stream_name=ALICE_CANONICAL)
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    assert storage.flush_canonical(timeout=5)
    (intent_id,) = _intents(server)
    assert [kind for kind in _kinds(server, intent_id) if kind.startswith("Canonical")] == []  # copies appended, $tb not raised
    appended = len(server._streams[ALICE_CANONICAL].events)
    assert storage.run_canonical_obligations().cleaned == 1
    assert len(server._streams[ALICE_CANONICAL].events) == appended  # the survivors already are the tail: only $tb is raised
    assert _facts(server) == ["Kept"]


async def test_session_rewrite_never_re_emits_what_another_deletion_removed(server, clock):
    from deerflow_extension_kurrentdb.canonical import emitter

    store = _store(server, clock=clock)
    await _say(store, "kept", "r0")
    await store.flush_canonical()
    chains = store._canonical_chains = CapturedChains()
    await _say(store, "doomed by A", "r1")
    await store.delete_by_run("t1", "r1")  # deletion A
    first = _intents(server)[0]
    pending_emission, *kicks = chains.jobs
    chains.jobs = kicks
    await chains.run_all()  # A's cleanup runs before the delayed emission of r1
    assert "CanonicalCleanupDone" in _kinds(server, first)

    async def no_post_check(*args):
        return None  # the stale emitter's process dies right after its append

    store._canonical._post_check = no_post_check
    real_keep = emitter._keep
    emitter._keep = lambda pending, intents: list(pending)  # it passed its pre-check before A committed
    try:
        await pending_emission()
    finally:
        emitter._keep = real_keep
    assert [text for _, _, text in _session(server)] == [None, "kept", "doomed by A"]  # stale, unverified
    await _say(store, "doomed by B", "r2")
    await store.delete_by_run("t1", "r2")  # deletion B rewrites the stream
    await chains.run_all()
    assert [text for _, _, text in _session(server)] == [None, "kept"]  # B's rewrite drops A's stale event too, never copies it


async def test_session_cleanup_retry_after_failed_truncation_appends_no_second_copies(server, clock):
    store = _store(server, clock=clock)
    await _say(store, "doomed", "r1")
    await _say(store, "kept", "r2")
    await store.flush_canonical()
    server.fail_next("set_stream_metadata", ServiceUnavailableError("metadata down"), stream_name=T1_CANONICAL)
    await store.delete_by_run("t1", "r1")
    await store.flush_canonical()
    (intent_id,) = _intents(server)
    assert [kind for kind in _kinds(server, intent_id) if kind.startswith("Canonical")] == []  # copies appended, $tb not raised
    appended = len(server._streams[T1_CANONICAL].events)
    assert (await store.run_canonical_obligations()).cleaned == 1
    assert len(server._streams[T1_CANONICAL].events) == appended  # the survivors already are the tail: only $tb is raised
    assert [text for _, _, text in _session(server)] == [None, "kept"]


# --- failure surfacing ---------------------------------------------------------------


async def test_primary_writes_prompt_while_canonical_down(server, clock, monkeypatch):
    from deerflow_extension_kurrentdb.canonical import cleanup

    sync = CanonicalDown(server.sync_client())
    storage = _storage(server, sync, clock=clock)
    sync.down = False
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    assert storage.flush_canonical(timeout=5)
    sync.down, sync.threads = True, []
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    _create(storage, _fact("f3", "Written while canonical is down"))
    assert sorted(fact["id"] for fact in storage.load(AGENT, user_id="alice")["facts"]) == ["f2", "f3"]
    assert storage.flush_canonical(timeout=5)
    assert sync.threads and set(sync.threads) == {"kurrentdb-canonical"}  # never on the caller's thread
    (intent_id,) = _intents(server)
    assert [kind for kind in _kinds(server, intent_id) if kind.startswith("Canonical")] == []
    assert "Doomed" in _facts(server)  # by design, until cleanup succeeds

    async_client = AsyncCanonicalDown(server.async_client())
    async_client.down = False
    store = _store(server, async_client, clock=clock)
    await _say(store, "doomed", "r1")
    await _say(store, "kept", "r2")
    await store.flush_canonical()
    async_client.down, async_client.threads = True, []
    assert await store.delete_by_run("t1", "r1") == 1
    assert async_client.threads == []  # the deletion returned before any canonical call (cleanup runs in a chain task)
    assert (await _say(store, "after the deletion", "r2"))["seq"] == 3
    assert [message["content"] for message in await store.list_messages("t1")] == ["kept", "after the deletion"]
    await store.flush_canonical()
    assert async_client.threads  # the cleanup was tried in the background, and failed
    thread_intent = _intents(server)[-1]
    assert [kind for kind in _kinds(server, thread_intent) if kind.startswith("Canonical")] == []

    # Canonical is back: the next write of the scope retries the pending cleanup in the background.
    sync.down = async_client.down = False
    monkeypatch.setattr(cleanup, "KICK_BACKOFF_SECONDS", 0.0)
    _create(storage, _fact("f4", "After the repair"))
    assert storage.flush_canonical(timeout=5)
    assert _facts(server) == ["Kept", "After the repair"]
    await _say(store, "after the repair", "r2")
    await store.flush_canonical()
    assert [text for _, _, text in _session(server)] == [None, "kept", "after the repair"]


async def test_canonical_failure_after_intent_deleter_gone_restart_recovers(server, clock):
    from deerflow_extension_kurrentdb import KurrentRecoveryService

    down = CanonicalDown(server.sync_client())
    down.down = False
    deleter = _storage(server, down, clock=clock)
    _create(deleter, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    assert deleter.flush_canonical(timeout=5)
    down.down = True
    deleter.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    assert deleter.flush_canonical(timeout=5)
    del deleter  # the deleting process is gone; its canonical cleanup never ran
    (intent_id,) = _intents(server)
    assert _facts(server) == ["Doomed", "Kept"]

    service = KurrentRecoveryService(memory_factory=lambda config: _storage(server, clock=clock, config=config), store_factory=lambda: _store(server, clock=clock), config_source=_both_backends, interval=3600, clock=clock)
    await service.start(None)
    try:
        for _ in range(500):
            if "CanonicalCleanupDone" in _kinds(server, intent_id):
                break
            await asyncio.sleep(0.01)
        assert _facts(server) == ["Kept"]
        clock.advance(PAST_VERIFICATION)
        assert await service.run_canonical() is None
        assert _kinds(server, intent_id)[-1] == "CanonicalCleanupVerified"
    finally:
        await service.stop()


# --- recovery service ------------------------------------------------------------------


class _HangingCanonical:
    """Canonical calls block until ``release`` (an unreachable canonical side); other calls pass through."""

    def __init__(self, inner, gate: threading.Event):
        self._inner, self._gate = inner, gate

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(stream_name, *args, **kwargs):
            if _is_canonical(stream_name):
                self._gate.wait(10)
                raise DeadlineExceededError("canonical side unreachable")
            return target(stream_name, *args, **kwargs)

        return call


class _AsyncHangingCanonical(_HangingCanonical):
    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target) or name in ("connect", "close"):
            return target

        async def call(stream_name, *args, **kwargs):
            if _is_canonical(stream_name):
                while not self._gate.is_set():
                    await asyncio.sleep(0.01)
                raise DeadlineExceededError("canonical side unreachable")
            return await target(stream_name, *args, **kwargs)

        return call


async def test_startup_recovery_does_not_block_on_canonical(server, clock):
    from deerflow_extension_kurrentdb import KurrentRecoveryService

    # Two deletions whose primary side was cut short ($tb never raised): open intents at restart.
    storage = _storage(server, clock=clock)
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    assert storage.flush_canonical(timeout=5)
    storage._canonical_queue = CapturedJobs()  # the deleting process dies before its canonical kick runs
    server.fail_next("set_stream_metadata", ServiceUnavailableError("crash"), stream_name=ALICE_PRIMARY)
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    store = _store(server, clock=clock)
    await _say(store, "doomed", "r1")
    await _say(store, "kept", "r2")
    await store.flush_canonical()
    store._canonical_chains = CapturedChains()
    server.fail_next("set_stream_metadata", ServiceUnavailableError("crash"), stream_name=T1_PRIMARY)
    await store.delete_by_run("t1", "r1")
    memory_intent, run_intent = _intents(server)
    assert "DeletionDone" not in _kinds(server, memory_intent) and "DeletionDone" not in _kinds(server, run_intent)

    gate = threading.Event()
    sync_client = _HangingCanonical(server.sync_client(), gate)
    async_client = _AsyncHangingCanonical(server.async_client(), gate)
    service = KurrentRecoveryService(
        memory_factory=lambda config: _storage(server, sync_client, clock=clock, config=config), store_factory=lambda: _store(server, async_client, clock=clock), config_source=_both_backends, interval=3600, clock=clock
    )
    started = time.monotonic()
    await service.start(None)
    try:
        assert time.monotonic() - started < 2.0  # never waits on the canonical side
        assert "DeletionDone" in _kinds(server, memory_intent) and "DeletionDone" in _kinds(server, run_intent)
        await asyncio.sleep(0.05)
        assert service.running  # canonical cleanup is stuck in the background, not in start()
        assert [kind for kind in _kinds(server, memory_intent) if kind.startswith("Canonical")] == []
    finally:
        gate.set()
        await service.stop()
    assert not service.running
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("kurrentdb")]


async def test_service_start_never_raises_and_is_bounded(server, monkeypatch):
    from deerflow_extension_kurrentdb import KurrentRecoveryService

    # KurrentDB unreachable: start returns within its budget and the loop keeps retrying.
    server.set_unavailable(ServiceUnavailableError("down"))
    service = KurrentRecoveryService(memory_factory=lambda config: _storage(server, config=config), store_factory=lambda: _store(server), config_source=_both_backends, interval=3600, startup_budget=1.0)
    started = time.monotonic()
    await service.start(None)
    assert time.monotonic() - started < 2.0
    assert service.running
    await service.stop()
    server.set_unavailable(None)

    # No settings: idle, with a warning.
    monkeypatch.delenv("KURRENTDB_CONNECTION_STRING")
    idle = KurrentRecoveryService(config_source=_both_backends)
    await idle.start(None)
    assert not idle.running
    await idle.stop()


async def test_service_runs_primary_recovery_periodically(server, clock):
    from deerflow_extension_kurrentdb import KurrentRecoveryService

    service = KurrentRecoveryService(memory_factory=lambda config: _storage(server, clock=clock, config=config), store_factory=lambda: _store(server, clock=clock), config_source=_both_backends, interval=0.01, clock=clock)
    await service.start(None)
    try:
        store = _store(server, clock=clock)
        await _say(store, "doomed", "r1")
        await _say(store, "kept", "r2")
        server.fail_next("set_stream_metadata", ServiceUnavailableError("crash"), stream_name=T1_PRIMARY)
        await store.delete_by_run("t1", "r1")
        (intent_id,) = _intents(server)
        for _ in range(500):  # R13: the periodic pass finishes the run-event primary side
            if "DeletionDone" in _kinds(server, intent_id):
                break
            await asyncio.sleep(0.01)
        assert "DeletionDone" in _kinds(server, intent_id)
        await store.flush_canonical()
    finally:
        await service.stop()


class _MetaDown:
    """A sync client whose memory-meta (sidecar) calls fail while ``down``."""

    def __init__(self, inner):
        self._inner, self.down = inner, True

    def __getattr__(self, name):
        target = getattr(self._inner, name)

        def call(stream_name, *args, **kwargs):
            if self.down and stream_name.startswith("deerflow.memory-meta"):
                raise ServiceUnavailableError("sidecar stream unavailable")
            return target(stream_name, *args, **kwargs)

        return call


async def test_service_recovery_uses_the_gateway_deermem_config(server):
    from datetime import UTC, datetime

    from deerflow_extension_kurrentdb import KurrentRecoveryService
    from deerflow_extension_kurrentdb.service import Backends

    from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EvictedFact, FactEvictionDecision

    # The operator keeps more eviction evidence than DeerMem's default (200 entries per agent).
    backend_config = {"storage_class": KURRENT_STORAGE_CLASS, "eviction_audit_max_entries": 250}
    gateway_config = DeerMemConfig.from_backend_config(backend_config)
    assert gateway_config.eviction_audit_max_entries != DeerMemConfig().eviction_audit_max_entries
    meta_down = _MetaDown(server.sync_client())
    meta_down.down = False
    gateway = _storage(server, meta_down, config=gateway_config)
    _create(gateway, _fact("f1", "Doomed"))
    for index in range(210):
        decision = FactEvictionDecision(kept=[], evicted=[EvictedFact(fact_id=f"old{index}", category="preference", score=0.1, components={"confidence": 0.1})], scores={}, policy="confidence")
        gateway.record_capacity_eviction(decision, max_facts=5, agent_name="other", user_id="alice", occurred_at=datetime(2026, 11, 1, tzinfo=UTC))
    assert len(gateway.get_eviction_audit(agent_name="other", user_id="alice")) == 210
    gateway.record_fact_accesses(["f1"], agent_name=AGENT, user_id="alice")  # so the deletion's sidecar boundary is a real snapshot
    meta_down.down = True  # the sidecar step fails: the deletion's primary side stays open
    gateway.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    assert gateway.flush_canonical(timeout=5)
    (intent_id,) = _intents(server)
    assert "DeletionDone" not in _kinds(server, intent_id)

    built = []

    def memory_factory(config):
        built.append(config)
        return _storage(server, config=config)

    service = KurrentRecoveryService(memory_factory=memory_factory, store_factory=lambda: _store(server), config_source=lambda: Backends(memory=backend_config, run_events=False), interval=3600)
    await service.start(None)
    await service.stop()
    assert "DeletionDone" in _kinds(server, intent_id)
    assert server._streams["deerflow.memory-meta-user.alice"].events[-1].type.endswith("MetadataSnapshot")  # the service wrote the sidecar boundary
    assert built[0].eviction_audit_max_entries == 250
    restarted = _storage(server, config=gateway_config)
    assert len(restarted.get_eviction_audit(agent_name="other", user_id="alice")) == 210  # unrelated evidence kept under the Gateway's caps


async def test_service_startup_budgets_are_separate_and_first_pass_is_full(server, clock):
    from deerflow_extension_kurrentdb import KurrentRecoveryService

    class StuckMemory:
        def __init__(self):
            self.gate = threading.Event()
            self.recoveries = 0

        def recover_deletions(self):
            self.recoveries += 1
            self.gate.wait(10)
            return []

        def run_canonical_obligations(self):
            return None

    memory = StuckMemory()
    store = _store(server, clock=clock)
    await _say(store, "doomed", "r1")
    await _say(store, "kept", "r2")
    await store.flush_canonical()
    store._canonical_chains = CapturedChains()
    server.fail_next("set_stream_metadata", ServiceUnavailableError("crash"), stream_name=T1_PRIMARY)
    await store.delete_by_run("t1", "r1")
    (intent_id,) = _intents(server)

    service = KurrentRecoveryService(memory_factory=lambda *config: memory, store_factory=lambda: _store(server, clock=clock), config_source=_both_backends, interval=3600, startup_budget=0.2, clock=clock)
    started = time.monotonic()
    await service.start(None)
    try:
        assert time.monotonic() - started < 1.0
        assert "DeletionDone" in _kinds(server, intent_id)  # run-event recovery ran although memory's timed out
        memory.gate.set()
        for _ in range(500):  # the first background pass retries the primary side (a full pass), not only canonical work
            if memory.recoveries >= 2:
                break
            await asyncio.sleep(0.01)
        assert memory.recoveries == 2
    finally:
        memory.gate.set()
        await service.stop()


async def test_service_idle_without_kurrent_backends():
    from deerflow_extension_kurrentdb import KurrentRecoveryService
    from deerflow_extension_kurrentdb.service import Backends, backends_from

    built = []
    service = KurrentRecoveryService(memory_factory=lambda config: built.append("memory"), store_factory=lambda: built.append("store"), config_source=lambda: Backends(memory=None, run_events=False))
    await service.start(None)
    assert not service.running and built == []
    await service.stop()

    # How the Gateway config is read: the memory storage class and the run-event backend name.
    assert backends_from({"storage_class": KURRENT_STORAGE_CLASS}, "kurrent") == Backends(memory={"storage_class": KURRENT_STORAGE_CLASS}, run_events=True)
    assert backends_from({"storage_class": "deerflow_extension_kurrentdb.memory.storage.KurrentdbMemoryStorage"}, "db").memory is not None
    assert backends_from({"storage_class": "file"}, "db") == Backends(memory=None, run_events=False)
    assert backends_from({}, "jsonl") == Backends(memory=None, run_events=False)
    assert backends_from({"storage_class": "no.such.module.Storage"}, None) == Backends(memory=None, run_events=False)


# --- acceptance ------------------------------------------------------------------------


async def _thread_deletion(server, storage, store):
    await _say(store, "t1 message", "r1")
    await _say(store, "t2 message", "r1", thread_id="t2")
    await store.flush_canonical()
    assert await store.delete_by_thread("t1") == 1
    assert await store.list_messages("t1") == []
    return lambda: _events(server, T1_CANONICAL) == [] and [text for _, _, text in _session(server, agent_session_stream("t2"))] == [None, "t2 message"]


async def _run_deletion(server, storage, store):
    await _say(store, "r1 first", "r1")
    await _say(store, "r2 kept", "r2")
    await _say(store, "r1 owns the max seq", "r1")
    await store.flush_canonical()
    assert await store.delete_by_run("t1", "r1") == 2
    assert [message["content"] for message in await store.list_messages("t1")] == ["r2 kept"]
    assert (await _say(store, "r1 after", "r1"))["seq"] == 4
    await store.flush_canonical()
    return lambda: [text for _, _, text in _session(server)] == [None, "r2 kept", "r1 after"]


async def _fact_delete(server, storage, store):
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"))
    assert storage.flush_canonical(timeout=5)
    storage.apply_changes({"deletes": ["f1"]}, user_id="alice", agent_name=AGENT)
    assert [fact["id"] for fact in storage.load(AGENT, user_id="alice")["facts"]] == ["f2"]
    return lambda: _facts(server) == ["Kept"]


async def _scoped_clear(server, storage, store):
    _create(storage, _fact("f1", "Doomed"))
    _create(storage, _fact("o1", "Other agent's"), agent="other")
    assert storage.flush_canonical(timeout=5)
    assert storage.save({"facts": []}, AGENT, user_id="alice")
    assert storage.load(AGENT, user_id="alice")["facts"] == []
    return lambda: _facts(server) == ["Other agent's"]


async def _whole_user_clear(server, storage, store):
    _create(storage, _fact("f1", "Doomed"))
    _create(storage, _fact("o1", "Also doomed"), agent="other")
    _create(storage, _fact("b1", "Bob's"), user_id="bob")
    assert storage.flush_canonical(timeout=5)
    storage.clear_all(user_id="alice")
    assert storage.load(AGENT, user_id="alice")["facts"] == [] and storage.load("other", user_id="alice")["facts"] == []
    return lambda: _events(server, ALICE_CANONICAL) == [] and _facts(server, BOB_CANONICAL) == ["Bob's"]


@pytest.mark.parametrize("scenario", [_thread_deletion, _run_deletion, _fact_delete, _scoped_clear, _whole_user_clear], ids=lambda scenario: scenario.__name__.strip("_"))
async def test_acceptance_primary_now_canonical_once_verified(server, clock, scenario):
    storage, store = _storage(server, clock=clock), _store(server, clock=clock)
    canonical_clean = await scenario(server, storage, store)  # asserts the primary side right after the call
    assert storage.flush_canonical(timeout=5)
    await store.flush_canonical()
    (intent_id,) = _intents(server)
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupDone"  # cleaned in the background, not yet verified
    assert canonical_clean()
    clock.advance(PAST_VERIFICATION)
    reports = [storage.run_canonical_obligations(), await store.run_canonical_obligations()]
    assert sum(report.verified for report in reports) == 1
    assert _kinds(server, intent_id)[-1] == "CanonicalCleanupVerified"
    assert canonical_clean()
    _assert_consumable(server)
    # Verified obligations are closed: another pass does nothing.
    again = [storage.run_canonical_obligations(), await store.run_canonical_obligations()]
    assert sum(report.verified + report.cleaned + report.failed for report in again) == 0


# --- pure pieces --------------------------------------------------------------------------


def test_selection_dedupes_by_identity_and_keeps_session_started():
    from deerflow_extension_kurrentdb.canonical.cleanup import identity

    started = {"deerflow.seq": 1, "deerflow.origin": 1, "deerflow.event_type": "session.start"}
    first = {"deerflow.seq": 1, "deerflow.origin": 1, "deerflow.run_id": "r1", "deerflow.event_type": "ai_message"}
    assert identity(started) != identity(first)
    assert identity({**first, "deerflow.intent_id": "x"}) == identity(first)
    fact = {"deerflow.fact_id": "f1", "deerflow.fact_revision": 1, "deerflow.agent": AGENT, "deerflow.origin": 1}
    assert identity(fact) == identity({**fact, "deerflow.intent_id": "x"}) != identity({**fact, "deerflow.origin": 5})
    assert identity({}) is None


def test_canonical_stream_of_intents():
    from deerflow_extension_kurrentdb._naming import memory_stream
    from deerflow_extension_kurrentdb.canonical.cleanup import canonical_stream_of
    from deerflow_extension_kurrentdb.deletions import Intent

    for user_id in ("alice", "a-b/c d", "ünï", "global", "%41"):
        intent = Intent.new("clear_all", {"op": "clear_all"}, memory_stream(user_id), 0)
        assert canonical_stream_of(intent) == agent_memory_stream("deerflow", user_id)
    assert canonical_stream_of(Intent.new("clear_all", {"op": "clear_all"}, memory_stream(None), 0)) is None
    assert canonical_stream_of(Intent.new("delete_thread", {"thread_id": "t/1"}, "deerflow.run-events-t%2F1", 0)) == agent_session_stream("t/1")
