"""Tests for RunJournal callback handler.

Uses MemoryRunEventStore as the backend for direct event inspection.
"""

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


@pytest.fixture
def journal_setup():
    store = MemoryRunEventStore()
    j = RunJournal("r1", "t1", store, flush_threshold=100)
    return j, store


def _make_llm_response(content="Hello", usage=None, tool_calls=None, additional_kwargs=None):
    """Create a mock LLM response with a message.

    model_dump() returns checkpoint-aligned format matching real AIMessage.
    """
    msg = MagicMock()
    msg.type = "ai"
    msg.content = content
    msg.id = f"msg-{id(msg)}"
    msg.tool_calls = tool_calls or []
    msg.invalid_tool_calls = []
    msg.response_metadata = {"model_name": "test-model"}
    msg.usage_metadata = usage
    msg.additional_kwargs = additional_kwargs or {}
    msg.name = None
    # model_dump returns checkpoint-aligned format
    msg.model_dump.return_value = {
        "content": content,
        "additional_kwargs": additional_kwargs or {},
        "response_metadata": {"model_name": "test-model"},
        "type": "ai",
        "name": None,
        "id": msg.id,
        "tool_calls": tool_calls or [],
        "invalid_tool_calls": [],
        "usage_metadata": usage,
    }

    gen = MagicMock()
    gen.message = msg

    response = MagicMock()
    response.generations = [[gen]]
    return response


class TestLlmCallbacks:
    @pytest.mark.anyio
    async def test_on_llm_end_produces_trace_event(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Hi"), run_id=run_id, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        trace_events = [e for e in events if e["event_type"] == "llm_response"]
        assert len(trace_events) == 1
        assert trace_events[0]["category"] == "trace"

    @pytest.mark.anyio
    async def test_on_llm_end_lead_agent_produces_ai_message(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Answer"), run_id=run_id, tags=["lead_agent"])
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "ai_message"
        # Content is checkpoint-aligned model_dump format
        assert messages[0]["content"]["type"] == "ai"
        assert messages[0]["content"]["content"] == "Answer"

    @pytest.mark.anyio
    async def test_on_llm_end_with_tool_calls_produces_ai_tool_call(self, journal_setup):
        """LLM response with pending tool_calls should produce ai_tool_call event."""
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_end(
            _make_llm_response("Let me search", tool_calls=[{"id": "call_1", "name": "search", "args": {}}]),
            run_id=run_id,
            tags=["lead_agent"],
        )
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "ai_tool_call"

    @pytest.mark.anyio
    async def test_on_llm_end_subagent_no_ai_message(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["subagent:research"])
        j.on_llm_end(_make_llm_response("Sub answer"), run_id=run_id, tags=["subagent:research"])
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 0

    @pytest.mark.anyio
    async def test_token_accumulation(self, journal_setup):
        j, store = journal_setup
        usage1 = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        usage2 = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
        j.on_llm_end(_make_llm_response("A", usage=usage1), run_id=uuid4(), tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("B", usage=usage2), run_id=uuid4(), tags=["lead_agent"])
        assert j._total_input_tokens == 30
        assert j._total_output_tokens == 15
        assert j._total_tokens == 45
        assert j._llm_call_count == 2

    @pytest.mark.anyio
    async def test_total_tokens_computed_from_input_output(self, journal_setup):
        """If total_tokens is 0, it should be computed from input + output."""
        j, store = journal_setup
        j.on_llm_end(
            _make_llm_response("Hi", usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 0}),
            run_id=uuid4(),
            tags=["lead_agent"],
        )
        assert j._total_tokens == 150
        assert j._lead_agent_tokens == 150

    @pytest.mark.anyio
    async def test_caller_token_classification(self, journal_setup):
        j, store = journal_setup
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        j.on_llm_end(_make_llm_response("A", usage=usage), run_id=uuid4(), tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("B", usage=usage), run_id=uuid4(), tags=["subagent:research"])
        j.on_llm_end(_make_llm_response("C", usage=usage), run_id=uuid4(), tags=["middleware:summarization"])
        assert j._lead_agent_tokens == 15
        assert j._subagent_tokens == 15
        assert j._middleware_tokens == 15

    @pytest.mark.anyio
    async def test_usage_metadata_none_no_crash(self, journal_setup):
        j, store = journal_setup
        j.on_llm_end(_make_llm_response("No usage", usage=None), run_id=uuid4(), tags=["lead_agent"])
        await j.flush()

    @pytest.mark.anyio
    async def test_latency_tracking(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Fast"), run_id=run_id, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        llm_resp = [e for e in events if e["event_type"] == "llm_response"][0]
        assert "latency_ms" in llm_resp["metadata"]
        assert llm_resp["metadata"]["latency_ms"] is not None


class TestLifecycleCallbacks:
    @pytest.mark.anyio
    async def test_chain_start_end_produce_lifecycle_events(self, journal_setup):
        j, store = journal_setup
        j.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=None)
        j.on_chain_end({}, run_id=uuid4(), parent_run_id=None)
        await asyncio.sleep(0.05)
        await j.flush()
        events = await store.list_events("t1", "r1")
        types = [e["event_type"] for e in events if e["category"] == "lifecycle"]
        assert "run_start" in types
        assert "run_end" in types

    @pytest.mark.anyio
    async def test_nested_chain_ignored(self, journal_setup):
        j, store = journal_setup
        parent_id = uuid4()
        j.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=parent_id)
        j.on_chain_end({}, run_id=uuid4(), parent_run_id=parent_id)
        await j.flush()
        events = await store.list_events("t1", "r1")
        lifecycle = [e for e in events if e["category"] == "lifecycle"]
        assert len(lifecycle) == 0


class TestToolCallbacks:
    @pytest.mark.anyio
    async def test_tool_start_end_produce_trace(self, journal_setup):
        j, store = journal_setup
        j.on_tool_start({"name": "web_search"}, "query", run_id=uuid4())
        j.on_tool_end("results", run_id=uuid4(), name="web_search")
        await j.flush()
        events = await store.list_events("t1", "r1")
        trace_types = {e["event_type"] for e in events if e["category"] == "trace"}
        assert "tool_start" in trace_types
        assert "tool_end" in trace_types

    @pytest.mark.anyio
    async def test_on_tool_error(self, journal_setup):
        j, store = journal_setup
        j.on_tool_error(TimeoutError("timeout"), run_id=uuid4(), name="web_fetch")
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert any(e["event_type"] == "tool_error" for e in events)


class TestCustomEvents:
    @pytest.mark.anyio
    async def test_summarization_event(self, journal_setup):
        j, store = journal_setup
        j.on_custom_event(
            "summarization",
            {"summary": "Context was summarized.", "replaced_count": 5, "replaced_message_ids": ["a", "b"]},
            run_id=uuid4(),
        )
        await j.flush()
        events = await store.list_events("t1", "r1")
        trace = [e for e in events if e["event_type"] == "summarization"]
        assert len(trace) == 1
        # Summarization goes to middleware category, not message
        mw_events = [e for e in events if e["event_type"] == "middleware:summarize"]
        assert len(mw_events) == 1
        assert mw_events[0]["category"] == "middleware"
        assert mw_events[0]["content"] == {"role": "system", "content": "Context was summarized."}
        # No message events from summarization
        messages = await store.list_messages("t1")
        assert len(messages) == 0

    @pytest.mark.anyio
    async def test_non_summarization_custom_event(self, journal_setup):
        j, store = journal_setup
        j.on_custom_event("task_running", {"task_id": "t1", "status": "running"}, run_id=uuid4())
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert any(e["event_type"] == "task_running" for e in events)


class TestBufferFlush:
    @pytest.mark.anyio
    async def test_flush_threshold(self, journal_setup):
        j, store = journal_setup
        j._flush_threshold = 3
        j.on_tool_start({"name": "a"}, "x", run_id=uuid4())
        j.on_tool_start({"name": "b"}, "x", run_id=uuid4())
        assert len(j._buffer) == 2
        j.on_tool_start({"name": "c"}, "x", run_id=uuid4())
        await asyncio.sleep(0.1)
        events = await store.list_events("t1", "r1")
        assert len(events) >= 3

    @pytest.mark.anyio
    async def test_events_retained_when_no_loop(self, journal_setup):
        """Events buffered in a sync (no-loop) context should survive
        until the async flush() in the finally block."""
        j, store = journal_setup
        j._flush_threshold = 1

        original = asyncio.get_running_loop

        def no_loop():
            raise RuntimeError("no running event loop")

        asyncio.get_running_loop = no_loop
        try:
            j._put(event_type="llm_response", category="trace", content="test")
        finally:
            asyncio.get_running_loop = original

        assert len(j._buffer) == 1
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert any(e["event_type"] == "llm_response" for e in events)


class TestIdentifyCaller:
    def test_lead_agent_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller({"tags": ["lead_agent"]}) == "lead_agent"

    def test_subagent_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller({"tags": ["subagent:research"]}) == "subagent:research"

    def test_middleware_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller({"tags": ["middleware:summarization"]}) == "middleware:summarization"

    def test_no_tags_returns_lead_agent(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller({"tags": []}) == "lead_agent"
        assert j._identify_caller({}) == "lead_agent"


class TestChainErrorCallback:
    @pytest.mark.anyio
    async def test_on_chain_error_writes_run_error(self, journal_setup):
        j, store = journal_setup
        j.on_chain_error(ValueError("boom"), run_id=uuid4(), parent_run_id=None)
        await asyncio.sleep(0.05)
        await j.flush()
        events = await store.list_events("t1", "r1")
        error_events = [e for e in events if e["event_type"] == "run_error"]
        assert len(error_events) == 1
        assert "boom" in error_events[0]["content"]
        assert error_events[0]["metadata"]["error_type"] == "ValueError"


class TestTokenTrackingDisabled:
    @pytest.mark.anyio
    async def test_track_token_usage_false(self):
        store = MemoryRunEventStore()
        j = RunJournal("r1", "t1", store, track_token_usage=False, flush_threshold=100)
        j.on_llm_end(
            _make_llm_response("X", usage={"input_tokens": 50, "output_tokens": 50, "total_tokens": 100}),
            run_id=uuid4(),
            tags=["lead_agent"],
        )
        data = j.get_completion_data()
        assert data["total_tokens"] == 0
        assert data["llm_call_count"] == 0


class TestConvenienceFields:
    @pytest.mark.anyio
    async def test_last_ai_message_tracks_latest(self, journal_setup):
        j, store = journal_setup
        j.on_llm_end(_make_llm_response("First"), run_id=uuid4(), tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Second"), run_id=uuid4(), tags=["lead_agent"])
        data = j.get_completion_data()
        assert data["last_ai_message"] == "Second"
        assert data["message_count"] == 2

    @pytest.mark.anyio
    async def test_first_human_message_via_set(self, journal_setup):
        j, _ = journal_setup
        j.set_first_human_message("What is AI?")
        data = j.get_completion_data()
        assert data["first_human_message"] == "What is AI?"

    @pytest.mark.anyio
    async def test_get_completion_data(self, journal_setup):
        j, _ = journal_setup
        j._total_tokens = 100
        j._msg_count = 5
        data = j.get_completion_data()
        assert data["total_tokens"] == 100
        assert data["message_count"] == 5


class TestUnknownCallerTokens:
    @pytest.mark.anyio
    async def test_unknown_caller_tokens_go_to_lead(self, journal_setup):
        j, store = journal_setup
        j.on_llm_end(
            _make_llm_response("X", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
            run_id=uuid4(),
            tags=[],
        )
        assert j._lead_agent_tokens == 15


# ---------------------------------------------------------------------------
# SQLite-backed end-to-end test
# ---------------------------------------------------------------------------


class TestDbBackedLifecycle:
    @pytest.mark.anyio
    async def test_full_lifecycle_with_sqlite(self, tmp_path):
        """Full lifecycle with SQLite-backed RunRepository + DbRunEventStore."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.persistence.run import RunRepository
        from deerflow.runtime.events.store.db import DbRunEventStore
        from deerflow.runtime.runs.manager import RunManager

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()

        run_store = RunRepository(sf)
        event_store = DbRunEventStore(sf)
        mgr = RunManager(store=run_store)

        # Create run
        record = await mgr.create("t1", "lead_agent")
        run_id = record.run_id

        # Write human_message (checkpoint-aligned format)
        from langchain_core.messages import HumanMessage

        human_msg = HumanMessage(content="Hello DB")
        await event_store.put(thread_id="t1", run_id=run_id, event_type="human_message", category="message", content=human_msg.model_dump())

        # Simulate journal
        journal = RunJournal(run_id, "t1", event_store, flush_threshold=100)
        journal.set_first_human_message("Hello DB")

        journal.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=None)
        llm_rid = uuid4()
        journal.on_llm_start({"name": "test"}, [], run_id=llm_rid, tags=["lead_agent"])
        journal.on_llm_end(
            _make_llm_response("DB response", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
            run_id=llm_rid,
            tags=["lead_agent"],
        )
        journal.on_chain_end({}, run_id=uuid4(), parent_run_id=None)
        await asyncio.sleep(0.05)
        await journal.flush()

        # Verify run persisted
        row = await run_store.get(run_id)
        assert row is not None
        assert row["status"] == "pending"

        # Update completion
        completion = journal.get_completion_data()
        await run_store.update_run_completion(run_id, status="success", **completion)
        row = await run_store.get(run_id)
        assert row["status"] == "success"
        assert row["total_tokens"] == 15

        # Verify messages from DB (checkpoint-aligned format)
        messages = await event_store.list_messages("t1")
        assert len(messages) == 2
        assert messages[0]["event_type"] == "human_message"
        assert messages[0]["content"]["type"] == "human"
        assert messages[1]["event_type"] == "ai_message"
        assert messages[1]["content"]["type"] == "ai"
        assert messages[1]["content"]["content"] == "DB response"

        # Verify events from DB
        events = await event_store.list_events("t1", run_id)
        event_types = {e["event_type"] for e in events}
        assert "run_start" in event_types
        assert "llm_response" in event_types
        assert "run_end" in event_types

        await close_engine()


class TestDictContentFlag:
    """Verify that content_is_dict metadata flag controls deserialization."""

    @pytest.mark.anyio
    async def test_db_store_str_starting_with_brace_not_deserialized(self, tmp_path):
        """Plain string content starting with { should NOT be deserialized."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()
        store = DbRunEventStore(sf)

        await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="tool_end",
            category="trace",
            content="{not json, just a string}",
        )
        events = await store.list_events("t1", "r1")
        assert events[0]["content"] == "{not json, just a string}"
        assert isinstance(events[0]["content"], str)

        await close_engine()

    @pytest.mark.anyio
    async def test_db_store_str_starting_with_bracket_not_deserialized(self, tmp_path):
        """Plain string content like '[1, 2, 3]' should NOT be deserialized."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()
        store = DbRunEventStore(sf)

        await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="tool_end",
            category="trace",
            content="[1, 2, 3]",
        )
        events = await store.list_events("t1", "r1")
        assert events[0]["content"] == "[1, 2, 3]"
        assert isinstance(events[0]["content"], str)

        await close_engine()


class TestDictContent:
    """Verify that store backends accept str | dict content."""

    @pytest.mark.anyio
    async def test_memory_store_dict_content(self):
        store = MemoryRunEventStore()
        record = await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="ai_message",
            category="message",
            content={"role": "assistant", "content": "Hello"},
        )
        assert record["content"] == {"role": "assistant", "content": "Hello"}
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"] == {"role": "assistant", "content": "Hello"}

    @pytest.mark.anyio
    async def test_memory_store_str_content_unchanged(self):
        store = MemoryRunEventStore()
        record = await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="ai_message",
            category="message",
            content="plain string",
        )
        assert record["content"] == "plain string"
        assert isinstance(record["content"], str)

    @pytest.mark.anyio
    async def test_db_store_dict_content_roundtrip(self, tmp_path):
        """Dict content survives DB roundtrip (JSON serialize on write, deserialize on read)."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()
        store = DbRunEventStore(sf)

        nested = {"role": "assistant", "content": "Hi", "metadata": {"model": "gpt-4", "tokens": [1, 2, 3]}}
        record = await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="ai_message",
            category="message",
            content=nested,
        )
        assert record["content"] == nested

        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"] == nested

        await close_engine()

    @pytest.mark.anyio
    async def test_db_store_trace_dict_truncation(self, tmp_path):
        """Large dict trace content is truncated with metadata flag."""
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        sf = get_session_factory()
        store = DbRunEventStore(sf, max_trace_content=100)

        large_dict = {"role": "assistant", "content": "x" * 200}
        record = await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="llm_end",
            category="trace",
            content=large_dict,
        )
        assert record["metadata"].get("content_truncated") is True
        # Content should be a truncated string (serialized JSON was too long)
        assert isinstance(record["content"], str)
        assert len(record["content"]) <= 100

        await close_engine()


class TestCheckpointAlignedHumanMessage:
    @pytest.mark.anyio
    async def test_human_message_checkpoint_format(self):
        """human_message content uses model_dump() checkpoint format."""
        from langchain_core.messages import HumanMessage

        store = MemoryRunEventStore()
        human_msg = HumanMessage(content="What is AI?")
        await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="human_message",
            category="message",
            content=human_msg.model_dump(),
            metadata={"message_id": "msg_001"},
        )
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"]["type"] == "human"
        assert messages[0]["content"]["content"] == "What is AI?"


class TestCheckpointAlignedMessageFormat:
    @pytest.mark.anyio
    async def test_ai_message_checkpoint_format(self, journal_setup):
        """ai_message content should be checkpoint-aligned model_dump dict."""
        j, store = journal_setup
        j.on_llm_end(_make_llm_response("Answer"), run_id=uuid4(), tags=["lead_agent"])
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"]["type"] == "ai"
        assert messages[0]["content"]["content"] == "Answer"
        assert "response_metadata" in messages[0]["content"]
        assert "additional_kwargs" in messages[0]["content"]

    @pytest.mark.anyio
    async def test_ai_tool_call_event(self, journal_setup):
        """LLM response with tool_calls should produce ai_tool_call with model_dump content."""
        j, store = journal_setup
        tool_calls = [{"id": "call_1", "name": "search", "args": {"query": "test"}}]
        j.on_llm_end(
            _make_llm_response("Let me search", tool_calls=tool_calls),
            run_id=uuid4(),
            tags=["lead_agent"],
        )
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "ai_tool_call"
        assert messages[0]["content"]["type"] == "ai"
        assert messages[0]["content"]["content"] == "Let me search"
        assert len(messages[0]["content"]["tool_calls"]) == 1
        tc = messages[0]["content"]["tool_calls"][0]
        assert tc["id"] == "call_1"
        assert tc["name"] == "search"

    @pytest.mark.anyio
    async def test_ai_tool_call_only_from_lead_agent(self, journal_setup):
        """ai_tool_call should only be emitted for lead_agent, not subagents."""
        j, store = journal_setup
        tool_calls = [{"id": "call_1", "name": "search", "args": {}}]
        j.on_llm_end(
            _make_llm_response("searching", tool_calls=tool_calls),
            run_id=uuid4(),
            tags=["subagent:research"],
        )
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 0


class TestToolResultMessage:
    @pytest.mark.anyio
    async def test_tool_end_produces_tool_result_message(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_tool_start({"name": "web_search"}, '{"query": "test"}', run_id=run_id, tool_call_id="call_abc")
        j.on_tool_end("search results here", run_id=run_id, name="web_search", tool_call_id="call_abc")
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "tool_result"
        # Content is checkpoint-aligned model_dump format
        assert messages[0]["content"]["type"] == "tool"
        assert messages[0]["content"]["tool_call_id"] == "call_abc"
        assert messages[0]["content"]["content"] == "search results here"
        assert messages[0]["content"]["name"] == "web_search"

    @pytest.mark.anyio
    async def test_tool_result_missing_tool_call_id(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_tool_start({"name": "bash"}, "ls", run_id=run_id)
        j.on_tool_end("file1.txt", run_id=run_id, name="bash")
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"]["type"] == "tool"

    @pytest.mark.anyio
    async def test_tool_end_extracts_from_tool_message_object(self, journal_setup):
        """When LangChain passes a ToolMessage object as output, extract fields from it."""
        from langchain_core.messages import ToolMessage

        j, store = journal_setup
        run_id = uuid4()
        tool_msg = ToolMessage(
            content="search results",
            tool_call_id="call_from_obj",
            name="web_search",
            status="success",
        )
        j.on_tool_end(tool_msg, run_id=run_id)
        await j.flush()

        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"]["type"] == "tool"
        assert messages[0]["content"]["tool_call_id"] == "call_from_obj"
        assert messages[0]["content"]["content"] == "search results"
        assert messages[0]["content"]["name"] == "web_search"
        assert messages[0]["metadata"]["tool_name"] == "web_search"
        assert messages[0]["metadata"]["status"] == "success"

        events = await store.list_events("t1", "r1")
        tool_end = [e for e in events if e["event_type"] == "tool_end"][0]
        assert tool_end["metadata"]["tool_call_id"] == "call_from_obj"
        assert tool_end["metadata"]["tool_name"] == "web_search"

    @pytest.mark.anyio
    async def test_tool_message_object_overrides_kwargs(self, journal_setup):
        """ToolMessage object fields take priority over kwargs."""
        from langchain_core.messages import ToolMessage

        j, store = journal_setup
        run_id = uuid4()
        tool_msg = ToolMessage(
            content="result",
            tool_call_id="call_obj",
            name="tool_a",
            status="success",
        )
        # Pass different values in kwargs — ToolMessage should win
        j.on_tool_end(tool_msg, run_id=run_id, name="tool_b", tool_call_id="call_kwarg")
        await j.flush()

        messages = await store.list_messages("t1")
        assert messages[0]["content"]["tool_call_id"] == "call_obj"
        assert messages[0]["content"]["name"] == "tool_a"
        assert messages[0]["metadata"]["tool_name"] == "tool_a"

    @pytest.mark.anyio
    async def test_tool_message_error_status(self, journal_setup):
        """ToolMessage with status='error' propagates status to metadata."""
        from langchain_core.messages import ToolMessage

        j, store = journal_setup
        run_id = uuid4()
        tool_msg = ToolMessage(
            content="something went wrong",
            tool_call_id="call_err",
            name="web_fetch",
            status="error",
        )
        j.on_tool_end(tool_msg, run_id=run_id)
        await j.flush()

        events = await store.list_events("t1", "r1")
        tool_end = [e for e in events if e["event_type"] == "tool_end"][0]
        assert tool_end["metadata"]["status"] == "error"

        messages = await store.list_messages("t1")
        assert messages[0]["content"]["status"] == "error"
        assert messages[0]["metadata"]["status"] == "error"

    @pytest.mark.anyio
    async def test_tool_message_fallback_to_cache(self, journal_setup):
        """If ToolMessage has empty tool_call_id, fall back to cache from on_tool_start."""
        from langchain_core.messages import ToolMessage

        j, store = journal_setup
        run_id = uuid4()
        j.on_tool_start({"name": "bash"}, "ls", run_id=run_id, tool_call_id="call_cached")
        tool_msg = ToolMessage(
            content="file list",
            tool_call_id="",
            name="bash",
        )
        j.on_tool_end(tool_msg, run_id=run_id)
        await j.flush()

        messages = await store.list_messages("t1")
        assert messages[0]["content"]["tool_call_id"] == "call_cached"

    @pytest.mark.anyio
    async def test_tool_error_produces_tool_result_message(self, journal_setup):
        j, store = journal_setup
        j.on_tool_error(TimeoutError("timeout"), run_id=uuid4(), name="web_fetch", tool_call_id="call_1")
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "tool_result"
        assert messages[0]["content"]["type"] == "tool"
        assert messages[0]["content"]["tool_call_id"] == "call_1"
        assert "timeout" in messages[0]["content"]["content"]
        assert messages[0]["content"]["status"] == "error"
        assert messages[0]["metadata"]["status"] == "error"

    @pytest.mark.anyio
    async def test_tool_error_uses_cached_tool_call_id(self, journal_setup):
        """on_tool_error should fall back to cached tool_call_id from on_tool_start."""
        j, store = journal_setup
        run_id = uuid4()
        j.on_tool_start({"name": "web_fetch"}, "url", run_id=run_id, tool_call_id="call_cached")
        j.on_tool_error(TimeoutError("timeout"), run_id=run_id, name="web_fetch")
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["content"]["tool_call_id"] == "call_cached"


def _make_base_messages():
    """Create mock LangChain BaseMessages for on_chat_model_start."""
    sys_msg = MagicMock()
    sys_msg.content = "You are helpful."
    sys_msg.type = "system"
    sys_msg.tool_calls = []
    sys_msg.tool_call_id = None

    user_msg = MagicMock()
    user_msg.content = "Hello"
    user_msg.type = "human"
    user_msg.tool_calls = []
    user_msg.tool_call_id = None

    return [sys_msg, user_msg]


class TestLlmRequestResponse:
    @pytest.mark.anyio
    async def test_llm_request_event(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        messages = _make_base_messages()
        j.on_chat_model_start({"name": "gpt-4o"}, [messages], run_id=run_id, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        req_events = [e for e in events if e["event_type"] == "llm_request"]
        assert len(req_events) == 1
        content = req_events[0]["content"]
        assert content["model"] == "gpt-4o"
        assert len(content["messages"]) == 2
        assert content["messages"][0]["role"] == "system"
        assert content["messages"][1]["role"] == "user"

    @pytest.mark.anyio
    async def test_llm_response_event(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(
            _make_llm_response("Answer", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
            run_id=run_id,
            tags=["lead_agent"],
        )
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert not any(e["event_type"] == "llm_end" for e in events)
        resp_events = [e for e in events if e["event_type"] == "llm_response"]
        assert len(resp_events) == 1
        content = resp_events[0]["content"]
        assert "choices" in content
        assert content["choices"][0]["message"]["role"] == "assistant"
        assert content["choices"][0]["message"]["content"] == "Answer"
        assert content["usage"]["prompt_tokens"] == 10

    @pytest.mark.anyio
    async def test_llm_request_response_paired(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        messages = _make_base_messages()
        j.on_chat_model_start({"name": "gpt-4o"}, [messages], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(
            _make_llm_response("Hi", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
            run_id=run_id,
            tags=["lead_agent"],
        )
        await j.flush()
        events = await store.list_events("t1", "r1")
        req = [e for e in events if e["event_type"] == "llm_request"][0]
        resp = [e for e in events if e["event_type"] == "llm_response"][0]
        assert req["metadata"]["llm_call_index"] == resp["metadata"]["llm_call_index"]

    @pytest.mark.anyio
    async def test_no_llm_start_event(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({"name": "test"}, [], run_id=run_id, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert not any(e["event_type"] == "llm_start" for e in events)


class TestMiddlewareEvents:
    @pytest.mark.anyio
    async def test_record_middleware_uses_middleware_category(self, journal_setup):
        j, store = journal_setup
        j.record_middleware(
            "title",
            name="TitleMiddleware",
            hook="after_model",
            action="generate_title",
            changes={"title": "Test Title", "thread_id": "t1"},
        )
        await j.flush()
        events = await store.list_events("t1", "r1")
        mw_events = [e for e in events if e["event_type"] == "middleware:title"]
        assert len(mw_events) == 1
        assert mw_events[0]["category"] == "middleware"
        assert mw_events[0]["content"]["name"] == "TitleMiddleware"
        assert mw_events[0]["content"]["hook"] == "after_model"
        assert mw_events[0]["content"]["action"] == "generate_title"
        assert mw_events[0]["content"]["changes"]["title"] == "Test Title"

    @pytest.mark.anyio
    async def test_middleware_events_not_in_messages(self, journal_setup):
        """Middleware events should not appear in list_messages()."""
        j, store = journal_setup
        j.record_middleware(
            "title",
            name="TitleMiddleware",
            hook="after_model",
            action="generate_title",
            changes={"title": "Test"},
        )
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 0

    @pytest.mark.anyio
    async def test_middleware_tag_variants(self, journal_setup):
        """Different middleware tags produce distinct event_types."""
        j, store = journal_setup
        j.record_middleware("title", name="TitleMiddleware", hook="after_model", action="generate_title", changes={})
        j.record_middleware("guardrail", name="GuardrailMiddleware", hook="before_tool", action="deny", changes={})
        await j.flush()
        events = await store.list_events("t1", "r1")
        event_types = {e["event_type"] for e in events}
        assert "middleware:title" in event_types
        assert "middleware:guardrail" in event_types


class TestFullRunSequence:
    @pytest.mark.anyio
    async def test_complete_run_event_sequence(self):
        """Simulate a full run: user -> LLM -> tool_call -> tool_result -> LLM -> final reply.

        All message events use checkpoint-aligned model_dump format.
        """
        from langchain_core.messages import HumanMessage

        store = MemoryRunEventStore()
        j = RunJournal("r1", "t1", store, flush_threshold=100)

        # 1. Human message (written by worker, using model_dump format)
        human_msg = HumanMessage(content="Search for quantum computing")
        await store.put(
            thread_id="t1",
            run_id="r1",
            event_type="human_message",
            category="message",
            content=human_msg.model_dump(),
        )
        j.set_first_human_message("Search for quantum computing")

        # 2. Run start
        j.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=None)

        # 3. First LLM call -> tool_calls
        llm1_id = uuid4()
        sys_msg = MagicMock(content="You are helpful.", type="system", tool_calls=[], tool_call_id=None)
        user_msg = MagicMock(content="Search for quantum computing", type="human", tool_calls=[], tool_call_id=None)
        j.on_chat_model_start({"name": "gpt-4o"}, [[sys_msg, user_msg]], run_id=llm1_id, tags=["lead_agent"])
        j.on_llm_end(
            _make_llm_response(
                "Let me search",
                tool_calls=[{"id": "call_1", "name": "web_search", "args": {"query": "quantum computing"}}],
                usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            ),
            run_id=llm1_id,
            tags=["lead_agent"],
        )

        # 4. Tool execution
        tool_id = uuid4()
        j.on_tool_start({"name": "web_search"}, '{"query": "quantum computing"}', run_id=tool_id, tool_call_id="call_1")
        j.on_tool_end("Quantum computing results...", run_id=tool_id, name="web_search", tool_call_id="call_1")

        # 5. Middleware: title generation
        j.record_middleware("title", name="TitleMiddleware", hook="after_model", action="generate_title", changes={"title": "Quantum Computing"})

        # 6. Second LLM call -> final reply
        llm2_id = uuid4()
        j.on_chat_model_start({"name": "gpt-4o"}, [[sys_msg, user_msg]], run_id=llm2_id, tags=["lead_agent"])
        j.on_llm_end(
            _make_llm_response(
                "Here are the results about quantum computing...",
                usage={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
            ),
            run_id=llm2_id,
            tags=["lead_agent"],
        )

        # 7. Run end
        j.on_chain_end({}, run_id=uuid4(), parent_run_id=None)
        await asyncio.sleep(0.05)
        await j.flush()

        # Verify message sequence
        messages = await store.list_messages("t1")
        msg_types = [m["event_type"] for m in messages]
        assert msg_types == ["human_message", "ai_tool_call", "tool_result", "ai_message"]

        # Verify checkpoint-aligned format: all messages use "type" not "role"
        assert messages[0]["content"]["type"] == "human"
        assert messages[0]["content"]["content"] == "Search for quantum computing"
        assert messages[1]["content"]["type"] == "ai"
        assert "tool_calls" in messages[1]["content"]
        assert messages[2]["content"]["type"] == "tool"
        assert messages[2]["content"]["tool_call_id"] == "call_1"
        assert messages[3]["content"]["type"] == "ai"
        assert messages[3]["content"]["content"] == "Here are the results about quantum computing..."

        # Verify trace events
        events = await store.list_events("t1", "r1")
        trace_types = [e["event_type"] for e in events if e["category"] == "trace"]
        assert "llm_request" in trace_types
        assert "llm_response" in trace_types
        assert "tool_start" in trace_types
        assert "tool_end" in trace_types
        assert "llm_start" not in trace_types
        assert "llm_end" not in trace_types

        # Verify middleware events are in their own category
        mw_events = [e for e in events if e["category"] == "middleware"]
        assert len(mw_events) == 1
        assert mw_events[0]["event_type"] == "middleware:title"

        # Verify token accumulation
        data = j.get_completion_data()
        assert data["total_tokens"] == 420  # 120 + 300
        assert data["llm_call_count"] == 2
        assert data["lead_agent_tokens"] == 420
        assert data["message_count"] == 1  # only final ai_message counts
        assert data["last_ai_message"] == "Here are the results about quantum computing..."

        # Verify all message contents are checkpoint-aligned dicts with "type" field
        for m in messages:
            assert isinstance(m["content"], dict)
            assert "type" in m["content"]
