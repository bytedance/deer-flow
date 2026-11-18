"""KurrentRunEventStore on the current RunEventStore contract: writes, reads, lookups, outcome classes, isolation."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from pathlib import Path

import pytest
import test_run_event_store as core
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import DeadlineExceededError, ServiceUnavailableError

from deerflow.runtime.events.message_identity import message_identity
from deerflow.runtime.events.message_seq import stamp_messages_with_seq
from deerflow.runtime.events.store.base import RunEventLifecycleRejected, RunEventStore, RunEventStoreNotCommittedError
from deerflow.runtime.user_context import reset_current_user, set_current_user

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0
T1 = "deerflow.run-events-t1"
T2 = "deerflow.run-events-t2"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://fake:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))


@pytest.fixture
def server() -> FakeKurrentDB:
    return FakeKurrentDB()


def _store(server: FakeKurrentDB, client=None):
    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStore

    client = client if client is not None else server.async_client()

    async def factory():
        return client

    return KurrentRunEventStore({}, client_factory=factory)


@pytest.fixture
def store(server):
    return _store(server)


def _ev(thread_id="t1", run_id="r1", event_type="ai_message", category="message", **extra) -> dict:
    return {"thread_id": thread_id, "run_id": run_id, "event_type": event_type, "category": category, **extra}


def _raw(server: FakeKurrentDB, stream: str = T1):
    return list(server.sync_client().get_stream(stream))


def _raw_types(server: FakeKurrentDB, stream: str = T1) -> list[str]:
    return [event.type for event in _raw(server, stream)]


def _foreign_event(seq: int, run_id: str = "foreign", thread_id: str = "t1") -> NewEvent:
    from deerflow_extension_kurrentdb.run_events import encode_record

    record = {"thread_id": thread_id, "run_id": run_id, "event_type": "ai_message", "category": "message", "content": "x", "metadata": {}, "seq": seq, "created_at": "2026-11-18T00:00:00+00:00"}
    return encode_record(record, user_id=None)


# --- mirrored core contract suites (ruling R5: core files stay extension-free) --


class TestKurrentPutAndSeq(core.TestPutAndSeq):
    pass


class TestKurrentListMessages(core.TestListMessages):
    pass


class TestKurrentListEvents(core.TestListEvents):
    pass


class TestKurrentListMessagesByRun(core.TestListMessagesByRun):
    # Builds memory/jsonl/db stores itself; mirrored below for this backend.
    test_explicit_user_id_follows_list_messages_semantics = None


class TestKurrentCountMessages(core.TestCountMessages):
    pass


class TestKurrentPutBatch(core.TestPutBatch):
    pass


class TestKurrentEdgeCases(core.TestEdgeCases):
    pass


class TestKurrentGetMessageSeqs(core.TestGetMessageSeqs):
    # Reach into the memory store's private projections or build other backends.
    test_the_scan_stops_once_every_wanted_identity_is_resolved = None
    test_jsonl_store_resolves_identities = None
    test_db_store_resolves_identities = None
    test_db_store_only_decodes_rows_that_can_match = None
    test_db_store_resolves_an_id_the_sql_prefilter_cannot_express = None


class TestKurrentStampMessagesWithSeq(core.TestStampMessagesWithSeq):
    pass


@pytest.mark.anyio
async def test_find_latest_ai_message_run_ids_contract(store, server):
    await core._assert_find_latest_ai_message_run_ids_contract(store, allow_empty_run_id=True)


@pytest.mark.anyio
async def test_find_latest_ai_message_run_ids_empty_input_does_no_storage_work(store, server):
    assert await store.find_latest_ai_message_run_ids("t1", set()) == {}
    assert await store.find_latest_ai_message_run_ids("t1", {"", None}) == {}
    assert server.calls == []


@pytest.mark.anyio
async def test_explicit_user_id_follows_list_messages_semantics(store, server):
    """Mirror of test_run_event_store.py's backend-parametrized case: not user-scoped, like memory/JSONL."""
    token = set_current_user(type("Owner", (), {"id": "feishu:owner"})())
    try:
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
    finally:
        reset_current_user(token)

    assert len(await store.list_messages_by_run("t1", "r1", user_id="feishu:owner")) == 1
    assert len(await store.list_messages_by_run("t1", "r1", user_id=None)) == 1
    assert len(await store.list_messages_by_run("t1", "r1", user_id="someone-else")) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("second_run", ["run-a", "run-b"])
async def test_reused_provider_ids_keep_distinct_seqs(store, second_run):
    """Mirror of test_tool_result_identity.py's backend-parametrized case."""
    first = {"type": "tool", "id": "result-first", "tool_call_id": "call_0", "content": "first"}
    second = {**first, "id": "result-second", "content": "second"}
    for run_id, message in [("run-a", first), (second_run, second), (second_run, {**second, "content": "replayed"})]:
        await store.put(thread_id="thread", run_id=run_id, event_type="llm.tool.result", category="message", content=message)
    stamped = await stamp_messages_with_seq(store, "thread", [first, second])
    assert [message["additional_kwargs"]["deerflow_seq"] for message in stamped] == [1, 2]
    assert [message_identity(message) for message in stamped] == ["message:result-first", "message:result-second"]


# --- construction and factory --------------------------------------------------


def test_make_store_builds_without_connecting(monkeypatch):
    from deerflow_extension_kurrentdb import run_events

    store = run_events.make_store({"backend": "kurrent"})
    assert isinstance(store, run_events.KurrentRunEventStore)
    assert isinstance(store, RunEventStore)

    monkeypatch.delenv("KURRENTDB_CONNECTION_STRING")
    with pytest.raises(ValueError, match="KURRENTDB_CONNECTION_STRING"):
        run_events.make_store({})


def test_seq_next_seq():
    from deerflow_extension_kurrentdb.run_events.seq import next_seq, seq_high_water

    assert next_seq(0, []) == 1
    assert next_seq(0, [1, 2, 3]) == 4
    assert next_seq(10, [3, 4]) == 11
    assert next_seq(5, [3, 9]) == 10
    assert next_seq(7, iter(())) == 8
    assert seq_high_water(0, []) == 0
    assert seq_high_water(10, [3, 4]) == 10
    assert seq_high_water(5, [3, 9]) == 9


# --- put / seq -----------------------------------------------------------------


@pytest.mark.anyio
async def test_put_assigns_strictly_increasing_seq(store, server):
    seqs = [(await store.put(**_ev(run_id=f"r{index % 3}")))["seq"] for index in range(10)]
    assert seqs == list(range(1, 11))
    # Concurrent writers in one process are serialized by the per-thread lock.
    results = await asyncio.gather(*(store.put(**_ev(run_id="burst")) for _ in range(20)))
    assert sorted(record["seq"] for record in results) == list(range(11, 31))
    # A cold instance continues from the stream, not from zero.
    assert (await _store(server).put(**_ev()))["seq"] == 31
    # Every event stores its seq in its data.
    assert [json.loads(event.data)["seq"] for event in _raw(server)] == list(range(1, 32))
    assert set(_raw_types(server)) == {"deerflow.run-events.RunEvent"}


@pytest.mark.anyio
async def test_put_returns_complete_record(store):
    record = await store.put(thread_id="t1", run_id="r1", event_type="llm.ai.response", category="message", content={"type": "ai", "id": "m1"}, metadata={"caller": "lead"}, created_at="2026-11-18T01:02:03+00:00")
    assert record == {
        "thread_id": "t1",
        "run_id": "r1",
        "event_type": "llm.ai.response",
        "category": "message",
        "content": {"type": "ai", "id": "m1"},
        "metadata": {"caller": "lead"},
        "seq": 1,
        "created_at": "2026-11-18T01:02:03+00:00",
    }
    assert (await store.list_events("t1", "r1")) == [record]
    default = await store.put(**_ev())
    assert default["content"] == "" and default["metadata"] == {} and default["created_at"]


@pytest.mark.anyio
async def test_seq_survives_interleaved_writer_in_another_process(server):
    first, second = _store(server), _store(server)
    assert (await first.put(**_ev(content="a")))["seq"] == 1
    assert (await second.put(**_ev(content="b")))["seq"] == 2
    # ``first`` still believes the head is where it left it: the append conflicts and is redone above ``second``'s seq.
    assert (await first.put(**_ev(content="c")))["seq"] == 3
    batch = await second.put_batch([_ev(content="d"), _ev(content="e")])
    assert [record["seq"] for record in batch] == [4, 5]
    assert [(m["seq"], m["content"]) for m in await first.list_messages("t1")] == [(1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")]


@pytest.mark.anyio
async def test_conflicts_that_never_settle_raise_not_committed(server, monkeypatch):
    from deerflow_extension_kurrentdb.run_events import store as store_module

    class _Racing:
        """Another process appends right before every append of this store."""

        def __init__(self, client):
            self._client = client
            self.foreign = 0

        def __getattr__(self, name):
            return getattr(self._client, name)

        async def append_to_stream(self, stream_name, **kwargs):
            self.foreign += 1
            server.sync_client().append_to_stream(stream_name, events=[_foreign_event(1000 + self.foreign)], current_version=StreamState.ANY)
            return await self._client.append_to_stream(stream_name, **kwargs)

    monkeypatch.setattr(store_module, "MAX_APPEND_ATTEMPTS", 3)
    racing = _Racing(server.async_client())
    store = _store(server, racing)
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch([_ev()])
    assert racing.foreign == 3
    assert {json.loads(event.data)["run_id"] for event in _raw(server)} == {"foreign"}


# --- outcome classification ------------------------------------------------------


@pytest.mark.anyio
async def test_lost_ack_after_commit_is_settled_as_committed(store, server):
    server.fail_next("append_to_stream", DeadlineExceededError("ack lost"), after_commit=True)
    records = await store.put_batch([_ev(content="a"), _ev(content="b")])
    assert [r["seq"] for r in records] == [1, 2]
    assert _raw_types(server) == ["deerflow.run-events.RunEvent"] * 2  # the rejected fence left nothing
    assert [m["content"] for m in await store.list_messages("t1")] == ["a", "b"]
    assert (await store.put(**_ev(content="c")))["seq"] == 3


@pytest.mark.anyio
async def test_put_batch_all_groups_rejected_raises_not_committed(store, server):
    # Rejected before reaching storage: the fence lands, so the batch never committed and never can.
    server.fail_next("append_to_stream", ServiceUnavailableError("down"))
    batch = [_ev("t1", content="a"), _ev("t2", content="b")]
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch(batch)
    assert await store.list_messages("t1") == []
    assert await store.list_messages("t2") == []
    # RunJournal retries a not-committed batch as is; it lands exactly once.
    records = await store.put_batch(batch)
    assert [(r["thread_id"], r["seq"]) for r in records] == [("t1", 1), ("t2", 1)]
    assert [m["content"] for m in await store.list_messages("t1")] == ["a"]

    # A client that cannot even be obtained never sent anything either.
    async def broken_factory():
        raise ServiceUnavailableError("cannot connect")

    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStore

    with pytest.raises(RunEventStoreNotCommittedError):
        await KurrentRunEventStore({}, client_factory=broken_factory).put_batch(batch)


@pytest.mark.anyio
async def test_put_batch_multi_thread_partial_commit_is_plain_exception(store, server):
    server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=T2)
    with pytest.raises(Exception) as caught:
        await store.put_batch([_ev("t1", content="a"), _ev("t2", content="b"), _ev("t1", content="c")])
    assert not isinstance(caught.value, RunEventStoreNotCommittedError)
    # The first group committed; the second was fence-settled as not committed.
    assert [m["content"] for m in await store.list_messages("t1")] == ["a", "c"]
    assert await store.list_messages("t2") == []
    assert _raw_types(server, T2) == ["deerflow.Fence"]


@pytest.mark.anyio
async def test_unsettled_outcome_is_plain_exception(store, server):
    # The append's ack is lost and the fence itself fails: nobody knows whether it committed.
    server.fail_next("append_to_stream", DeadlineExceededError("ack lost"))
    server.fail_next("append_to_stream", DeadlineExceededError("fence lost"))
    with pytest.raises(Exception) as caught:
        await store.put_batch([_ev()])
    assert not isinstance(caught.value, RunEventStoreNotCommittedError)
    # Nothing was appended, so the next write still assigns seq 1 and reads stay clean.
    assert (await store.put(**_ev()))["seq"] == 1


@pytest.mark.anyio
async def test_delayed_commit_racing_the_fence_never_duplicates(store, server):
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("slow"))
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch([_ev(content="a")])
    pending.release()
    assert pending.committed is False  # the fence took the position, so the late commit is rejected
    await store.put_batch([_ev(content="a")])
    assert [m["content"] for m in await store.list_messages("t1")] == ["a"]


@pytest.mark.anyio
async def test_put_raises_on_failures_like_put_batch(store, server):
    server.fail_next("append_to_stream", ServiceUnavailableError("down"))
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put(**_ev())
    assert await store.count_messages("t1") == 0


@pytest.mark.anyio
async def test_put_batch_rejects_events_missing_required_keys_before_writing(store, server):
    with pytest.raises(ValueError, match="event_type"):
        await store.put_batch([_ev(), {"thread_id": "t1", "run_id": "r1", "category": "message"}])
    assert server.calls_to("append_to_stream") == []


@pytest.mark.anyio
async def test_put_batch_groups_threads_and_keeps_input_order(store, server):
    assert await store.put_batch([]) == []
    records = await store.put_batch([_ev("t1", content="a"), _ev("t2", content="b"), _ev("t1", content="c")])
    assert [(r["thread_id"], r["content"], r["seq"]) for r in records] == [("t1", "a", 1), ("t2", "b", 1), ("t1", "c", 2)]
    # One append per thread group.
    assert [call.stream_name for call in server.calls_to("append_to_stream")] == [T1, T2]


# --- isolation -------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_batch_isolation_no_caller_mutation(store):
    events = [_ev(content={"type": "ai", "id": "m1", "parts": [{"text": "hi"}]}, metadata={"tags": ["a"]})]
    snapshot = copy.deepcopy(events)
    records = await store.put_batch(events)
    assert events == snapshot  # no stamped keys, nothing rewritten

    events[0]["content"]["parts"][0]["text"] = "mutated input"
    events[0]["metadata"]["tags"].append("mutated")
    records[0]["content"]["parts"][0]["text"] = "mutated record"
    records[0]["metadata"]["tags"].append("mutated")
    first_read = await store.list_messages("t1")
    assert first_read[0]["content"]["parts"][0]["text"] == "hi"
    assert first_read[0]["metadata"] == {"tags": ["a"]}
    first_read[0]["content"]["parts"].clear()
    assert (await store.list_messages("t1"))[0]["content"]["parts"] == [{"text": "hi"}]

    content = {"type": "ai", "id": "m2"}
    record = await store.put(**_ev(content=content))
    content["id"] = "changed"
    record["content"]["id"] = "changed"
    assert (await store.list_events("t1", "r1"))[-1]["content"]["id"] == "m2"

    existing, created = await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle", content={"a": [1]}))
    existing["content"]["a"].append(2)
    again, created_again = await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle"))
    assert (created, created_again) == (True, False)
    assert again["content"] == {"a": [1]}


# --- put_if_absent -----------------------------------------------------------------


@pytest.mark.anyio
async def test_put_if_absent_idempotent(store, server):
    first, created = await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle", content="done"))
    second, created_again = await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle", content="other"))
    assert (created, created_again) == (True, False)
    assert second == first
    # Another instance (cold, same stream) sees the receipt too.
    third, created_third = await _store(server).put_if_absent(**_ev(event_type="run.end", category="lifecycle"))
    assert (created_third, third) == (False, first)
    # Other runs and event types are independent.
    assert (await store.put_if_absent(**_ev(run_id="r2", event_type="run.end", category="lifecycle")))[1] is True
    assert (await store.put_if_absent(**_ev(event_type="run.error", category="lifecycle")))[1] is True
    assert len(_raw(server)) == 3


@pytest.mark.anyio
async def test_put_if_absent_sees_another_process_receipt(server):
    first, second = _store(server), _store(server)
    await first.put(**_ev())  # warms ``first``'s head
    receipt, created = await second.put_if_absent(**_ev(event_type="run.end", category="lifecycle", content="theirs"))
    assert created is True
    mine, created_mine = await first.put_if_absent(**_ev(event_type="run.end", category="lifecycle", content="mine"))
    assert (created_mine, mine) == (False, receipt)


@pytest.mark.anyio
async def test_put_if_absent_with_guard_rejected(store, server):
    observed = []

    async def guard():
        observed.append(store._lock_for("t1").locked())
        return False

    with pytest.raises(RunEventLifecycleRejected):
        await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle"), lifecycle_guard=guard)
    assert observed == [True]  # evaluated inside the per-thread mutation fence
    assert server.calls_to("append_to_stream") == []

    async def admits():
        return True

    assert (await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle"), lifecycle_guard=admits))[1] is True


# --- reads ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_messages_both_cursors_window(store):
    for index in range(10):
        await store.put(**_ev(content=f"m{index + 1}"))
        await store.put(**_ev(event_type="llm_end", category="trace"))
    message_seqs = [m["seq"] for m in await store.list_messages("t1", limit=100)]
    assert message_seqs == list(range(1, 20, 2))
    window = await store.list_messages("t1", after_seq=4, before_seq=15, limit=3)
    assert [m["seq"] for m in window] == [5, 7, 9]
    assert [m["seq"] for m in await store.list_messages("t1", after_seq=4, before_seq=15, limit=50)] == [5, 7, 9, 11, 13]
    assert [m["seq"] for m in await store.list_messages("t1", before_seq=15, limit=2)] == [11, 13]
    assert [m["seq"] for m in await store.list_messages("t1", after_seq=15, limit=50)] == [17, 19]
    assert [m["seq"] for m in await store.list_messages("t1", limit=3)] == [15, 17, 19]
    assert await store.list_messages("t1", limit=0) == []
    by_run = await store.list_messages_by_run("t1", "r1", after_seq=4, before_seq=15, limit=3)
    assert [m["seq"] for m in by_run] == [5, 7, 9]


@pytest.mark.anyio
async def test_list_events_task_id_and_after_seq(store):
    await store.put(**_ev(event_type="task.start", category="trace", metadata={"task_id": "a"}))
    await store.put(**_ev(event_type="task.step", category="trace", metadata={"task_id": "b"}))
    await store.put(**_ev(event_type="task.step", category="trace", metadata={"task_id": "a"}))
    await store.put(**_ev(run_id="r2", event_type="task.step", category="trace", metadata={"task_id": "a"}))
    await store.put(**_ev(event_type="task.end", category="trace", metadata={"task_id": "a"}))
    assert [e["seq"] for e in await store.list_events("t1", "r1", task_id="a")] == [1, 3, 5]
    assert [e["seq"] for e in await store.list_events("t1", "r1", task_id="a", after_seq=1)] == [3, 5]
    assert [e["seq"] for e in await store.list_events("t1", "r1", task_id="a", after_seq=1, limit=1)] == [3]
    assert [e["seq"] for e in await store.list_events("t1", "r1", event_types=["task.step"], task_id="a")] == [3]
    assert [e["seq"] for e in await store.list_events("t1", "r1", after_seq=3)] == [5]


@pytest.mark.anyio
async def test_get_last_visible_ai_seq_by_run_skips_middleware(store):
    await store.put(**_ev(event_type="llm.ai.response", content={"type": "ai"}))
    await store.put(**_ev(event_type="ai_message", content={"type": "ai"}))
    await store.put(**_ev(event_type="llm.ai.response", metadata={"caller": "middleware:title"}))
    await store.put(**_ev(event_type="llm.tool.result"))
    await store.put(**_ev(run_id="r2", event_type="llm.ai.response", metadata={"caller": "middleware:summary"}))
    await store.put(**_ev(run_id="r3", event_type="llm.ai.response", category="trace"))
    assert await store.get_last_visible_ai_seq_by_run("t1", {"r1", "r2", "r3", "missing"}) == {"r1": 2}
    assert await store.get_last_visible_ai_seq_by_run("empty", {"r1"}) == {}


@pytest.mark.anyio
async def test_get_message_seqs_earliest_wins(store):
    await store.put(**_ev(content={"type": "ai", "id": "a", "content": "v1"}))
    await store.put(**_ev(event_type="llm_end", category="trace", content={"type": "ai", "id": "b"}))
    await store.put(**_ev(run_id="r2", content={"type": "ai", "id": "a", "content": "v2"}))
    await store.put(**_ev(content={"type": "ai", "id": "b"}))
    assert await store.get_message_seqs("t1", ["message:a", "message:b", "message:missing"]) == {"message:a": 1, "message:b": 4}
    assert await store.get_message_seqs("t1", []) == {}


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_user_id_accepted_ignored_for_isolation_and_recorded_in_metadata(store, server):
    await store.put_batch([_ev(content="explicit", user_id="alice"), _ev(content="unowned", user_id=None)])
    token = set_current_user(type("Owner", (), {"id": "ctx-user"})())
    try:
        await store.put(**_ev(content="context"))
        await store.put_batch([_ev(content="batch-context")])
    finally:
        reset_current_user(token)
    await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle"), user_id="bob")
    await store.put(**_ev(content="anonymous"))

    owners = [json.loads(event.metadata)["user_id"] for event in _raw(server)]
    assert owners == ["alice", None, "ctx-user", "ctx-user", "bob", None]
    records = await store.list_messages("t1", user_id="someone-else")
    assert [m["content"] for m in records] == ["explicit", "unowned", "context", "batch-context", "anonymous"]
    assert all("user_id" not in m for m in records)  # envelope only, like memory/JSONL
    assert len(await store.list_events("t1", "r1", user_id="nobody")) == 6
    assert await store.get_message_seqs("t1", [], user_id="x") == {}
    assert await store.get_last_visible_ai_seq_by_run("t1", {"r1"}, user_id="x") == {"r1": 6}


async def _large_thread(store, server) -> int:
    """seq 1 is an old AI target, then 3 000 noise events, then the newest AI message ``other``."""
    await store.put(**_ev(run_id="old", event_type="llm.ai.response", content={"type": "ai", "id": "target"}))
    for chunk in range(3):
        await store.put_batch([_ev(run_id="noise", event_type="llm.ai.response", category="trace" if index % 2 else "message", content={"type": "ai", "id": f"noise-{chunk}-{index}"}) for index in range(1000)])
    await store.put(**_ev(run_id="new", event_type="llm.ai.response", content={"type": "ai", "id": "other"}))
    server.calls.clear()
    server.read_responses.clear()
    return 3002


def _one_streaming_read(server) -> list[int]:
    reads = server.calls_to("read_stream")
    assert len(server.calls) == len(reads) == 1
    assert reads[0].kwargs["backwards"] is True and reads[0].kwargs["timeout"] == TIMEOUT
    assert len(server.read_responses) == 1
    return server.read_responses[0].yielded


@pytest.mark.anyio
async def test_large_thread_lookup_single_read(store, server):
    total = await _large_thread(store, server)
    assert await store.find_latest_ai_message_run_ids("t1", {"other"}) == {"other": "new"}
    assert _one_streaming_read(server) == [total - 1]  # stops at the newest match, the oldest events are never sent

    server.calls.clear()
    server.read_responses.clear()
    # An exhaustive lookup (a missing id) is still one read, down to the start of the live stream.
    assert await store.find_latest_ai_message_run_ids("t1", {"target", "other", "missing"}) == {"target": "old", "other": "new"}
    assert len(_one_streaming_read(server)) == total


@pytest.mark.anyio
async def test_large_thread_tail_reads_stop_early(store, server):
    total = await _large_thread(store, server)
    page = await store.list_messages("t1", limit=5)
    assert [m["seq"] for m in page] == [total - 8, total - 6, total - 4, total - 2, total]
    assert min(_one_streaming_read(server)) >= total - 9

    server.calls.clear()
    server.read_responses.clear()
    page = await store.list_messages("t1", after_seq=total - 4, limit=50)
    assert [m["seq"] for m in page] == [total - 2, total]
    assert min(_one_streaming_read(server)) >= total - 5

    server.calls.clear()
    server.read_responses.clear()
    assert await store.get_last_visible_ai_seq_by_run("t1", {"new"}) == {"new": total}
    assert _one_streaming_read(server) == [total - 1]


@pytest.mark.anyio
async def test_large_thread_next_seq_lookup_reads_only_the_newest_event(store, server):
    total = await _large_thread(store, server)
    cold = _store(server)
    server.calls.clear()
    server.read_responses.clear()
    assert (await cold.put(**_ev()))["seq"] == total + 1
    assert [call.method for call in server.calls] == ["read_stream", "append_to_stream"]
    assert server.read_responses[0].yielded == [total - 1]


@pytest.mark.anyio
async def test_reads_of_a_missing_stream_are_empty_and_transport_errors_raise(store, server):
    assert await store.list_messages("nope") == []
    assert await store.list_events("nope", "r1") == []
    assert await store.list_messages_by_run("nope", "r1") == []
    assert await store.count_messages("nope") == 0
    assert await store.get_message_seqs("nope", ["message:a"]) == {}
    assert await store.find_latest_ai_message_run_ids("nope", {"a"}) == {}
    await store.put(**_ev())
    server.set_unavailable(ServiceUnavailableError("down"))
    for read in (store.list_messages("t1"), store.count_messages("t1"), store.list_events("t1", "r1"), store.find_latest_ai_message_run_ids("t1", {"a"})):
        with pytest.raises(ServiceUnavailableError):
            await read


@pytest.mark.anyio
async def test_every_client_call_passes_the_timeout(store, server):
    await store.put(**_ev())
    await store.put_batch([_ev("t2"), _ev()])
    await store.put_if_absent(**_ev(event_type="run.end", category="lifecycle"))
    server.fail_next("append_to_stream", DeadlineExceededError("ack lost"), after_commit=True)
    await store.put(**_ev())
    for read in (store.list_messages("t1"), store.list_events("t1", "r1"), store.list_messages_by_run("t1", "r1"), store.count_messages("t1")):
        await read
    await store.get_message_seqs("t1", ["message:a"])
    await store.get_last_visible_ai_seq_by_run("t1", {"r1"})
    await store.find_latest_ai_message_run_ids("t1", {"a"})
    assert server.calls
    assert {call.kwargs.get("timeout") for call in server.calls} == {TIMEOUT}


# --- boundaries, fences and corruption -------------------------------------------------


def _boundary(event_type: str, seq_high_water: int) -> NewEvent:
    return NewEvent(id=uuid.uuid4(), type=event_type, data=json.dumps({"seq_high_water": seq_high_water, "intent_id": "i-1"}).encode())


@pytest.mark.anyio
async def test_reads_fold_from_the_newest_boundary(store, server):
    from deerflow_extension_kurrentdb.run_events import RUNS_COMPACTED_EVENT_TYPE, THREAD_CLEARED_EVENT_TYPE, encode_record

    for index in range(4):
        await store.put(**_ev(run_id=f"r{index}", content=f"m{index + 1}"))
    raw = server.sync_client()
    survivor = _raw(server)[1]  # r1, seq 2
    # delete_by_run(r3) as Task 11 writes it: the boundary, then copies of every survivor, in one append.
    copies = [encode_record(json.loads(event.data), user_id=None, survivor=True) for event in _raw(server) if json.loads(event.data)["run_id"] != "r3"]
    raw.append_to_stream(T1, events=[_boundary(RUNS_COMPACTED_EVENT_TYPE, 4), *copies], current_version=3)
    assert [m["content"] for m in await _store(server).list_messages("t1")] == ["m1", "m2", "m3"]
    assert json.loads(survivor.data)["seq"] == 2
    # A new event gets a seq above the deleted run's, even though no surviving event holds it.
    assert (await _store(server).put(**_ev(content="m5")))["seq"] == 5
    assert (await store.put(**_ev(content="m6")))["seq"] == 6  # the warm instance re-reads after its conflict

    head = raw.get_current_version(T1)
    raw.append_to_stream(T1, events=[_boundary(THREAD_CLEARED_EVENT_TYPE, 6)], current_version=head)
    for reader in (store, _store(server)):
        assert await reader.list_messages("t1") == []
        assert await reader.count_messages("t1") == 0
        assert await reader.find_latest_ai_message_run_ids("t1", {"x"}) == {}
    assert (await _store(server).put(**_ev(content="after")))["seq"] == 7
    assert [m["content"] for m in await store.list_messages("t1")] == ["after"]


@pytest.mark.anyio
async def test_fence_events_are_ignored_by_reads_and_seq(store, server):
    from deerflow_extension_kurrentdb._fence import FENCE_EVENT_TYPE

    await store.put(**_ev(content="a"))
    raw = server.sync_client()
    raw.append_to_stream(T1, events=[NewEvent(id=uuid.uuid4(), type=FENCE_EVENT_TYPE, data=b"{}")], current_version=0)
    assert (await _store(server).put(**_ev(content="b")))["seq"] == 2
    assert [m["content"] for m in await store.list_messages("t1")] == ["a", "b"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "event",
    [
        NewEvent(id=uuid.uuid4(), type="deerflow.run-events.RunEvent", data=b"not json"),
        NewEvent(id=uuid.uuid4(), type="deerflow.run-events.RunEvent", data=b'{"thread_id": "t1"}'),
        NewEvent(id=uuid.uuid4(), type="deerflow.run-events.RunEvent", data=b'["a list"]'),
        NewEvent(id=uuid.uuid4(), type="some.unknown.Type", data=b"{}"),
        NewEvent(id=uuid.uuid4(), type="deerflow.run-events.ThreadCleared", data=b'{"seq_high_water": "x"}'),
    ],
    ids=["undecodable", "missing-fields", "not-an-object", "unknown-type", "bad-boundary"],
)
async def test_undecodable_stored_data_is_corruption(store, server, event):
    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStoreCorruption

    server.sync_client().append_to_stream(T1, events=[event], current_version=StreamState.NO_STREAM)
    with pytest.raises(KurrentRunEventStoreCorruption):
        await store.list_messages("t1")
    with pytest.raises(RunEventStoreNotCommittedError):
        await store.put_batch([_ev()])


# --- deletions (Task 11): boundaries, survivors, seq high water --------------------

INDEX = "deerflow.kurrent-deletions"


class TestKurrentDelete(core.TestDelete):
    # Builds memory/jsonl/db stores itself; mirrored below for this backend (ruling R5).
    test_delete_by_run_preserves_seq_watermark = None


def _index(server: FakeKurrentDB) -> list[str]:
    try:
        recorded = server.sync_client().get_stream(INDEX)
    except Exception:
        return []
    return [event.type.rsplit(".", 1)[-1] for event in recorded]


def _tb(server: FakeKurrentDB, stream: str = T1) -> int:
    return server.sync_client().get_stream_metadata(stream)[0].get("$tb", 0)


def _all_events(server: FakeKurrentDB, stream: str = T1):
    """Every recorded event, including those below ``$tb`` (the fake's raw history)."""
    return list(server._streams[stream].events)


def _short(event_type: str) -> str:
    return event_type.rsplit(".", 1)[-1]


async def _view(reader, thread_id: str = "t1") -> dict:
    messages = await reader.list_messages(thread_id)
    return {
        "messages": [(m["seq"], m["run_id"], m["content"]) for m in messages],
        "count": await reader.count_messages(thread_id),
        "r1_events": [e["seq"] for e in await reader.list_events(thread_id, "r1")],
        "r2_events": [e["seq"] for e in await reader.list_events(thread_id, "r2")],
    }


@pytest.mark.anyio
async def test_delete_by_run_preserves_seq_watermark(store, server):
    """Mirror of test_run_event_store.py:496 for this backend."""
    r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="one")
    r2 = await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message", content="two")
    assert [r1["seq"], r2["seq"]] == [1, 2]
    assert await store.delete_by_run("t1", "r2", user_id=None) == 1
    r3 = await store.put(thread_id="t1", run_id="r3", event_type="human_message", category="message", content="three")
    assert r3["seq"] > r2["seq"]
    messages = await store.list_messages("t1", limit=50, after_seq=r2["seq"], user_id=None)
    assert [message["seq"] for message in messages] == [r3["seq"]]


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_delete_run_keeps_survivors_and_seq_before_and_after_repair_and_restart(store, server):
    alice = set_current_user(type("Owner", (), {"id": "alice"})())
    try:
        await store.put(**_ev(run_id="r1", content="a", metadata={"k": 1}))
    finally:
        reset_current_user(alice)
    await store.put(**_ev(run_id="r2", content="b"))
    await store.put(**_ev(run_id="r1", content="c", category="trace", event_type="llm_end"))
    await store.put(**_ev(run_id="r2", content="d"))
    expected = {"messages": [(1, "r1", "a")], "count": 1, "r1_events": [1, 3], "r2_events": []}

    # The boundary commits but raising $tb fails: the deletion succeeds and stays open.
    server.fail_next("get_stream_metadata", ServiceUnavailableError("metadata down"), stream_name=T1)
    assert await store.delete_by_run("t1", "r2") == 2
    assert _index(server) == ["DeletionIntended"]
    assert _tb(server) == 0
    assert [_short(e.type) for e in _raw(server)][4:] == ["RunsCompacted", "RunEvent", "RunEvent"]
    for reader in (store, _store(server)):  # before the truncation repair
        assert await _view(reader) == expected

    # Repair: recovery raises $tb to the boundary itself, so it stays readable.
    assert await _store(server).recover_deletions() == []
    assert _index(server) == ["DeletionIntended", "DeletionDone"]
    assert _tb(server) == 4
    assert [_short(e.type) for e in _raw(server)] == ["RunsCompacted", "RunEvent", "RunEvent"]
    boundary = json.loads(_raw(server)[0].data)
    assert boundary["seq_high_water"] == 4 and boundary["run_id"] == "r2" and uuid.UUID(boundary["intent_id"])
    for reader in (store, _store(server)):  # after it
        assert await _view(reader) == expected

    # Survivor copies keep their seq, data and metadata (owner included), marked as survivors.
    copies = _raw(server)[1:]
    assert [json.loads(e.data)["seq"] for e in copies] == [1, 3]
    assert [json.loads(e.metadata) for e in copies] == [{"user_id": "alice", "survivor": True}, {"user_id": None, "survivor": True}]
    assert json.loads(copies[0].data)["metadata"] == {"k": 1}

    # Cold restart: a new client, a new store.
    restarted = _store(server, server.async_client())
    assert await _view(restarted) == expected
    assert (await restarted.put(**_ev(run_id="r3", content="e")))["seq"] == 5
    assert [m["seq"] for m in await restarted.list_messages("t1")] == [1, 5]


@pytest.mark.anyio
async def test_delete_run_owning_max_seq_then_restart_write_gets_higher_seq(store, server):
    for run_id in ("r1", "r1", "r2", "r2"):
        await store.put(**_ev(run_id=run_id))
    assert await store.delete_by_run("t1", "r2") == 2
    assert [m["seq"] for m in await store.list_messages("t1")] == [1, 2]

    restarted = _store(server, server.async_client())
    assert (await restarted.put(**_ev(run_id="r3")))["seq"] == 5
    assert [m["seq"] for m in await restarted.list_messages("t1", after_seq=4)] == [5]
    # The warm instance's cache is stale: it conflicts, re-reads and continues above.
    assert (await store.put(**_ev(run_id="r3")))["seq"] == 6

    # Deleting every remaining run leaves a boundary with no survivors; the high water holds.
    assert await store.delete_by_run("t1", "r1") == 2
    assert await store.delete_by_run("t1", "r3") == 2
    assert await store.list_messages("t1") == []
    assert (await _store(server).put(**_ev()))["seq"] == 7
    assert _index(server) == ["DeletionIntended", "DeletionDone"] * 3


@pytest.mark.anyio
async def test_delete_thread_then_write_gets_higher_seq(store, server):
    await store.put(**_ev(run_id="r1"))
    await store.put(**_ev(run_id="r2"))
    await store.put(**_ev(run_id="r2", category="trace", event_type="llm_end"))
    # Delete the run that owns the top seq first: the thread boundary still carries it.
    assert await store.delete_by_run("t1", "r2") == 2
    assert await store.delete_by_thread("t1") == 1  # the survivor copy

    raw = _raw(server)
    assert [_short(e.type) for e in raw] == ["ThreadCleared"]
    assert json.loads(raw[0].data)["seq_high_water"] == 3
    assert _tb(server) == raw[0].stream_position
    for reader in (store, _store(server)):
        assert await reader.list_messages("t1") == []
        assert await reader.count_messages("t1") == 0
        assert await reader.list_events("t1", "r1") == []
        assert await reader.find_latest_ai_message_run_ids("t1", {"x"}) == {}

    restarted = _store(server, server.async_client())
    assert (await restarted.put(**_ev(run_id="r3", content="after")))["seq"] == 4
    assert (await store.put(**_ev(run_id="r3")))["seq"] == 5
    assert [m["content"] for m in await restarted.list_messages("t1")] == ["after", ""]
    assert _index(server) == ["DeletionIntended", "DeletionDone"] * 2


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_delete_returns_counts_per_contract(store, server):
    # No stream yet: a cheap no-op that reads once and never touches the index.
    assert await store.delete_by_thread("t1") == 0
    assert await store.delete_by_run("t1", "r1") == 0
    assert {call.method for call in server.calls} == {"read_stream"}
    assert _index(server) == []

    owners = [("alice", "r1"), ("bob", "r1"), (None, "r2"), ("alice", "r2")]
    for owner, run_id in owners:
        await store.put_batch([_ev(run_id=run_id, user_id=owner)])
    await store.put_batch([_ev(run_id="r1", category="trace", event_type="llm_end", user_id="bob")])

    # A run with no events, in an existing thread: 0, and no intent.
    before = len(server.calls)
    assert await store.delete_by_run("t1", "nope") == 0
    assert {call.method for call in server.calls[before:]} == {"read_stream"}
    assert _index(server) == []

    # user_id is accepted in all three states and does not scope (the store is not user-scoped, like memory/JSONL).
    assert await store.delete_by_run("t1", "r1", user_id="alice") == 3
    token = set_current_user(type("Owner", (), {"id": "carol"})())
    try:
        assert await store.delete_by_run("t1", "r2") == 2  # AUTO
    finally:
        reset_current_user(token)
    assert await store.count_messages("t1") == 0

    await store.put(**_ev(run_id="r3"))
    await store.put(**_ev(run_id="r3", category="trace", event_type="llm_end"))
    assert await store.delete_by_thread("t1", user_id=None) == 2
    # Already cleared: nothing live, so no new intent.
    assert await store.delete_by_thread("t1", user_id="alice") == 0
    assert await store.delete_by_run("t1", "r3") == 0
    assert _index(server) == ["DeletionIntended", "DeletionDone"] * 3


@pytest.mark.anyio
async def test_deletion_updates_the_head_cache(store, server):
    for run_id in ("r1", "r2", "r2"):
        await store.put(**_ev(run_id=run_id))
    assert await store.delete_by_run("t1", "r2") == 2
    before = len(server.calls)
    assert (await store.put(**_ev(run_id="r3")))["seq"] == 4
    # The deletion remembered the new head: the next put is one append, no read, no conflict.
    assert [call.method for call in server.calls[before:]] == ["append_to_stream"]
    assert await store.delete_by_thread("t1") == 2
    before = len(server.calls)
    assert (await store.put(**_ev()))["seq"] == 5
    assert [call.method for call in server.calls[before:]] == ["append_to_stream"]


@pytest.mark.anyio
async def test_deletion_lost_ack_is_settled_as_committed(store, server):
    for run_id in ("r1", "r2"):
        await store.put(**_ev(run_id=run_id))
    server.fail_next("append_to_stream", DeadlineExceededError("ack lost"), after_commit=True, stream_name=T1)
    assert await store.delete_by_run("t1", "r2") == 1
    assert [_short(e.type) for e in _all_events(server)] == ["RunEvent", "RunEvent", "RunsCompacted", "RunEvent"]
    assert _index(server) == ["DeletionIntended", "DeletionDone"]
    assert (await store.put(**_ev(run_id="r3")))["seq"] == 3


@pytest.mark.anyio
async def test_deletion_lost_request_is_fenced_off_and_retried(store, server):
    for run_id in ("r1", "r2"):
        await store.put(**_ev(run_id=run_id))
    server.fail_next("append_to_stream", DeadlineExceededError("request lost"), stream_name=T1)
    assert await store.delete_by_run("t1", "r2") == 1
    # The fence settles the first attempt as not committed (abandoned); the retry commits at the new head.
    assert [_short(e.type) for e in _all_events(server)] == ["RunEvent", "RunEvent", "Fence", "RunsCompacted", "RunEvent"]
    assert _index(server) == ["DeletionIntended", "DeletionAbandoned", "DeletionIntended", "DeletionDone"]
    assert _tb(server) == 3
    assert [m["run_id"] for m in await _store(server).list_messages("t1")] == ["r1"]
    assert (await store.put(**_ev(run_id="r3")))["seq"] == 3


@pytest.mark.anyio
async def test_unsettled_deletion_blocks_the_next_until_settled(store, server):
    from deerflow_extension_kurrentdb.deletions import DeletionBlocked, DeletionOutcomeUnknown

    for run_id in ("r1", "r2", "r3"):
        await store.put(**_ev(run_id=run_id))

    def fail_primary_appends(count: int) -> None:
        for _ in range(count):
            server.fail_next("append_to_stream", ServiceUnavailableError("down"), stream_name=T1)

    fail_primary_appends(2)  # the boundary and its fence
    with pytest.raises(DeletionOutcomeUnknown):
        await store.delete_by_run("t1", "r2")
    assert _index(server) == ["DeletionIntended"]

    fail_primary_appends(2)  # recovery's fence, twice (before reading the head, and inside the engine)
    with pytest.raises(DeletionBlocked):
        await store.delete_by_run("t1", "r3")
    assert _index(server) == ["DeletionIntended"]  # no second intent while the first is unsettled
    assert [m["run_id"] for m in await store.list_messages("t1")] == ["r1", "r2", "r3"]

    # Once a fence lands, the first is abandoned and the next deletion proceeds.
    assert await store.delete_by_run("t1", "r3") == 1
    assert _index(server) == ["DeletionIntended", "DeletionAbandoned", "DeletionIntended", "DeletionDone"]
    assert [m["run_id"] for m in await _store(server).list_messages("t1")] == ["r1", "r2"]
    assert (await store.put(**_ev(run_id="r4")))["seq"] == 4


@pytest.mark.anyio
async def test_later_deletion_defers_tb_until_the_earlier_one_closes(store, server):
    for run_id in ("r1", "r2", "r3"):
        await store.put(**_ev(run_id=run_id))
    # A's $tb fails in its own call and in both recoveries B runs first; B commits but defers.
    for _ in range(3):
        server.fail_next("get_stream_metadata", ServiceUnavailableError("metadata down"), stream_name=T1)
    assert await store.delete_by_run("t1", "r2") == 1
    assert await store.delete_by_run("t1", "r3") == 1
    assert _index(server) == ["DeletionIntended", "DeletionIntended"]
    assert _tb(server) == 0
    assert [m["run_id"] for m in await _store(server).list_messages("t1")] == ["r1"]

    assert await _store(server).recover_deletions() == []
    assert _index(server) == ["DeletionIntended", "DeletionIntended", "DeletionDone", "DeletionDone"]
    # $tb rose in deletion order, to each boundary in turn.
    assert [call.kwargs["metadata"]["$tb"] for call in server.calls_to("set_stream_metadata", T1)] == [3, 6]
    assert [_short(e.type) for e in _raw(server)] == ["RunsCompacted", "RunEvent"]
    assert (await store.put(**_ev(run_id="r4")))["seq"] == 4


@pytest.mark.anyio
async def test_deletion_with_unreachable_server_raises_and_writes_nothing(store, server):
    await store.put(**_ev())
    server.set_unavailable(ServiceUnavailableError("down"))
    with pytest.raises(ServiceUnavailableError):
        await store.delete_by_thread("t1")
    server.set_unavailable(None)
    assert _index(server) == []
    assert [_short(e.type) for e in _raw(server)] == ["RunEvent"]


@pytest.mark.anyio
async def test_deletion_client_calls_pass_the_timeout(store, server):
    for run_id in ("r1", "r2", "r3"):
        await store.put(**_ev(run_id=run_id))
    server.fail_next("append_to_stream", DeadlineExceededError("request lost"), stream_name=T1)
    await store.delete_by_run("t1", "r2")
    await store.delete_by_thread("t1")
    await store.delete_by_thread("t2")
    await store.recover_deletions()
    assert {call.method for call in server.calls} >= {"read_stream", "append_to_stream", "get_current_version", "get_stream", "get_stream_metadata", "set_stream_metadata"}
    assert {call.kwargs.get("timeout") for call in server.calls} == {TIMEOUT}
