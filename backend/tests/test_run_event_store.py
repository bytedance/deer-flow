"""Tests for RunEventStore contract across all backends.

Uses a helper to create the store for each backend type.
Memory tests run directly; DB and JSONL tests create stores inside each test.
"""

from unittest.mock import AsyncMock, patch

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture
def store():
    return MemoryRunEventStore()


async def _assert_find_latest_ai_message_run_ids_contract(store, *, allow_empty_run_id: bool) -> None:
    assert await store.find_latest_ai_message_run_ids("t1", set()) == {}

    await store.put(
        thread_id="t1",
        run_id="trace-run",
        event_type="llm.ai.response",
        category="trace",
        content={"type": "ai", "id": "target"},
    )
    await store.put(
        thread_id="t1",
        run_id="string-content-run",
        event_type="llm.ai.response",
        category="message",
        content="target",
    )
    await store.put(
        thread_id="t1",
        run_id="human-run",
        event_type="human_message",
        category="message",
        content={"type": "human", "id": "target"},
    )
    await store.put(
        thread_id="t1",
        run_id="old-run",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "id": "target"},
    )
    await store.put(
        thread_id="t1",
        run_id="other-run",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "id": "other"},
    )
    await store.put(
        thread_id="t1",
        run_id="decoy-run",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "id": "decoy", "note": "target"},
    )
    await store.put(
        thread_id="t1",
        run_id="new-run",
        event_type="llm.ai.response",
        category="message",
        content={"type": "ai", "id": "target"},
    )
    if allow_empty_run_id:
        await store.put(
            thread_id="t1",
            run_id="",
            event_type="llm.ai.response",
            category="message",
            content={"type": "ai", "id": "target"},
        )

    assert await store.find_latest_ai_message_run_ids("t1", {"target", "other", "missing"}, user_id=None) == {
        "target": "new-run",
        "other": "other-run",
    }


# -- Basic write and query --


class TestPutAndSeq:
    @pytest.mark.anyio
    async def test_put_returns_dict_with_seq(self, store):
        record = await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hello")
        assert "seq" in record
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
    async def test_put_if_absent_preserves_first_run_scoped_event(self, store):
        first, created = await store.put_if_absent(
            thread_id="t1",
            run_id="r1",
            event_type="run.delivery",
            category="outputs",
            content={"presented": 1},
        )
        duplicate, duplicate_created = await store.put_if_absent(
            thread_id="t1",
            run_id="r1",
            event_type="run.delivery",
            category="outputs",
            content={"presented": 0},
        )

        assert created is True
        assert duplicate_created is False
        assert duplicate == first
        assert [event["content"] for event in await store.list_events("t1", "r1") if event["event_type"] == "run.delivery"] == [{"presented": 1}]


# -- list_messages --


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
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [3, 4, 5]

    @pytest.mark.anyio
    async def test_after_seq_pagination(self, store):
        for i in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))
        messages = await store.list_messages("t1", after_seq=7, limit=3)
        assert len(messages) == 3
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_limit_restricts_count(self, store):
        for _ in range(20):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=5)
        assert len(messages) == 5

    @pytest.mark.anyio
    async def test_cross_run_unified_ordering(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        messages = await store.list_messages("t1")
        assert [m["seq"] for m in messages] == [1, 2, 3, 4]
        assert messages[0]["run_id"] == "r1"
        assert messages[2]["run_id"] == "r2"

    @pytest.mark.anyio
    async def test_default_returns_latest(self, store):
        for _ in range(10):
            await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        messages = await store.list_messages("t1", limit=3)
        assert [m["seq"] for m in messages] == [8, 9, 10]

    @pytest.mark.anyio
    async def test_pagination_with_interleaved_trace_events(self, store):
        # Messages and non-message events interleave, so message seqs are
        # non-contiguous (1, 3, 5, 7, 9). Seq-window pagination must still be
        # correct over the messages-only projection, including when the cursor
        # lands in a gap or exactly on a message seq (exclusive bound).
        for i in range(10):
            category = "message" if i % 2 == 0 else "trace"
            await store.put(thread_id="t1", run_id="r1", event_type="e", category=category, content=str(i))

        assert [m["seq"] for m in await store.list_messages("t1")] == [1, 3, 5, 7, 9]
        # before_seq in a gap: seq < 6 -> [1, 3, 5], last 2
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=6, limit=2)] == [3, 5]
        # before_seq on a message seq is exclusive: seq < 5 -> [1, 3]
        assert [m["seq"] for m in await store.list_messages("t1", before_seq=5, limit=5)] == [1, 3]
        # after_seq in a gap: seq > 4 -> [5, 7, 9], first 2
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=4, limit=2)] == [5, 7]
        # after_seq on a message seq is exclusive: seq > 5 -> [7, 9]
        assert [m["seq"] for m in await store.list_messages("t1", after_seq=5, limit=5)] == [7, 9]


class TestFindLatestAiMessageRunIds:
    @pytest.mark.anyio
    async def test_memory_contract(self, store):
        await _assert_find_latest_ai_message_run_ids_contract(store, allow_empty_run_id=True)

    @pytest.mark.anyio
    async def test_memory_stops_after_all_targets_are_found(self, store):
        from deerflow.runtime.events.store import base as event_store_base

        await store.put(
            thread_id="t1",
            run_id="old-run",
            event_type="llm.ai.response",
            category="message",
            content={"type": "ai", "id": "old"},
        )
        await store.put(
            thread_id="t1",
            run_id="new-run",
            event_type="llm.ai.response",
            category="message",
            content={"type": "ai", "id": "target"},
        )

        store.list_messages = AsyncMock(wraps=store.list_messages)
        with patch.object(event_store_base, "match_ai_message_run_id", wraps=event_store_base.match_ai_message_run_id) as match_event:
            assert await store.find_latest_ai_message_run_ids("t1", {"target"}, user_id=None) == {"target": "new-run"}
        assert match_event.call_count == 1
        store.list_messages.assert_awaited_once_with("t1", limit=1000, before_seq=None, user_id=None)

    @pytest.mark.anyio
    async def test_memory_pages_in_bounded_windows_and_keeps_initial_high_watermark(self, store):
        await store.put(
            thread_id="t1",
            run_id="old-run",
            event_type="llm.ai.response",
            category="message",
            content={"type": "ai", "id": "target"},
        )
        await store.put_batch(
            [
                {
                    "thread_id": "t1",
                    "run_id": "noise-run",
                    "event_type": "llm.ai.response",
                    "category": "message",
                    "content": {"type": "ai", "id": f"noise-{index}"},
                }
                for index in range(1000)
            ]
        )

        original_list_messages = store.list_messages
        calls: list[dict] = []

        async def list_messages(*args, **kwargs):
            page = await original_list_messages(*args, **kwargs)
            calls.append(kwargs)
            if len(calls) == 1:
                # This duplicate is newer than the first page's snapshot.  A
                # backward cursor must not let it replace the older answer
                # while resolving the rest of that same lookup.
                await store.put(
                    thread_id="t1",
                    run_id="concurrent-new-run",
                    event_type="llm.ai.response",
                    category="message",
                    content={"type": "ai", "id": "target"},
                )
            return page

        store.list_messages = AsyncMock(side_effect=list_messages)

        assert await store.find_latest_ai_message_run_ids("t1", {"target"}, user_id=None) == {"target": "old-run"}
        assert len(calls) == 2
        assert all(call["limit"] == 1000 for call in calls)
        assert calls[0].get("before_seq") is None
        assert calls[1]["before_seq"] == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("malformed_page", ["missing-seq", "non-progressing-seq"])
    async def test_default_lookup_raises_instead_of_looping_on_unsafe_cursor(self, store, malformed_page):
        from deerflow.runtime.events.store.base import RunEventStore

        calls = 0

        async def list_messages(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if malformed_page == "missing-seq":
                return [
                    {
                        "category": "message",
                        "content": {"type": "ai", "id": f"noise-{index}"},
                        "run_id": "noise-run",
                    }
                    for index in range(1000)
                ]
            return [
                {
                    "category": "message",
                    "content": {"type": "ai", "id": f"noise-{index}"},
                    "run_id": "noise-run",
                    "seq": index + 1,
                }
                for index in range(1000)
            ]

        store.list_messages = AsyncMock(side_effect=list_messages)

        with pytest.raises(RuntimeError, match="safe backward cursor"):
            await RunEventStore.find_latest_ai_message_run_ids(store, "t1", {"missing"}, user_id=None)
        assert calls == (1 if malformed_page == "missing-seq" else 2)


# -- list_events --


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


# -- list_messages_by_run --


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


# -- count_messages --


class TestCountMessages:
    @pytest.mark.anyio
    async def test_counts_only_message_category(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace")
        assert await store.count_messages("t1") == 2


# -- put_batch --


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


# -- delete --


class TestDelete:
    @pytest.mark.anyio
    async def test_delete_by_thread(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_thread("t1")
        assert count == 3
        assert await store.list_messages("t1") == []
        assert await store.count_messages("t1") == 0

    @pytest.mark.anyio
    async def test_delete_by_run(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        await store.put(thread_id="t1", run_id="r2", event_type="llm_end", category="trace")
        count = await store.delete_by_run("t1", "r2")
        assert count == 2
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["run_id"] == "r1"

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_returns_zero(self, store):
        assert await store.delete_by_thread("nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_run_returns_zero(self, store):
        await store.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert await store.delete_by_run("t1", "nope") == 0

    @pytest.mark.anyio
    async def test_delete_nonexistent_thread_for_run_returns_zero(self, store):
        assert await store.delete_by_run("nope", "r1") == 0


# -- Edge cases --


class TestEdgeCases:
    @pytest.mark.anyio
    async def test_empty_thread_list_messages(self, store):
        assert await store.list_messages("empty") == []

    @pytest.mark.anyio
    async def test_empty_run_list_events(self, store):
        assert await store.list_events("empty", "r1") == []

    @pytest.mark.anyio
    async def test_empty_thread_count_messages(self, store):
        assert await store.count_messages("empty") == 0


# -- DB-specific tests --


class TestDbRunEventStore:
    """Tests for DbRunEventStore with temp SQLite."""

    @pytest.mark.anyio
    async def test_postgres_max_seq_uses_advisory_lock_without_for_update(self):
        from sqlalchemy.dialects import postgresql

        from deerflow.runtime.events.store.db import DbRunEventStore

        class FakeSession:
            def __init__(self):
                self.dialect = postgresql.dialect()
                self.execute_calls = []
                self.scalar_stmt = None

            def get_bind(self):
                return self

            async def execute(self, stmt, params=None):
                self.execute_calls.append((stmt, params))

            async def scalar(self, stmt):
                self.scalar_stmt = stmt
                return 41

        session = FakeSession()

        max_seq = await DbRunEventStore._max_seq_for_thread(session, "thread-1")

        assert max_seq == 41
        assert session.execute_calls
        assert session.execute_calls[0][1] == {"thread_id": "thread-1"}
        assert "pg_advisory_xact_lock" in str(session.execute_calls[0][0])
        compiled = str(session.scalar_stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" not in compiled

    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        r2 = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content="hello")
        assert r2["seq"] == 2

        messages = await s.list_messages("t1")
        assert len(messages) == 2

        count = await s.count_messages("t1")
        assert count == 2

        await close_engine()

    @pytest.mark.anyio
    async def test_find_latest_ai_message_run_ids_contract_and_owner_filter(self, tmp_path):
        from types import SimpleNamespace

        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            store = DbRunEventStore(get_session_factory())
            await _assert_find_latest_ai_message_run_ids_contract(store, allow_empty_run_id=True)
            owner_a_token = set_current_user(SimpleNamespace(id="owner-a"))
            try:
                await store.put(
                    thread_id="owned-thread",
                    run_id="owner-a-run",
                    event_type="llm.ai.response",
                    category="message",
                    content={"type": "ai", "id": "shared-id"},
                )
            finally:
                reset_current_user(owner_a_token)

            owner_b_token = set_current_user(SimpleNamespace(id="owner-b"))
            try:
                await store.put(
                    thread_id="owned-thread",
                    run_id="owner-b-run",
                    event_type="llm.ai.response",
                    category="message",
                    content={"type": "ai", "id": "shared-id"},
                )
            finally:
                reset_current_user(owner_b_token)

            assert await store.find_latest_ai_message_run_ids("owned-thread", {"shared-id"}, user_id="owner-a") == {"shared-id": "owner-a-run"}
            assert await store.find_latest_ai_message_run_ids("owned-thread", {"shared-id"}, user_id="owner-b") == {"shared-id": "owner-b-run"}
        finally:
            await close_engine()

    @pytest.mark.anyio
    async def test_find_latest_ai_message_run_ids_handles_large_target_sets_and_special_ids(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            store = DbRunEventStore(get_session_factory())
            target_ids = {f"id-{index:03d}" for index in range(201)}
            special_id = 'message-%_/"-雪'
            target_ids.add(special_id)
            await store.put_batch(
                [
                    {
                        "thread_id": "t1",
                        "run_id": "first-chunk-run",
                        "event_type": "llm.ai.response",
                        "category": "message",
                        "content": {"type": "ai", "id": "id-000"},
                    },
                    {
                        "thread_id": "t1",
                        "run_id": "last-chunk-run",
                        "event_type": "llm.ai.response",
                        "category": "message",
                        "content": {"type": "ai", "id": "id-200"},
                    },
                    {
                        "thread_id": "t1",
                        "run_id": "special-run",
                        "event_type": "llm.ai.response",
                        "category": "message",
                        "content": {"type": "ai", "id": special_id},
                    },
                ]
            )

            assert await store.find_latest_ai_message_run_ids("t1", target_ids, user_id=None) == {
                "id-000": "first-chunk-run",
                "id-200": "last-chunk-run",
                special_id: "special-run",
            }
        finally:
            await close_engine()

    @pytest.mark.anyio
    async def test_find_latest_ai_message_run_ids_pages_db_with_owner_scoped_high_watermark(self, tmp_path):
        from types import SimpleNamespace

        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        owner_token = set_current_user(SimpleNamespace(id="owner-a"))
        try:
            store = DbRunEventStore(get_session_factory())
            await store.put(
                thread_id="t1",
                run_id="old-run",
                event_type="llm.ai.response",
                category="message",
                content={"type": "ai", "id": "target"},
            )
            await store.put_batch(
                [
                    {
                        "thread_id": "t1",
                        "run_id": "noise-run",
                        "event_type": "llm.ai.response",
                        "category": "message",
                        "content": {"type": "ai", "id": f"noise-{index}"},
                    }
                    for index in range(1000)
                ]
            )

            original_list_messages = store.list_messages
            calls: list[dict] = []

            async def list_messages(*args, **kwargs):
                page = await original_list_messages(*args, **kwargs)
                calls.append(kwargs)
                if len(calls) == 1:
                    await store.put(
                        thread_id="t1",
                        run_id="concurrent-new-run",
                        event_type="llm.ai.response",
                        category="message",
                        content={"type": "ai", "id": "target"},
                    )
                return page

            store.list_messages = AsyncMock(side_effect=list_messages)

            assert await store.find_latest_ai_message_run_ids("t1", {"target"}, user_id="owner-a") == {"target": "old-run"}
            assert len(calls) == 2
            assert all(call["limit"] == 1000 and call["user_id"] == "owner-a" for call in calls)
            assert calls[0].get("before_seq") is None
            assert calls[1]["before_seq"] == 2
        finally:
            reset_current_user(owner_token)
            await close_engine()

    @pytest.mark.anyio
    async def test_put_if_absent_is_idempotent(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        first, created = await s.put_if_absent(thread_id="t1", run_id="r1", event_type="run.delivery", category="outputs", content={"presented": 2})
        duplicate, duplicate_created = await s.put_if_absent(thread_id="t1", run_id="r1", event_type="run.delivery", category="outputs", content={"presented": 0})

        assert created is True
        assert duplicate_created is False
        assert duplicate["seq"] == first["seq"]
        assert duplicate["content"] == {"presented": 2}
        await close_engine()

    @pytest.mark.anyio
    async def test_trace_content_truncation(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory(), max_trace_content=100)

        long = "x" * 200
        r = await s.put(thread_id="t1", run_id="r1", event_type="llm_end", category="trace", content=long)
        assert len(r["content"]) == 100
        assert r["metadata"].get("content_truncated") is True

        # message content NOT truncated
        m = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content=long)
        assert len(m["content"]) == 200

        await close_engine()

    @pytest.mark.anyio
    async def test_structured_content_round_trips(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = [{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}]
        record = await s.put(thread_id="t1", run_id="r1", event_type="ai_message", category="message", content=content)

        assert record["content"] == content
        assert record["metadata"]["content_is_json"] is True
        assert "content_is_dict" not in record["metadata"]

        messages = await s.list_messages("t1")
        assert messages[0]["content"] == content
        assert messages[0]["metadata"]["content_is_json"] is True

        await close_engine()

    @pytest.mark.anyio
    async def test_pagination(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        for i in range(10):
            await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content=str(i))

        # before_seq
        msgs = await s.list_messages("t1", before_seq=6, limit=3)
        assert [m["seq"] for m in msgs] == [3, 4, 5]

        # after_seq
        msgs = await s.list_messages("t1", after_seq=7, limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        # default (latest)
        msgs = await s.list_messages("t1", limit=3)
        assert [m["seq"] for m in msgs] == [8, 9, 10]

        await close_engine()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="ai_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert await s.count_messages("t1") == 1

        c = await s.delete_by_thread("t1")
        assert c == 1
        assert await s.count_messages("t1") == 0

        await close_engine()

    @pytest.mark.anyio
    async def test_put_batch_seq_continuity(self, tmp_path):
        """Batch write produces continuous seq values with no gaps."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        events = [{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"} for _ in range(50)]
        results = await s.put_batch(events)
        seqs = [r["seq"] for r in results]
        assert seqs == list(range(1, 51))
        await close_engine()

    @pytest.mark.anyio
    async def test_put_batch_accepts_structured_content(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = [{"messages": [{"type": "ai", "content": ""}]}]
        results = await s.put_batch(
            [
                {
                    "thread_id": "t1",
                    "run_id": "r1",
                    "event_type": "run.end",
                    "category": "outputs",
                    "content": content,
                }
            ]
        )

        assert results[0]["content"] == content
        assert results[0]["metadata"]["content_is_json"] is True

        events = await s.list_events("t1", "r1")
        assert events[0]["content"] == content
        assert events[0]["metadata"]["content_is_json"] is True

        await close_engine()

    @pytest.mark.anyio
    async def test_dict_content_keeps_legacy_metadata_flag(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        content = {"status": "success"}
        record = await s.put(thread_id="t1", run_id="r1", event_type="run.end", category="outputs", content=content)

        assert record["content"] == content
        assert record["metadata"]["content_is_json"] is True
        assert record["metadata"]["content_is_dict"] is True

        await close_engine()


class TestDbRunEventStoreWriteLock:
    """Per-thread seq-assignment lock (fixes SQLite UNIQUE(thread_id, seq) races).

    Two in-process coroutines writing to the same thread can interleave between
    the ``max(seq)`` read and the INSERT, both computing the same next seq and
    colliding. A per-thread ``asyncio.Lock`` serializes seq assignment.
    """

    def test_get_write_lock_same_thread_returns_same_lock(self):
        import asyncio
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store.db import DbRunEventStore

        # The lock accessor does not touch the session factory, so a stub is fine.
        store = DbRunEventStore(MagicMock())

        lock = store._get_write_lock("thread-1")
        assert isinstance(lock, asyncio.Lock)
        assert store._get_write_lock("thread-1") is lock

    def test_get_write_lock_distinct_threads_get_distinct_locks(self):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store.db import DbRunEventStore

        store = DbRunEventStore(MagicMock())

        assert store._get_write_lock("thread-1") is not store._get_write_lock("thread-2")

    @pytest.mark.anyio
    async def test_concurrent_put_batch_same_thread_has_no_seq_collision(self, tmp_path):
        import asyncio

        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        def _batch(run_id: str):
            return [{"thread_id": "t1", "run_id": run_id, "event_type": "trace", "category": "trace"} for _ in range(20)]

        # Fire two concurrent batches at the same thread; without the per-thread
        # lock this races on seq and raises IntegrityError / duplicates seq.
        results = await asyncio.gather(s.put_batch(_batch("r1")), s.put_batch(_batch("r2")))

        all_seqs = [r["seq"] for batch in results for r in batch]
        assert len(all_seqs) == 40
        # Seq values are unique and contiguous 1..40 across both writers.
        assert sorted(all_seqs) == list(range(1, 41))

        await close_engine()

    @pytest.mark.anyio
    async def test_delete_by_thread_evicts_orphaned_write_lock(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        # A write materializes the per-thread lock in the registry.
        await s.put_batch([{"thread_id": "t1", "run_id": "r1", "event_type": "trace", "category": "trace"}])
        assert "t1" in s._write_locks

        # Deleting the thread must evict the now-orphaned lock so the registry
        # does not grow unbounded across the singleton store's lifetime.
        await s.delete_by_thread("t1")
        assert "t1" not in s._write_locks

        # A subsequent write recreates a fresh lock and seq restarts from 1.
        result = await s.put_batch([{"thread_id": "t1", "run_id": "r2", "event_type": "trace", "category": "trace"}])
        assert "t1" in s._write_locks
        assert result[0]["seq"] == 1

        await close_engine()

    @pytest.mark.anyio
    async def test_delete_by_thread_keeps_lock_held_by_inflight_writer(self, tmp_path):
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        s = DbRunEventStore(get_session_factory())

        # Simulate a writer mid-flight by holding the lock; the eviction must
        # not drop a lock another coroutine is actively using.
        lock = s._get_write_lock("t1")
        await lock.acquire()
        try:
            await s.delete_by_thread("t1")
            assert "t1" in s._write_locks
            assert s._write_locks["t1"] is lock
        finally:
            lock.release()

        await close_engine()


# -- Factory tests --


class TestMakeRunEventStore:
    """Tests for the make_run_event_store factory function."""

    @pytest.mark.anyio
    async def test_memory_backend_default(self):
        from deerflow.runtime.events.store import make_run_event_store

        store = make_run_event_store(None)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_memory_backend_explicit(self):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "memory"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"

    @pytest.mark.anyio
    async def test_db_backend_with_engine(self, tmp_path):
        from unittest.mock import MagicMock

        from deerflow.persistence.engine import close_engine, init_engine
        from deerflow.runtime.events.store import make_run_event_store

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))

        config = MagicMock()
        config.backend = "db"
        config.max_trace_content = 10240
        store = make_run_event_store(config)
        assert type(store).__name__ == "DbRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_db_backend_no_engine_falls_back(self):
        """db backend without engine falls back to memory."""
        from unittest.mock import MagicMock

        from deerflow.persistence.engine import close_engine, init_engine
        from deerflow.runtime.events.store import make_run_event_store

        await init_engine("memory")  # no engine created

        config = MagicMock()
        config.backend = "db"
        store = make_run_event_store(config)
        assert type(store).__name__ == "MemoryRunEventStore"
        await close_engine()

    @pytest.mark.anyio
    async def test_jsonl_backend(self):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "jsonl"
        store = make_run_event_store(config)
        assert type(store).__name__ == "JsonlRunEventStore"

    @pytest.mark.anyio
    async def test_unknown_backend_raises(self):
        from unittest.mock import MagicMock

        from deerflow.runtime.events.store import make_run_event_store

        config = MagicMock()
        config.backend = "redis"
        with pytest.raises(ValueError, match="Unknown"):
            make_run_event_store(config)


# -- JSONL-specific tests --


class TestJsonlRunEventStore:
    @pytest.mark.anyio
    @pytest.mark.parametrize("thread_id", ["", "thread.with.dot", "../escape", "x" * 65])
    async def test_rejects_noncanonical_thread_ids(self, tmp_path, thread_id):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        store = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        with pytest.raises(ValueError, match="Invalid thread_id"):
            await store.put(
                thread_id=thread_id,
                run_id="r1",
                event_type="human_message",
                category="message",
            )

    @pytest.mark.anyio
    async def test_basic_crud(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        r = await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message", content="hi")
        assert r["seq"] == 1
        messages = await s.list_messages("t1")
        assert len(messages) == 1

    @pytest.mark.anyio
    async def test_find_latest_ai_message_run_ids_contract(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        store = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await _assert_find_latest_ai_message_run_ids_contract(store, allow_empty_run_id=False)

    @pytest.mark.anyio
    async def test_find_latest_ai_message_run_ids_reads_thread_once_and_ignores_empty_run(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        store = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        events = [
            {
                "thread_id": "t1",
                "run_id": "valid-run",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"type": "ai", "id": "target"},
                "seq": 1,
            },
            {
                "thread_id": "t1",
                "run_id": "",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"type": "ai", "id": "target"},
                "seq": 2,
            },
        ]
        with patch.object(store, "_read_thread_events", return_value=events) as read_thread_events:
            assert await store.find_latest_ai_message_run_ids("t1", {"target"}, user_id=None) == {"target": "valid-run"}
        read_thread_events.assert_called_once_with("t1")

        with patch.object(store, "_read_thread_events", side_effect=AssertionError("empty input must not read")) as read_thread_events:
            assert await store.find_latest_ai_message_run_ids("t1", set()) == {}
        read_thread_events.assert_not_called()

    @pytest.mark.anyio
    async def test_put_if_absent_is_idempotent(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        first, created = await s.put_if_absent(thread_id="t1", run_id="r1", event_type="run.delivery", category="outputs", content={"presented": 2})
        duplicate, duplicate_created = await s.put_if_absent(thread_id="t1", run_id="r1", event_type="run.delivery", category="outputs", content={"presented": 0})

        assert created is True
        assert duplicate_created is False
        assert duplicate == first
        assert len(await s.list_events("t1", "r1", event_types=["run.delivery"])) == 1

    @pytest.mark.anyio
    async def test_file_at_correct_path(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        assert (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r1.jsonl").exists()

    @pytest.mark.anyio
    async def test_cross_run_messages(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        messages = await s.list_messages("t1")
        assert len(messages) == 2
        assert [m["seq"] for m in messages] == [1, 2]

    @pytest.mark.anyio
    async def test_delete_by_run(self, tmp_path):
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        s = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await s.put(thread_id="t1", run_id="r1", event_type="human_message", category="message")
        await s.put(thread_id="t1", run_id="r2", event_type="human_message", category="message")
        c = await s.delete_by_run("t1", "r2")
        assert c == 1
        assert not (tmp_path / "jsonl" / "threads" / "t1" / "runs" / "r2.jsonl").exists()
        assert await s.count_messages("t1") == 1
