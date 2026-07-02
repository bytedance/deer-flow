"""Tests for KurrentRunEventStore — run events as KurrentDB streams (#3910).

Mirrors the contract cases in test_run_event_store.py against a fake async
KurrentDB client (no real KurrentDB required), plus KurrentDB-specific
behavior: seq-from-stream-revision derivation, run-redaction deletes, and
the best-effort canonical kurrent-agent-schema dual-write for messages.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("kurrentdbclient")

from kurrentdbclient.exceptions import NotFoundError

from deerflow.community.kurrentdb.run_event_store import KurrentRunEventStore

# ---------------------------------------------------------------------------
# Fake async client
# ---------------------------------------------------------------------------


class FakeRecordedEvent:
    """Stand-in for kurrentdbclient.events.RecordedEvent (only fields we use)."""

    def __init__(self, *, type: str, data: bytes, metadata: bytes = b"{}", stream_position: int, id=None):
        import uuid as _uuid

        self.type = type
        self.data = data
        self.metadata = metadata
        self.stream_position = stream_position
        self.id = id if id is not None else _uuid.uuid4()


class FakeAsyncKurrentDBClient:
    """In-memory stand-in for kurrentdbclient.AsyncKurrentDBClient (unit tests only).

    ``append_to_stream`` returns a global-looking incrementing int (mirrors
    the real client returning a commit *position*, not a stream revision) so
    tests would fail loudly if the store under test mistakenly treated the
    append return value as the per-event seq.

    ``before_get_stream``, if set, is called once (and cleared) at the start
    of the next ``get_stream`` call -- used by tests to simulate a second
    writer's full ``put()`` landing between a first writer's append and its
    post-append read-back (interleaving regression coverage).
    """

    def __init__(self):
        self.streams: dict[str, list[FakeRecordedEvent]] = {}
        self.deleted_streams: set[str] = set()
        self.connected = False
        self._global_position = 0
        self.append_calls: list[dict] = []
        self.get_stream_calls: list[dict] = []
        self.delete_stream_calls: list[dict] = []
        self.before_get_stream = None

    async def connect(self) -> None:
        self.connected = True

    async def append_to_stream(self, stream_name, *, events, current_version, timeout=None):
        events = [events] if not isinstance(events, list) else events
        self.append_calls.append({"stream_name": stream_name, "events": events, "current_version": current_version, "timeout": timeout})
        existing = self.streams.setdefault(stream_name, [])
        self.deleted_streams.discard(stream_name)
        start_position = len(existing)
        for i, ev in enumerate(events):
            existing.append(FakeRecordedEvent(type=ev.type, data=ev.data, metadata=ev.metadata, stream_position=start_position + i, id=ev.id))
            self._global_position += 1
        # Real client returns a *global commit position*, deliberately NOT
        # equal to the new stream revision -- offset it far away so any bug
        # that uses this value as seq is caught immediately.
        return self._global_position + 1_000_000

    async def get_stream(self, stream_name, *, stream_position=None, backwards=False, resolve_links=False, limit=2**63 - 1, timeout=None):
        if self.before_get_stream is not None:
            hook = self.before_get_stream
            self.before_get_stream = None
            await hook()
        self.get_stream_calls.append({"stream_name": stream_name, "stream_position": stream_position, "backwards": backwards, "limit": limit, "timeout": timeout})
        if stream_name not in self.streams or stream_name in self.deleted_streams:
            raise NotFoundError(stream_name)
        events = list(self.streams[stream_name])
        if backwards:
            events.reverse()
        if stream_position is not None:
            if backwards:
                events = [e for e in events if e.stream_position <= stream_position]
            else:
                events = [e for e in events if e.stream_position >= stream_position]
        return tuple(events[:limit])

    async def delete_stream(self, stream_name, *, current_version, timeout=None):
        self.delete_stream_calls.append({"stream_name": stream_name, "current_version": current_version, "timeout": timeout})
        if stream_name not in self.streams or stream_name in self.deleted_streams:
            raise NotFoundError(stream_name)
        self.deleted_streams.add(stream_name)


def _new_event(type_, data: dict, metadata: dict | None = None):
    """Build a minimal NewEvent-like stand-in accepted by the fake client."""
    from kurrentdbclient import NewEvent

    return NewEvent(type=type_, data=json.dumps(data).encode("utf-8"), metadata=json.dumps(metadata or {}).encode("utf-8"))


@pytest.fixture
def fake_client():
    return FakeAsyncKurrentDBClient()


@pytest.fixture
def store(fake_client):
    return KurrentRunEventStore(client_factory=lambda: fake_client)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_missing_connection_string_raises(self, monkeypatch):
        monkeypatch.delenv("KURRENTDB_CONNECTION_STRING", raising=False)
        with pytest.raises(RuntimeError, match="KURRENTDB_CONNECTION_STRING"):
            KurrentRunEventStore()

    def test_env_connection_string_accepted_without_connecting(self, monkeypatch):
        monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://localhost:2113?tls=false")
        # Must not raise and must not touch the network (client is lazy).
        KurrentRunEventStore()


# ---------------------------------------------------------------------------
# put / seq
# ---------------------------------------------------------------------------


class TestPutAndSeq:
    @pytest.mark.anyio
    async def test_put_returns_complete_record_with_seq(self, store):
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        assert record["seq"] == 1
        assert record["thread_id"] == "t1"
        assert record["run_id"] == "r1"
        assert record["event_type"] == "human_message"
        assert record["category"] == "message"
        assert record["content"] == "hello"
        assert "created_at" in record

    @pytest.mark.anyio
    async def test_seq_strictly_increasing_same_thread(self, store):
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        r3 = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert r1["seq"] == 1
        assert r2["seq"] == 2
        assert r3["seq"] == 3

    @pytest.mark.anyio
    async def test_seq_increasing_across_runs_same_thread(self, store):
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        assert r1["seq"] == 1
        assert r2["seq"] == 2

    @pytest.mark.anyio
    async def test_seq_independent_across_threads(self, store):
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        r2 = await store.put(thread_id="t2", run_id="r2", event_type="human_message", category="message")
        assert r1["seq"] == 1
        assert r2["seq"] == 1

    @pytest.mark.anyio
    async def test_put_respects_provided_created_at(self, store):
        ts = "2024-06-01T12:00:00+00:00"
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", created_at=ts)
        assert record["created_at"] == ts

    @pytest.mark.anyio
    async def test_put_metadata_preserved(self, store):
        meta = {"model": "gpt-4", "tokens": 100}
        record = await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", metadata=meta)
        assert record["metadata"] == meta

    @pytest.mark.anyio
    async def test_event_type_stored_verbatim_not_collapsed_to_category(self, store, fake_client):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        stream_name = "deerflow.runs-t1"
        stored = fake_client.streams[stream_name][0]
        assert stored.type == "llm_end"


# ---------------------------------------------------------------------------
# put_batch
# ---------------------------------------------------------------------------


class TestPutBatch:
    @pytest.mark.anyio
    async def test_batch_assigns_seq(self, store):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "a"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "b"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace"},
        ]
        results = await store.put_batch(events)
        assert len(results) == 3
        assert all("seq" in r for r in results)

    @pytest.mark.anyio
    async def test_batch_seq_strictly_increasing(self, store):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message"},
        ]
        results = await store.put_batch(events)
        assert results[0]["seq"] == 1
        assert results[1]["seq"] == 2

    @pytest.mark.anyio
    async def test_batch_uses_single_append_call(self, store, fake_client):
        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"} for _ in range(5)]
        await store.put_batch(events)
        assert len(fake_client.append_calls) == 1
        assert len(fake_client.append_calls[0]["events"]) == 5

    @pytest.mark.anyio
    async def test_batch_cross_thread_raises_value_error(self, store):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"},
            {"thread_id": "t2", "run_id": "r2", "event_type": "trace", "category": "trace"},
        ]
        with pytest.raises(ValueError, match="same thread"):
            await store.put_batch(events)

    @pytest.mark.anyio
    async def test_empty_batch_returns_empty_list(self, store):
        assert await store.put_batch([]) == []


# ---------------------------------------------------------------------------
# Stable per-record event IDs (retry-safety mechanism)
# ---------------------------------------------------------------------------


class TestStableEventIds:
    @pytest.mark.anyio
    async def test_put_batch_assigns_kurrent_event_id_to_input_dicts(self, store):
        """RunJournal retries re-send the SAME dict objects; put_batch must
        stamp an id onto them (mutating the caller's dicts) so a retry after
        a failed round-trip reuses the same NewEvent id."""
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"},
        ]
        await store.put_batch(events)
        assert "_kurrent_event_id" in events[0]

    @pytest.mark.anyio
    async def test_put_batch_does_not_overwrite_existing_event_id_on_retry(self, store, fake_client):
        """Simulates a RunJournal retry: the same dict (already stamped) is
        put_batch'd twice. The second call must reuse the same event id
        rather than minting a new one, or KurrentDB-side idempotence (and our
        own read-side dedup) has nothing stable to key off of."""
        event = {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"}
        await store.put_batch([event])
        first_id = event["_kurrent_event_id"]
        # Retry with the SAME dict object (as RunJournal._flush_async does).
        await store.put_batch([event])
        assert event["_kurrent_event_id"] == first_id

    @pytest.mark.anyio
    async def test_returned_record_shape_excludes_internal_event_id(self, store):
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert set(record.keys()) == {"thread_id", "run_id", "event_type", "category", "content", "metadata", "seq", "created_at"}

    @pytest.mark.anyio
    async def test_stored_payload_excludes_internal_event_id(self, store, fake_client):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        stored = fake_client.streams["deerflow.runs-t1"][0]
        payload = json.loads(stored.data)
        assert "_kurrent_event_id" not in payload

    @pytest.mark.anyio
    async def test_new_event_id_matches_stamped_kurrent_event_id(self, store, fake_client):
        from uuid import UUID

        record_input = {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"}
        await store.put_batch([record_input])
        stored_id = fake_client.streams["deerflow.runs-t1"][0].id
        assert stored_id == UUID(record_input["_kurrent_event_id"])


# ---------------------------------------------------------------------------
# Concurrent-writer interleaving (Critical 1 regression)
# ---------------------------------------------------------------------------


class TestInterleavedWriters:
    @pytest.mark.anyio
    async def test_seq_attribution_survives_interleaved_writer(self, store, fake_client):
        """Writer A appends 2 events. Before A's post-append read-back runs,
        writer B fully appends+reads-back 3 events of its own to the SAME
        thread stream (simulating a concurrent request). A's returned records
        must carry the seq of A's OWN events, not be positionally zipped
        against whatever the backwards read happens to return.
        """
        thread_id = "t1"

        async def writer_b_lands_in_the_middle():
            # Runs once, right before A's tail read-back. Must not itself
            # trigger recursively (the fake clears the hook before calling).
            await store.put(thread_id=thread_id, run_id="rB", event_type="human_message", category="message", content="b1")
            await store.put(thread_id=thread_id, run_id="rB", event_type="ai_message", category="message", content="b2")
            await store.put(thread_id=thread_id, run_id="rB", event_type="llm_end", category="trace", content="b3")

        events_a = [
            {"thread_id": thread_id, "run_id": "rA", "event_type": "human_message", "category": "message", "content": "a1"},
            {"thread_id": thread_id, "run_id": "rA", "event_type": "ai_message", "category": "message", "content": "a2"},
        ]

        fake_client.before_get_stream = writer_b_lands_in_the_middle
        results_a = await store.put_batch(events_a)

        # Writer A's own events must be attributed A's own seqs: since A
        # appended first (positions 0-1) before B appended (positions 2-4),
        # A's events are stream_position 0 and 1 => seq 1 and 2.
        assert [r["seq"] for r in results_a] == [1, 2]
        assert [r["content"] for r in results_a] == ["a1", "a2"]

        # Sanity: B's events really did land at higher positions, and the
        # full stream reflects all 5 events in the right order.
        all_events = await store.list_events(thread_id, "rA")
        assert [e["content"] for e in all_events] == ["a1", "a2"]
        b_events = await store.list_events(thread_id, "rB")
        assert [e["content"] for e in b_events] == ["b1", "b2", "b3"]


# ---------------------------------------------------------------------------
# Retry-safety: append succeeds, read-back/put_batch fails, caller retries
# with the SAME record dicts (Critical 2 regression)
# ---------------------------------------------------------------------------


class TestRetrySafety:
    @pytest.mark.anyio
    async def test_retry_with_same_dicts_produces_no_duplicates(self, store, fake_client):
        """Simulates RunJournal._flush_async: put_batch's append succeeds,
        but the post-append read-back transport call raises, so put_batch
        raises to the caller even though the events are already durable.
        RunJournal pushes the SAME dicts back onto its buffer and retries on
        the next flush. The store must not duplicate events on the stream,
        and seq attribution must stay correct.
        """
        thread_id = "t1"
        events = [
            {"thread_id": thread_id, "run_id": "r1", "event_type": "human_message", "category": "message", "content": "hello"},
            {"thread_id": thread_id, "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "hi back"},
        ]

        real_get_stream = fake_client.get_stream
        call_count = {"n": 0}

        async def flaky_get_stream(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("kurrentdb down during read-back")
            return await real_get_stream(*args, **kwargs)

        fake_client.get_stream = flaky_get_stream

        with pytest.raises(ConnectionError):
            await store.put_batch(events)

        # The append already committed even though put_batch raised.
        stream_name = "deerflow.runs-t1"
        assert len(fake_client.streams[stream_name]) == 2

        # Retry with the SAME dict objects (mirrors RunJournal's buffer
        # re-push: `self._buffer = batch + self._buffer`). The retry
        # re-appends (the store cannot know the prior append committed), so
        # the underlying stream now physically holds 4 events -- 2 pairs
        # sharing the same stable `_kurrent_event_id` per logical record.
        fake_client.get_stream = real_get_stream
        results = await store.put_batch(events)
        assert len(fake_client.streams[stream_name]) == 4
        # The retry's own return value reports the seq of the events *this*
        # (successful) append call produced -- the second, higher-position
        # copy. That is a one-time, in-process return value only seen by the
        # caller of this specific retry.
        assert [r["seq"] for r in results] == [3, 4]

        # What matters for correctness is every *read* path: read-side dedup
        # (keep-first by stream_position) collapses the duplicate pair back
        # down to 2 logical events at the ORIGINAL (first-ever) seq, forever
        # after -- in both list_events and list_messages.
        stream_events = await store.list_events(thread_id, "r1")
        assert len(stream_events) == 2
        assert [e["content"] for e in stream_events] == ["hello", "hi back"]
        assert [e["seq"] for e in stream_events] == [1, 2]

        messages = await store.list_messages(thread_id)
        assert len(messages) == 2
        assert [m["seq"] for m in messages] == [1, 2]


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    @pytest.mark.anyio
    async def test_only_returns_message_category(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["category"] == "message"

    @pytest.mark.anyio
    async def test_ascending_seq_order(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="first")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="second")
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="third")
        messages = await store.list_messages("t1")
        seqs = [m["seq"] for m in messages]
        assert seqs == sorted(seqs)

    @pytest.mark.anyio
    async def test_before_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", before_seq=6, limit=3)
        assert [m["seq"] for m in messages] == [3, 4, 5]

    @pytest.mark.anyio
    async def test_after_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", after_seq=7, limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_default_returns_latest(self, store):
        for _ in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_limit_restricts_count(self, store):
        for _ in range(20):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=5)
        assert len(messages) == 5

    @pytest.mark.anyio
    async def test_missing_stream_returns_empty_list(self, store):
        assert await store.list_messages("nope") == []

    @pytest.mark.anyio
    async def test_pagination_with_interleaved_trace_events(self, store):
        # Messages and non-message events interleave, so message seqs are
        # non-contiguous (1, 3, 5, 7, 9) -- mirrors
        # test_run_event_store.py::TestListMessages::test_pagination_with_interleaved_trace_events.
        for i in range(10):
            category = "message" if i % 2 == 0 else "trace"
            await store.put(thread_id="t1", run_id="r1", event_type="e", category=category, content=str(i))

        assert [m["seq"] for m in await store.list_messages("t1")] == [1, 3, 5, 7, 9]
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=6, limit=2)] == [3, 5]
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=5, limit=5)] == [1, 3]
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=4, limit=2)] == [5, 7]
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=5, limit=5)] == [7, 9]


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------


class TestListEvents:
    @pytest.mark.anyio
    async def test_returns_all_categories_for_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="run_start", category="lifecycle")
        events = await store.list_events("t1", "r1")
        assert len(events) == 3

    @pytest.mark.anyio
    async def test_event_types_filter(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_start", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r1", event_type="tool_start", category="trace")
        events = await store.list_events("t1", "r1", event_types=["llm_end"])
        assert len(events) == 1
        assert events[0]["event_type"] == "llm_end"

    @pytest.mark.anyio
    async def test_only_returns_specified_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        events = await store.list_events("t1", "r1")
        assert len(events) == 1
        assert events[0]["run_id"] == "r1"

    @pytest.mark.anyio
    async def test_missing_stream_returns_empty_list(self, store):
        assert await store.list_events("nope", "r1") == []


# ---------------------------------------------------------------------------
# list_messages_by_run
# ---------------------------------------------------------------------------


class TestListMessagesByRun:
    @pytest.mark.anyio
    async def test_only_messages_for_specified_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await store.list_messages_by_run("t1", "r1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"
        assert messages[0]["category"] == "message"

    @pytest.mark.anyio
    async def test_before_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages_by_run("t1", "r1", before_seq=6, limit=3)
        assert [m["seq"] for m in messages] == [3, 4, 5]

    @pytest.mark.anyio
    async def test_after_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages_by_run("t1", "r1", after_seq=7, limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]


# ---------------------------------------------------------------------------
# count_messages
# ---------------------------------------------------------------------------


class TestCountMessages:
    @pytest.mark.anyio
    async def test_counts_only_message_category(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert await store.count_messages("t1") == 2

    @pytest.mark.anyio
    async def test_missing_stream_returns_zero(self, store):
        assert await store.count_messages("nope") == 0


# ---------------------------------------------------------------------------
# delete_by_thread
# ---------------------------------------------------------------------------


class TestDeleteByThread:
    @pytest.mark.anyio
    async def test_delete_by_thread_returns_count_and_empties_reads(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")

        count = await store.delete_by_thread("t1")

        assert count == 3
        assert await store.list_messages("t1") == []
        assert await store.count_messages("t1") == 0
        assert await store.list_events("t1", "r1") == []

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_returns_zero(self, store):
        assert await store.delete_by_thread("nope") == 0


# ---------------------------------------------------------------------------
# delete_by_run (event-native redaction)
# ---------------------------------------------------------------------------


class TestDeleteByRun:
    @pytest.mark.anyio
    async def test_redacts_run_events_from_all_read_paths(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")

        count = await store.delete_by_run("t1", "r2")

        assert count == 2
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"
        assert await store.list_events("t1", "r2") == []
        assert await store.list_messages_by_run("t1", "r2") == []
        assert await store.count_messages("t1") == 1

    @pytest.mark.anyio
    async def test_other_runs_unaffected(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.delete_by_run("t1", "r2")
        events = await store.list_events("t1", "r1")
        assert len(events) == 1

    @pytest.mark.anyio
    async def test_marker_not_visible_in_any_read_path(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.delete_by_run("t1", "r1")
        events = await store.list_events("t1", "r1")
        assert events == []
        # The marker itself must never surface as a run's own event either.
        all_events_for_thread = await store.list_messages("t1")
        assert all_events_for_thread == []

    @pytest.mark.anyio
    async def test_delete_nonexistent_run_returns_zero(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert await store.delete_by_run("t1", "nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_for_run_returns_zero(self, store):
        assert await store.delete_by_run("nope", "r1") == 0

    @pytest.mark.anyio
    async def test_seq_still_advances_after_redaction_marker(self, store):
        """The redaction marker itself consumes a seq (it's an event on the stream)."""
        r1 = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.delete_by_run("t1", "r1")
        r2 = await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        assert r1["seq"] == 1
        assert r2["seq"] > r1["seq"]


# ---------------------------------------------------------------------------
# Missing-stream vs transport-error read semantics
# ---------------------------------------------------------------------------


class TestReadFailureSemantics:
    @pytest.mark.anyio
    async def test_transport_error_raises_not_empty(self, store, fake_client):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")

        async def broken_get_stream(*args, **kwargs):
            raise ConnectionError("kurrentdb down")

        fake_client.get_stream = broken_get_stream
        with pytest.raises(ConnectionError):
            await store.list_messages("t1")


# ---------------------------------------------------------------------------
# Canonical dual-write (best-effort, messages only)
# ---------------------------------------------------------------------------


class TestCanonicalDualWrite:
    @pytest.mark.anyio
    async def test_human_message_emits_user_message_received(self, store, fake_client):
        from kurrent_agent_schema import UserMessageReceived, from_json

        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello there")

        canonical_stream = "AgentSession-t1"
        calls = [c for c in fake_client.append_calls if c["stream_name"] == canonical_stream]
        assert len(calls) == 1
        event = calls[0]["events"][0]
        decoded = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
        canonical_event = from_json(UserMessageReceived, decoded)
        assert canonical_event.content == "hello there"

    @pytest.mark.anyio
    async def test_ai_message_emits_assistant_text_generated(self, store, fake_client):
        from kurrent_agent_schema import AssistantTextGenerated, from_json

        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="hi back")

        canonical_stream = "AgentSession-t1"
        calls = [c for c in fake_client.append_calls if c["stream_name"] == canonical_stream]
        assert len(calls) == 1
        event = calls[0]["events"][0]
        decoded = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
        canonical_event = from_json(AssistantTextGenerated, decoded)
        assert canonical_event.content == "hi back"

    @pytest.mark.anyio
    async def test_trace_record_emits_no_canonical_event(self, store, fake_client):
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", content="ignored")
        canonical_stream = "AgentSession-t1"
        assert all(c["stream_name"] != canonical_stream for c in fake_client.append_calls)

    @pytest.mark.anyio
    async def test_unmappable_message_event_type_skipped(self, store, fake_client):
        await store.put(thread_id="t1", run_id="r1", event_type="some_other_message_kind", category="message", content="?")
        canonical_stream = "AgentSession-t1"
        assert all(c["stream_name"] != canonical_stream for c in fake_client.append_calls)

    @pytest.mark.anyio
    async def test_canonical_metadata_carries_schema_version(self, store, fake_client):
        from kurrent_agent_schema import SCHEMA_VERSION

        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        canonical_stream = "AgentSession-t1"
        event = next(c for c in fake_client.append_calls if c["stream_name"] == canonical_stream)["events"][0]
        metadata = json.loads(event.metadata)
        assert metadata["schema_version"] == SCHEMA_VERSION

    @pytest.mark.anyio
    async def test_canonical_failure_isolated_primary_put_still_succeeds(self, store, fake_client):
        real_append = fake_client.append_to_stream

        async def flaky_append(stream_name, *, events, current_version, timeout=None):
            if stream_name == "AgentSession-t1":
                raise ConnectionError("kurrentdb down")
            return await real_append(stream_name, events=events, current_version=current_version, timeout=timeout)

        fake_client.append_to_stream = flaky_append

        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert record["seq"] == 1
        assert record["content"] == "hi"

    @pytest.mark.anyio
    async def test_batch_dual_writes_only_message_records(self, store, fake_client):
        events = [
            {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "hi"},
            {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace"},
        ]
        await store.put_batch(events)
        canonical_stream = "AgentSession-t1"
        calls = [c for c in fake_client.append_calls if c["stream_name"] == canonical_stream]
        assert len(calls) == 1
        assert len(calls[0]["events"]) == 1


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactory:
    @pytest.mark.anyio
    async def test_factory_builds_kurrent_store(self, monkeypatch):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://localhost:2113?tls=false")
        config = MagicMock()
        config.backend = "kurrent"
        store = make_run_event_store(config)
        assert type(store).__name__ == "KurrentRunEventStore"

    @pytest.mark.anyio
    async def test_factory_missing_env_raises(self, monkeypatch):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        monkeypatch.delenv("KURRENTDB_CONNECTION_STRING", raising=False)
        config = MagicMock()
        config.backend = "kurrent"
        with pytest.raises(RuntimeError, match="KURRENTDB_CONNECTION_STRING"):
            make_run_event_store(config)
