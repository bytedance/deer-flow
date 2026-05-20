"""Tests for RunJournal partial message capture on interruption."""

from __future__ import annotations

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


def _make_llm_response(content="Hello"):
    msg = MagicMock()
    msg.type = "ai"
    msg.content = content
    msg.id = f"msg-{id(msg)}"
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
    return response


class TestPartialMessageTracking:
    def test_on_llm_new_token_accumulates_tokens(self, journal_setup):
        j, _ = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("Hello", run_id=run_id)
        j.on_llm_new_token(" world", run_id=run_id)
        assert "".join(j._partial_llm_tokens[str(run_id)]) == "Hello world"

    def test_on_llm_end_clears_partial_tracking(self, journal_setup):
        j, _ = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("partial", run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("complete"), run_id=run_id, tags=["lead_agent"])
        assert str(run_id) not in j._partial_llm_tokens

    @pytest.mark.anyio
    async def test_flush_partial_messages_writes_event(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("Hello", run_id=run_id, tags=["lead_agent"])
        j.on_llm_new_token(" there", run_id=run_id, tags=["lead_agent"])
        j.flush_partial_messages()
        await j.flush()

        events = await store.list_events("t1", "r1")
        partial_events = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert len(partial_events) == 1
        assert partial_events[0]["category"] == "message"
        assert partial_events[0]["content"]["content"] == "Hello there"
        assert partial_events[0]["metadata"]["partial"] is True

    def test_flush_partial_messages_skips_empty_content(self, journal_setup):
        j, _ = journal_setup
        run_id = uuid4()
        j._partial_llm_tokens[str(run_id)] = []
        j._partial_llm_tags[str(run_id)] = None
        j.flush_partial_messages()
        # Buffer should still be empty (no event added)
        assert len(j._buffer) == 0

    def test_flush_partial_messages_clears_tracking(self, journal_setup):
        j, _ = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("token", run_id=run_id)
        j.flush_partial_messages()
        assert len(j._partial_llm_tokens) == 0
        assert len(j._partial_llm_tags) == 0

    @pytest.mark.anyio
    async def test_completed_llm_call_not_in_partial(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("full response", run_id=run_id, tags=["lead_agent"])
        j.on_llm_end(_make_llm_response("full response"), run_id=run_id, tags=["lead_agent"])
        j.flush_partial_messages()
        await j.flush()

        events = await store.list_events("t1", "r1")
        partial_events = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert len(partial_events) == 0

    @pytest.mark.anyio
    async def test_flush_partial_messages_caller_preserved(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("response", run_id=run_id, tags=["subagent:bash"])
        j.flush_partial_messages()
        await j.flush()

        events = await store.list_events("t1", "r1")
        partial_events = [e for e in events if e["event_type"] == "llm.ai.partial"]
        assert len(partial_events) == 1
        assert partial_events[0]["metadata"]["caller"] == "subagent:bash"

    @pytest.mark.anyio
    async def test_flush_partial_messages_included_in_list_messages_by_run(self, journal_setup):
        j, store = journal_setup
        run_id = uuid4()
        j.on_llm_new_token("partial response", run_id=run_id, tags=["lead_agent"])
        j.flush_partial_messages()
        await j.flush()

        messages = await store.list_messages_by_run("t1", "r1")
        assert len(messages) == 1
        assert messages[0]["event_type"] == "llm.ai.partial"
