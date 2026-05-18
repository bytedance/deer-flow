"""Tests for partial AI message capture on run interruption.

Covers:
- RunJournal.record_partial_ai_message: skips empty, skips completed, preserves ID
- RunJournal._completed_message_ids tracking via on_llm_end
- _accumulate_ai_chunk helper in worker module
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessageChunk

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.worker import _accumulate_ai_chunk


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    return MemoryRunEventStore()


@pytest.fixture
def journal(store):
    return RunJournal("r1", "t1", store, flush_threshold=100)


def _make_llm_response(content="Hello", msg_id: str | None = None):
    msg = MagicMock()
    msg.type = "ai"
    msg.content = content
    msg.id = msg_id or f"msg-{id(msg)}"
    msg.tool_calls = []
    msg.invalid_tool_calls = []
    msg.response_metadata = {}
    msg.usage_metadata = None
    msg.additional_kwargs = {}
    msg.name = None
    msg.model_dump.return_value = {
        "content": content,
        "additional_kwargs": {},
        "response_metadata": {},
        "type": "ai",
        "name": None,
        "id": msg.id,
        "tool_calls": [],
        "invalid_tool_calls": [],
        "usage_metadata": None,
    }
    gen = MagicMock()
    gen.message = msg
    response = MagicMock()
    response.generations = [[gen]]
    return response, msg.id


# ---------------------------------------------------------------------------
# record_partial_ai_message
# ---------------------------------------------------------------------------


class TestRecordPartialAiMessage:
    @pytest.mark.anyio
    async def test_writes_llm_ai_partial_event(self, journal, store):
        journal.record_partial_ai_message("msg-abc", "Hello world")
        await journal.flush()

        events = await store.list_events("t1", "r1")
        partial = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert len(partial) == 1
        assert partial[0]["category"] == "message"
        assert partial[0]["content"]["content"] == "Hello world"
        assert partial[0]["metadata"]["partial"] is True

    @pytest.mark.anyio
    async def test_preserves_message_id(self, journal, store):
        journal.record_partial_ai_message("msg-xyz", "partial text")
        await journal.flush()

        events = await store.list_events("t1", "r1")
        partial = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert partial[0]["content"]["id"] == "msg-xyz"

    @pytest.mark.anyio
    async def test_skips_empty_content(self, journal, store):
        journal.record_partial_ai_message("msg-abc", "")
        await journal.flush()

        events = await store.list_events("t1", "r1")
        assert not any(e["event_type"] == "llm.ai.partial" for e in events)

    @pytest.mark.anyio
    async def test_skips_completed_message(self, journal, store):
        """If on_llm_end already recorded this message, record_partial must not duplicate it."""
        response, msg_id = _make_llm_response("complete response", msg_id="msg-done")
        journal.on_llm_end(response, run_id=uuid4(), tags=["lead_agent"])

        journal.record_partial_ai_message("msg-done", "partial text")
        await journal.flush()

        events = await store.list_events("t1", "r1")
        assert not any(e["event_type"] == "llm.ai.partial" for e in events)

    @pytest.mark.anyio
    async def test_writes_when_msg_id_is_none(self, journal, store):
        """No ID available (unusual) — should still write the content."""
        journal.record_partial_ai_message(None, "content without id")
        await journal.flush()

        events = await store.list_events("t1", "r1")
        partial = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert len(partial) == 1

    @pytest.mark.anyio
    async def test_included_in_list_messages_by_run(self, journal, store):
        journal.record_partial_ai_message("msg-abc", "partial")
        await journal.flush()

        messages = await store.list_messages_by_run("t1", "r1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.ai.partial"

    def test_caller_default_is_lead_agent(self, journal):
        journal.record_partial_ai_message("msg-abc", "hello")
        assert journal._buffer[0]["metadata"]["caller"] == "lead_agent"

    def test_caller_can_be_overridden(self, journal):
        journal.record_partial_ai_message("msg-abc", "hello", caller="subagent:bash")
        assert journal._buffer[0]["metadata"]["caller"] == "subagent:bash"


# ---------------------------------------------------------------------------
# _completed_message_ids tracking via on_llm_end
# ---------------------------------------------------------------------------


class TestCompletedMessageIdTracking:
    def test_on_llm_end_records_completed_message_id(self, journal):
        response, msg_id = _make_llm_response(msg_id="msg-complete")
        journal.on_llm_end(response, run_id=uuid4(), tags=["lead_agent"])
        assert "msg-complete" in journal._completed_message_ids

    def test_multiple_llm_ends_accumulate_ids(self, journal):
        r1, id1 = _make_llm_response(msg_id="msg-1")
        r2, id2 = _make_llm_response(msg_id="msg-2")
        journal.on_llm_end(r1, run_id=uuid4(), tags=["lead_agent"])
        journal.on_llm_end(r2, run_id=uuid4(), tags=["lead_agent"])
        assert "msg-1" in journal._completed_message_ids
        assert "msg-2" in journal._completed_message_ids

    def test_message_with_no_id_does_not_crash(self, journal):
        response, _ = _make_llm_response(msg_id=None)
        response.generations[0][0].message.id = None
        # Should not raise
        journal.on_llm_end(response, run_id=uuid4(), tags=["lead_agent"])


# ---------------------------------------------------------------------------
# _accumulate_ai_chunk worker helper
# ---------------------------------------------------------------------------


class TestAccumulateAiChunk:
    def _make_chunk(self, content: str, msg_id: str) -> tuple:
        chunk = AIMessageChunk(content=content, id=msg_id)
        return (chunk, {"langgraph_node": "agent"})

    def test_accumulates_text_for_message_id(self):
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("messages", self._make_chunk("Hello", "msg-1"), target)
        _accumulate_ai_chunk("messages", self._make_chunk(" world", "msg-1"), target)
        assert "".join(target["msg-1"]) == "Hello world"

    def test_ignores_non_messages_mode(self):
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("values", {"messages": []}, target)
        _accumulate_ai_chunk("updates", {}, target)
        assert target == {}

    def test_ignores_non_tuple_chunk(self):
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("messages", AIMessageChunk(content="x", id="msg-1"), target)
        assert target == {}

    def test_ignores_non_ai_message_chunk(self):
        from langchain_core.messages import HumanMessage
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("messages", (HumanMessage(content="hi"), {}), target)
        assert target == {}

    def test_ignores_chunk_without_id(self):
        target: dict[str, list[str]] = {}
        chunk = AIMessageChunk(content="hello")
        chunk.id = None
        _accumulate_ai_chunk("messages", (chunk, {}), target)
        assert target == {}

    def test_ignores_empty_content(self):
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("messages", self._make_chunk("", "msg-1"), target)
        assert target == {}

    def test_multiple_messages_tracked_separately(self):
        target: dict[str, list[str]] = {}
        _accumulate_ai_chunk("messages", self._make_chunk("A", "msg-1"), target)
        _accumulate_ai_chunk("messages", self._make_chunk("B", "msg-2"), target)
        _accumulate_ai_chunk("messages", self._make_chunk("C", "msg-1"), target)
        assert "".join(target["msg-1"]) == "AC"
        assert "".join(target["msg-2"]) == "B"
