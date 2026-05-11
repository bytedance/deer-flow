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
        j.on_llm_end(_make_llm_response("Hi"), run_id=run_id, parent_run_id=None, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        trace_events = [e for e in events if e["event_type"] == "llm.ai.response"]
        assert len(trace_events) == 1
        assert trace_events[0]["category"] == "message"

    @pytest.mark.anyio
    async def test_on_llm_end_lead_agent_produces_ai_message(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Answer"), run_id=run_id, parent_run_id=None, tags=["lead_agent"])
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.ai.response"
        # Content is checkpoint-aligned model_dump format
        assert messages[0]["content"]["type"] == "ai"
        assert messages[0]["content"]["content"] == "Answer"

    @pytest.mark.anyio
    async def test_on_llm_end_with_tool_calls_produces_ai_tool_call(self, journal_setup):
        """LLM response with pending tool_calls emits llm.ai.response with tool_calls in content."""
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_end(
            _make_llm_response("Let me search", tool_calls=[{"id": "call_1", "name": "search", "args": {}}]),
            run_id=run_id,
            parent_run_id=None,
            tags=["lead_agent"],
        )
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.ai.response"
        assert len(messages[0]["content"]["tool_calls"]) == 1

    @pytest.mark.anyio
    async def test_on_llm_end_subagent_no_ai_message(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["subagent:research"])
        j.on_llm_end(_make_llm_response("Sub answer"), run_id=run_id, parent_run_id=None, tags=["subagent:research"])
        await j.flush()
        messages = await store.list_messages("t1")
        # subagent responses still emit llm.ai.response with category="message"
        assert len(messages) == 1

    @pytest.mark.anyio
    async def test_token_accumulation(self, journal_setup):
        j, store = journal_setup
        usage1 = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        usage2 = {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
        j.on_llm_end(_make_llm_response("A", usage=usage1), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("B", usage=usage2), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
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
            parent_run_id=None,
            tags=["lead_agent"],
        )
        assert j._total_tokens == 150

    @pytest.mark.anyio
    async def test_caller_token_classification(self, journal_setup):
        j, store = journal_setup
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        j.on_llm_end(_make_llm_response("A", usage=usage), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("B", usage=usage), run_id=uuid4(), parent_run_id=None, tags=["subagent:research"])
        j.on_llm_end(_make_llm_response("C", usage=usage), run_id=uuid4(), parent_run_id=None, tags=["middleware:summarization"])
        # token tracking not broken by caller type
        assert j._total_tokens == 45
        assert j._llm_call_count == 3

    @pytest.mark.anyio
    async def test_usage_metadata_none_no_crash(self, journal_setup):
        j, store = journal_setup
        j.on_llm_end(_make_llm_response("No usage", usage=None), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
        await j.flush()

    @pytest.mark.anyio
    async def test_latency_tracking(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_start({}, [], run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("Fast"), run_id=run_id, parent_run_id=None, tags=["lead_agent"])
        await j.flush()
        events = await store.list_events("t1", "r1")
        llm_resp = [e for e in events if e["event_type"] == "llm.ai.response"][0]
        assert "latency_ms" in llm_resp["metadata"]
        assert llm_resp["metadata"]["latency_ms"] is not None


class TestLifecycleCallbacks:
    @pytest.mark.anyio
    async def test_chain_start_end_produce_trace_events(self, journal_setup):
        j, store = journal_setup
        j.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=None)
        j.on_chain_end({}, run_id=uuid4())
        await asyncio.sleep(0.05)
        await j.flush()
        events = await store.list_events("t1", "r1")
        types = {e["event_type"] for e in events}
        assert "run.start" in types
        assert "run.end" in types

    @pytest.mark.anyio
    async def test_nested_chain_no_run_start(self, journal_setup):
        """Nested chains (parent_run_id set) should NOT produce run.start."""
        j, store = journal_setup
        parent_id = uuid4()
        j.on_chain_start({}, {}, run_id=uuid4(), parent_run_id=parent_id)
        j.on_chain_end({}, run_id=uuid4())
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert not any(e["event_type"] == "run.start" for e in events)


class TestToolCallbacks:
    @pytest.mark.anyio
    async def test_tool_end_with_tool_message(self, journal_setup):
        """on_tool_end with a ToolMessage stores it as llm.tool.result."""
        from langchain_core.messages import ToolMessage

        j, store = journal_setup
        tool_msg = ToolMessage(content="results", tool_call_id="call_1", name="web_search")
        j.on_tool_end(tool_msg, run_id=uuid4())
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.tool.result"
        assert messages[0]["content"]["type"] == "tool"

    @pytest.mark.anyio
    async def test_tool_end_with_command_unwraps_tool_message(self, journal_setup):
        """on_tool_end with Command(update={'messages':[ToolMessage]}) unwraps inner message."""
        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        j, store = journal_setup
        inner = ToolMessage(content="file list", tool_call_id="call_2", name="present_files")
        cmd = Command(update={"messages": [inner]})
        j.on_tool_end(cmd, run_id=uuid4())
        await j.flush()
        messages = await store.list_messages("t1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.tool.result"
        assert messages[0]["content"]["content"] == "file list"

    @pytest.mark.anyio
    async def test_on_tool_error_no_crash(self, journal_setup):
        """on_tool_error should not crash (no event emitted by default)."""
        j, store = journal_setup
        j.on_tool_error(TimeoutError("timeout"), run_id=uuid4(), name="web_fetch")
        await j.flush()
        # Base implementation does not emit tool_error — just verify no crash
        events = await store.list_events("t1", "r1")
        assert isinstance(events, list)


class TestCustomEvents:
    @pytest.mark.anyio
    async def test_on_custom_event_not_implemented(self, journal_setup):
        """RunJournal does not implement on_custom_event — no crash expected."""
        j, store = journal_setup
        # BaseCallbackHandler.on_custom_event is a no-op by default
        j.on_custom_event("task_running", {"task_id": "t1"}, run_id=uuid4())
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert isinstance(events, list)


class TestBufferFlush:
    @pytest.mark.anyio
    async def test_flush_threshold(self, journal_setup):
        j, store = journal_setup
        j._flush_threshold = 2
        # Each on_llm_end emits 1 event
        j.on_llm_end(_make_llm_response("A"), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
        assert len(j._buffer) == 1
        j.on_llm_end(_make_llm_response("B"), run_id=uuid4(), parent_run_id=None, tags=["lead_agent"])
        # At threshold the buffer should have been flushed asynchronously
        await asyncio.sleep(0.1)
        events = await store.list_events("t1", "r1")
        assert len(events) >= 2

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
            j._put(event_type="llm.ai.response", category="message", content="test")
        finally:
            asyncio.get_running_loop = original

        assert len(j._buffer) == 1
        await j.flush()
        events = await store.list_events("t1", "r1")
        assert any(e["event_type"] == "llm.ai.response" for e in events)


class TestIdentifyCaller:
    def test_lead_agent_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller(["lead_agent"]) == "lead_agent"

    def test_subagent_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller(["subagent:research"]) == "subagent:research"

    def test_middleware_tag(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller(["middleware:summarization"]) == "middleware:summarization"

    def test_no_tags_returns_lead_agent(self, journal_setup):
        j, _ = journal_setup
        assert j._identify_caller([]) == "lead_agent"
        assert j._identify_caller(None) == "lead_agent"


class TestChainErrorCallback:
    @pytest.mark.anyio
    async def test_on_chain_error_writes_run_error(self, journal_setup):
        j, store = journal_setup
        j.on_chain_error(ValueError("boom"), run_id=uuid4())
        await asyncio.sleep(0.05)
        await j.flush()
        events = await store.list_events("t1", "r1")
        error_events = [e for e in events if e["event_type"] == "run.error"]
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
            parent_run_id=None,
            tags=["lead_agent"],
        )
        data = j.get_completion_data()
        assert data["total_tokens"] == 0
        assert data["llm_call_count"] == 0


class TestConvenienceFields:
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


class TestChatModelStartHumanMessage:
    """Tests for on_chat_model_start extracting the first human message."""

    @pytest.mark.anyio
    async def test_extracts_first_human_message(self, journal_setup):
        """on_chat_model_start captures the first HumanMessage from prompts."""
        from langchain_core.messages import AIMessage, HumanMessage

        j, store = journal_setup
        messages_batch = [
            [HumanMessage(content="What is AI?"), AIMessage(content="Hi there")],
        ]
        j.on_chat_model_start({}, messages_batch, run_id=uuid4(), tags=["lead_agent"])
        await j.flush()

        assert j._first_human_msg == "What is AI?"
        events = await store.list_events("t1", "r1")
        human_events = [e for e in events if e["event_type"] == "llm.human.input"]
        assert len(human_events) == 1
        assert human_events[0]["content"]["content"] == "What is AI?"

    @pytest.mark.anyio
    async def test_skips_summary_named_human_messages(self, journal_setup):
        """HumanMessages with name='summary' are skipped."""
        from langchain_core.messages import HumanMessage

        j, store = journal_setup
        messages_batch = [
            [HumanMessage(content="Summarized context", name="summary"), HumanMessage(content="Real question")],
        ]
        j.on_chat_model_start({}, messages_batch, run_id=uuid4(), tags=["lead_agent"])
        await j.flush()

        assert j._first_human_msg == "Real question"

    @pytest.mark.anyio
    async def test_only_first_human_message_captured(self, journal_setup):
        """Subsequent on_chat_model_start calls do not overwrite the first message."""
        from langchain_core.messages import HumanMessage

        j, store = journal_setup
        j.on_chat_model_start({}, [[HumanMessage(content="First question")]], run_id=uuid4(), tags=["lead_agent"])
        j.on_chat_model_start({}, [[HumanMessage(content="Second question")]], run_id=uuid4(), tags=["lead_agent"])
        await j.flush()

        assert j._first_human_msg == "First question"
        events = await store.list_events("t1", "r1")
        human_events = [e for e in events if e["event_type"] == "llm.human.input"]
        assert len(human_events) == 1

    @pytest.mark.anyio
    async def test_empty_messages_no_crash(self, journal_setup):
        """on_chat_model_start with empty messages does not crash."""
        j, store = journal_setup
        j.on_chat_model_start({}, [], run_id=uuid4(), tags=["lead_agent"])
        await j.flush()
        assert j._first_human_msg is None
