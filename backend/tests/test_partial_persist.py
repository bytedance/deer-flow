"""Tests for the partial-stream persistence pipeline.

Covers:
- ``PartialMessageAccumulator`` chunk aggregation and middleware filtering
- ``find_open_tool_calls`` matching logic
- ``build_closure_tool_messages`` body / id derivation
- ``mark_partial`` marker semantics
- ``append_messages_to_checkpoint`` uuid6 INSERT pattern
- ``persist_partial_on_cancel`` end-to-end orchestration
- ``RunJournal.record_partial_response`` event + token accumulation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from deerflow.agents.middlewares.dangling_tool_call_middleware import INTERRUPTED_TOOL_MESSAGE_CONTENT
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.partial_persist import (
    CHECKPOINT_WRITE_SOURCE,
    PARTIAL_FINISH_REASON,
    PARTIAL_KWARG,
    PartialMessageAccumulator,
    append_messages_to_checkpoint,
    build_closure_tool_messages,
    closure_tool_message_id,
    find_open_tool_calls,
    is_non_lead_chunk,
    mark_partial,
    persist_partial_on_cancel,
)

# ---------------------------------------------------------------------------
# is_non_lead_chunk
# ---------------------------------------------------------------------------


class TestIsNonLeadChunk:
    def test_none_metadata(self):
        assert is_non_lead_chunk(None) is False

    def test_no_tags(self):
        assert is_non_lead_chunk({"langgraph_node": "agent"}) is False

    def test_lead_agent_tag(self):
        assert is_non_lead_chunk({"tags": ["lead_agent"]}) is False

    def test_middleware_title_tag(self):
        assert is_non_lead_chunk({"tags": ["middleware:title"]}) is True

    def test_middleware_anything_tag(self):
        assert is_non_lead_chunk({"tags": ["middleware:summarize"]}) is True

    def test_mixed_tags_with_middleware(self):
        assert is_non_lead_chunk({"tags": ["lead_agent", "middleware:guardrail"]}) is True

    def test_subagent_tag(self):
        assert is_non_lead_chunk({"tags": ["subagent:researcher"]}) is True

    def test_mixed_tags_with_subagent(self):
        assert is_non_lead_chunk({"tags": ["lead_agent", "subagent:researcher"]}) is True


# ---------------------------------------------------------------------------
# PartialMessageAccumulator
# ---------------------------------------------------------------------------


class TestPartialMessageAccumulator:
    def test_starts_empty(self):
        acc = PartialMessageAccumulator()
        assert acc.is_empty()
        assert acc.finalize() == []

    def test_feed_single_chunk(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="hello"))
        assert not acc.is_empty()
        finalized = acc.finalize()
        assert len(finalized) == 1
        assert finalized[0].id == "m1"
        assert finalized[0].content == "hello"

    def test_feed_merges_same_id(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="hel"))
        acc.feed(AIMessageChunk(id="m1", content="lo"))
        finalized = acc.finalize()
        assert len(finalized) == 1
        assert finalized[0].content == "hello"

    def test_feed_separate_ids(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="a"))
        acc.feed(AIMessageChunk(id="m2", content="b"))
        finalized = acc.finalize()
        assert {m.id for m in finalized} == {"m1", "m2"}

    def test_feed_no_id_skipped(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id=None, content="ghost"))
        assert acc.is_empty()

    def test_feed_non_chunk_skipped(self):
        acc = PartialMessageAccumulator()
        acc.feed("not a chunk")
        acc.feed({"some": "dict"})
        assert acc.is_empty()

    def test_feed_middleware_skipped(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="title"), {"tags": ["middleware:title"]})
        assert acc.is_empty()

    def test_feed_subagent_skipped(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="subagent scratch"), {"tags": ["subagent:researcher"]})
        assert acc.is_empty()

    def test_finalize_skip_ids(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="a"))
        acc.feed(AIMessageChunk(id="m2", content="b"))
        finalized = acc.finalize(skip_ids={"m1"})
        assert [m.id for m in finalized] == ["m2"]

    def test_clear(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="x"))
        acc.clear()
        assert acc.is_empty()

    def test_finalize_preserves_tool_call_chunks(self):
        acc = PartialMessageAccumulator()
        # Two chunks of the same tool_call (index=0), the JSON arg accumulates.
        acc.feed(
            AIMessageChunk(
                id="m1",
                content="",
                tool_call_chunks=[{"name": "bash", "args": '{"cmd":"l', "id": "call_1", "index": 0}],
            )
        )
        acc.feed(
            AIMessageChunk(
                id="m1",
                content="",
                tool_call_chunks=[{"name": None, "args": 's"}', "id": None, "index": 0}],
            )
        )
        finalized = acc.finalize()
        assert len(finalized) == 1
        msg = finalized[0]
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "bash"
        assert msg.tool_calls[0]["args"] == {"cmd": "ls"}


# ---------------------------------------------------------------------------
# mark_partial
# ---------------------------------------------------------------------------


class TestMarkPartial:
    def test_sets_interrupted_kwarg(self):
        msg = AIMessage(id="m1", content="x")
        marked = mark_partial(msg)
        assert marked.additional_kwargs.get(PARTIAL_KWARG) is True
        assert marked.additional_kwargs.get("partial") is True

    def test_sets_default_finish_reason(self):
        msg = AIMessage(id="m1", content="x")
        marked = mark_partial(msg)
        assert marked.response_metadata.get("finish_reason") == PARTIAL_FINISH_REASON

    def test_preserves_existing_finish_reason(self):
        msg = AIMessage(id="m1", content="x", response_metadata={"finish_reason": "stop"})
        marked = mark_partial(msg)
        assert marked.response_metadata["finish_reason"] == "stop"

    def test_records_abort_action(self):
        msg = AIMessage(id="m1", content="x")
        marked = mark_partial(msg, abort_action="interrupt")
        assert marked.response_metadata.get("abort_action") == "interrupt"

    def test_normalizes_id_less_tool_call_in_place(self):
        # Fix 3: AIMessage's own tool_call dict gets the fallback id, not
        # just a downstream copy. Without this, the synthetic closure
        # ToolMessage's tool_call_id wouldn't match anything on the AIMessage.
        ai = AIMessage(id="m1", content="x", tool_calls=[{"id": None, "name": "ls", "args": {}}])
        mark_partial(ai)
        assert ai.tool_calls[0]["id"] is not None
        assert ai.tool_calls[0]["id"].startswith("tc_interrupted_")

    def test_normalize_preserves_existing_id(self):
        ai = AIMessage(id="m1", content="x", tool_calls=[{"id": "real_id", "name": "ls", "args": {}}])
        mark_partial(ai)
        assert ai.tool_calls[0]["id"] == "real_id"

    def test_normalize_handles_invalid_tool_calls(self):
        ai = AIMessage(
            id="m1",
            content="x",
            tool_calls=[],
            invalid_tool_calls=[{"id": None, "name": "ls", "args": "{", "error": "bad"}],
        )
        mark_partial(ai)
        assert ai.invalid_tool_calls[0]["id"] is not None
        assert ai.invalid_tool_calls[0]["id"].startswith("tc_interrupted_")


# ---------------------------------------------------------------------------
# find_open_tool_calls
# ---------------------------------------------------------------------------


class TestFindOpenToolCalls:
    def test_empty_messages(self):
        assert find_open_tool_calls([]) == []

    def test_no_ai_messages(self):
        assert find_open_tool_calls([HumanMessage(content="hi")]) == []

    def test_ai_without_tool_calls(self):
        assert find_open_tool_calls([AIMessage(content="hello")]) == []

    def test_ai_with_unclosed_tool_call(self):
        ai = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "bash", "args": {}}])
        open_calls = find_open_tool_calls([ai])
        assert len(open_calls) == 1
        assert open_calls[0]["id"] == "tc1"

    def test_ai_with_matching_tool_message(self):
        ai = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "bash", "args": {}}])
        tm = ToolMessage(content="ok", tool_call_id="tc1")
        assert find_open_tool_calls([ai, tm]) == []

    def test_invalid_tool_call_is_open(self):
        ai = AIMessage(
            content="",
            tool_calls=[],
            invalid_tool_calls=[{"id": "tc1", "name": "bash", "error": "bad json", "args": ""}],
        )
        open_calls = find_open_tool_calls([ai])
        assert len(open_calls) == 1
        assert open_calls[0]["id"] == "tc1"
        assert open_calls[0]["invalid"] is True

    def test_mixed_complete_and_invalid(self):
        ai = AIMessage(
            content="",
            tool_calls=[{"id": "tc_complete", "name": "ls", "args": {}}],
            invalid_tool_calls=[{"id": "tc_invalid", "name": "bash", "error": "bad", "args": ""}],
        )
        open_calls = find_open_tool_calls([ai])
        ids = {tc["id"] for tc in open_calls}
        assert ids == {"tc_complete", "tc_invalid"}

    def test_skips_already_closed_in_prior_turn(self):
        # Turn 1: tool_call closed
        ai1 = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "ls", "args": {}}])
        tm1 = ToolMessage(content="ok", tool_call_id="tc1")
        # Turn 2 (partial): tool_call NOT closed
        ai2 = AIMessage(content="", tool_calls=[{"id": "tc2", "name": "bash", "args": {}}])
        open_calls = find_open_tool_calls([ai1, tm1, ai2])
        assert [tc["id"] for tc in open_calls] == ["tc2"]

    def test_allocates_fallback_id_when_missing(self):
        # find_open_tool_calls itself no longer mutates — id-less tool_calls are
        # skipped. Normalization happens upstream in mark_partial.
        ai = AIMessage(content="", tool_calls=[{"id": None, "name": "ls", "args": {}}])
        open_calls = find_open_tool_calls([ai])
        assert open_calls == []

    def test_returns_after_mark_partial_normalizes_id(self):
        # End-to-end: mark_partial assigns the fallback in place, then
        # find_open_tool_calls sees it as a normal open tool_call.
        ai = AIMessage(id="m1", content="", tool_calls=[{"id": None, "name": "ls", "args": {}}])
        mark_partial(ai)
        open_calls = find_open_tool_calls([ai])
        assert len(open_calls) == 1
        assert open_calls[0]["id"].startswith("tc_interrupted_")
        # Critically: AIMessage's own tool_call dict has the SAME id
        assert ai.tool_calls[0]["id"] == open_calls[0]["id"]


# ---------------------------------------------------------------------------
# closure_tool_message_id / build_closure_tool_messages
# ---------------------------------------------------------------------------


class TestClosureToolMessages:
    def test_closure_id_is_stable(self):
        assert closure_tool_message_id("tc1") == "tm_interrupted_tc1"

    def test_build_for_interrupted_call(self):
        closures = build_closure_tool_messages([{"id": "tc1", "name": "bash", "args": {}}])
        assert len(closures) == 1
        tm = closures[0]
        assert tm.id == "tm_interrupted_tc1"
        assert tm.tool_call_id == "tc1"
        assert tm.name == "bash"
        assert tm.status == "error"
        assert tm.content == INTERRUPTED_TOOL_MESSAGE_CONTENT
        assert tm.additional_kwargs[PARTIAL_KWARG] is True

    def test_build_for_invalid_call_uses_same_interrupted_body(self):
        # In the cancel context, invalid_tool_calls are also "interrupted"
        # (their args JSON was being streamed and got cut off). Using the
        # canonical interrupted body keeps closure semantics consistent.
        closures = build_closure_tool_messages([{"id": "tc1", "name": "bash", "args": {}, "invalid": True, "error": "bad"}])
        assert len(closures) == 1
        assert closures[0].content == INTERRUPTED_TOOL_MESSAGE_CONTENT

    def test_skips_id_less_tool_call(self):
        closures = build_closure_tool_messages([{"id": None, "name": "bash", "args": {}}])
        assert closures == []


# ---------------------------------------------------------------------------
# RunJournal.record_partial_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordPartialResponse:
    async def test_writes_ai_and_tool_events(self):
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        ai = AIMessage(id="m1", content="partial reply")
        tm = ToolMessage(
            id="tm_interrupted_tc1",
            content=INTERRUPTED_TOOL_MESSAGE_CONTENT,
            tool_call_id="tc1",
            status="error",
            name="bash",
        )
        journal.record_partial_response(ai, [tm], abort_action="interrupt")
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        types = [(e["event_type"], e["metadata"].get("interrupted")) for e in events]
        assert ("llm.ai.response", True) in types
        assert ("llm.tool.result", True) in types
        ai_event = next(e for e in events if e["event_type"] == "llm.ai.response")
        assert ai_event["metadata"]["partial"] is True
        assert ai_event["metadata"]["abort_action"] == "interrupt"

    async def test_accumulates_token_usage(self):
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        ai = AIMessage(
            id="m1",
            content="partial",
            usage_metadata={"input_tokens": 10, "output_tokens": 25, "total_tokens": 35},
        )
        journal.record_partial_response(ai, [])
        completion = journal.get_completion_data()
        assert completion["total_input_tokens"] == 10
        assert completion["total_output_tokens"] == 25
        assert completion["total_tokens"] == 35
        assert completion["llm_call_count"] == 1
        assert completion["lead_agent_tokens"] == 35

    async def test_idempotent_on_duplicate_id(self):
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        ai = AIMessage(
            id="m1",
            content="partial",
            usage_metadata={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        )
        journal.record_partial_response(ai, [])
        journal.record_partial_response(ai, [])  # second call should no-op
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        assert sum(1 for e in events if e["event_type"] == "llm.ai.response") == 1
        completion = journal.get_completion_data()
        assert completion["total_tokens"] == 10  # not doubled

    async def test_recorded_ai_message_ids_tracks_writes(self):
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        ai = AIMessage(id="m1", content="x")
        journal.record_partial_response(ai, [])
        assert "m1" in journal.recorded_ai_message_ids


# ---------------------------------------------------------------------------
# append_messages_to_checkpoint
# ---------------------------------------------------------------------------


def _make_checkpoint_tuple(messages: list, *, checkpoint_id: str = "ckpt_old", step: int = 0):
    """Build a minimal aget_tuple return value."""
    return MagicMock(
        checkpoint={
            "id": checkpoint_id,
            "ts": "2026-01-01T00:00:00+00:00",
            "channel_values": {"messages": messages},
            "channel_versions": {"messages": "00000000000000000000000000000001.0.0000000000000000"},
        },
        metadata={"step": step, "source": "loop"},
        config={"configurable": {"thread_id": "t1", "checkpoint_ns": "", "checkpoint_id": checkpoint_id}},
    )


_NO_AGET = object()


def _make_checkpointer_mock(aget_return: Any = _NO_AGET) -> AsyncMock:
    """Build a checkpointer mock with both async API (aget_tuple/aput) and the
    sync ``get_next_version`` helper (not async on the real saver).

    ``aget_return=_NO_AGET`` (default) leaves ``aget_tuple`` un-configured
    so the test must set it explicitly. Pass ``aget_return=None`` for the
    "no checkpoint exists" branch.
    """
    cp = AsyncMock()
    cp.get_next_version = MagicMock(return_value="00000000000000000000000000000002.0.0000000000000000")
    if aget_return is not _NO_AGET:
        cp.aget_tuple.return_value = aget_return
    return cp


@pytest.mark.asyncio
class TestAppendMessagesToCheckpoint:
    async def test_no_checkpointer(self):
        ok = await append_messages_to_checkpoint(None, thread_id="t1", new_messages=[AIMessage(id="m1", content="x")])
        assert ok is False

    async def test_no_new_messages(self):
        cp = _make_checkpointer_mock()
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=[])
        assert ok is False
        cp.aget_tuple.assert_not_called()

    async def test_no_existing_checkpoint(self):
        cp = _make_checkpointer_mock(aget_return=None)
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=[AIMessage(id="m1", content="x")])
        assert ok is False
        cp.aput.assert_not_called()

    async def test_appends_and_writes_new_uuid(self):
        existing = [HumanMessage(id="h1", content="hi")]
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple(existing))
        new = [AIMessage(id="m1", content="partial")]
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=new, abort_action="interrupt")
        assert ok is True
        cp.aput.assert_called_once()
        call_args = cp.aput.call_args
        write_config, checkpoint, metadata, versions = call_args.args
        assert write_config["configurable"]["thread_id"] == "t1"
        assert checkpoint["id"] != "ckpt_old"
        assert checkpoint["channel_values"]["messages"] == existing + new
        # Bumped channel_versions for messages
        assert "messages" in versions
        assert checkpoint["channel_versions"]["messages"] == versions["messages"]
        assert metadata["source"] == "update"
        assert metadata["step"] == 1
        assert CHECKPOINT_WRITE_SOURCE in metadata["writes"]
        assert metadata["writes"][CHECKPOINT_WRITE_SOURCE] == {"message_ids": ["m1"]}
        assert metadata["abort_action"] == "interrupt"

    async def test_round_trips_with_async_sqlite_saver(self, tmp_path):
        from langgraph.checkpoint.base import empty_checkpoint
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = tmp_path / "checkpoints.sqlite"
        thread_id = "thread-sqlite-partial"
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
            await saver.setup()

            seed_checkpoint = empty_checkpoint()
            seed_version = saver.get_next_version(None, None)
            seed_checkpoint["channel_values"] = {"messages": [HumanMessage(id="h1", content="hi")]}
            seed_checkpoint["channel_versions"] = {"messages": seed_version}
            await saver.aput(config, seed_checkpoint, {"source": "input", "step": 0}, {"messages": seed_version})

            new_messages = [
                AIMessage(id="m_partial", content="partial"),
                ToolMessage(id="tm_interrupted_tc1", content=INTERRUPTED_TOOL_MESSAGE_CONTENT, tool_call_id="tc1", status="error"),
            ]
            ok = await append_messages_to_checkpoint(
                saver,
                thread_id=thread_id,
                new_messages=new_messages,
                abort_action="interrupt",
            )

            assert ok is True
            latest = await saver.aget_tuple(config)
            assert latest is not None
            messages = latest.checkpoint["channel_values"]["messages"]
            ids = [getattr(message, "id", None) for message in messages]
            assert ids == ["h1", "m_partial", "tm_interrupted_tc1"]
            assert latest.checkpoint["channel_versions"]["messages"] != seed_version
            assert latest.metadata["writes"][CHECKPOINT_WRITE_SOURCE] == {"message_ids": ["m_partial", "tm_interrupted_tc1"]}

    async def test_dedup_by_id(self):
        existing_ai = AIMessage(id="m1", content="x")
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([existing_ai]))
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=[AIMessage(id="m1", content="x")])
        assert ok is False
        cp.aput.assert_not_called()

    async def test_aget_tuple_failure_returns_false(self):
        cp = _make_checkpointer_mock()
        cp.aget_tuple.side_effect = RuntimeError("DB down")
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=[AIMessage(id="m1", content="x")])
        assert ok is False

    async def test_aput_failure_returns_false(self):
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([]))
        cp.aput.side_effect = RuntimeError("aput failed")
        ok = await append_messages_to_checkpoint(cp, thread_id="t1", new_messages=[AIMessage(id="m1", content="x")])
        assert ok is False


# ---------------------------------------------------------------------------
# persist_partial_on_cancel (end-to-end orchestration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPersistPartialOnCancel:
    async def test_empty_accumulator_is_noop(self):
        acc = PartialMessageAccumulator()
        cp = _make_checkpointer_mock()
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is False
        cp.aget_tuple.assert_not_called()

    async def test_persists_text_only_partial(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="hello ", response_metadata={"model_name": "x"}))
        acc.feed(AIMessageChunk(id="m1", content="world"))

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="hi")]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        await journal.flush()

        # Journal got the AIMessage event with interrupted markers
        events = await store.list_messages_by_run("t1", "r1", limit=100)
        ai_events = [e for e in events if e["event_type"] == "llm.ai.response"]
        assert len(ai_events) == 1
        assert ai_events[0]["metadata"]["interrupted"] is True
        # Checkpoint append got the AIMessage too
        cp.aput.assert_called_once()
        _, checkpoint, _, _ = cp.aput.call_args.args
        messages_written = checkpoint["channel_values"]["messages"]
        ids = [getattr(m, "id", None) for m in messages_written]
        assert "m1" in ids
        # Accumulator cleared after
        assert acc.is_empty()

    async def test_subagent_tagged_partial_is_not_persisted(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m_subagent", content="internal draft"), {"tags": ["subagent:researcher"]})

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="hi")]))

        ok = await persist_partial_on_cancel(
            accumulator=acc,
            journal=journal,
            checkpointer=cp,
            thread_id="t1",
            abort_action="interrupt",
        )
        assert ok is False
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        ai_events = [e for e in events if e["event_type"] == "llm.ai.response"]
        assert ai_events == []
        cp.aput.assert_not_called()

    async def test_closes_open_tool_call(self):
        acc = PartialMessageAccumulator()
        acc.feed(
            AIMessageChunk(
                id="m1",
                content="",
                tool_call_chunks=[{"name": "bash", "args": '{"cmd":"ls"}', "id": "call_1", "index": 0}],
            )
        )

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="run ls")]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        tool_events = [e for e in events if e["event_type"] == "llm.tool.result"]
        assert len(tool_events) == 1
        assert tool_events[0]["metadata"]["synthetic"] is True

        # Checkpoint contains both the AIMessage and the closure ToolMessage
        _, checkpoint, _, _ = cp.aput.call_args.args
        written = checkpoint["channel_values"]["messages"]
        # human + ai + closure_tm = 3
        assert len(written) == 3
        assert any(getattr(m, "tool_call_id", None) == "call_1" for m in written)

    async def test_skips_already_recorded_id(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="already done"))

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        # Simulate prior on_llm_end having recorded m1.
        journal._recorded_ai_message_ids.add("m1")

        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is False
        cp.aput.assert_not_called()

    async def test_works_without_journal(self):
        # Checkpointer-only deployment: partial still lands in checkpoint.
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="hi"))
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=None, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        cp.aput.assert_called_once()

    async def test_journal_failure_does_not_block_checkpoint(self):
        # If record_partial_response raises (e.g. event_store down), the
        # checkpoint append still runs so the next-turn agent context is
        # not corrupted.
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m1", content="hi"))

        broken_journal: Any = MagicMock()
        broken_journal.recorded_ai_message_ids = set()
        broken_journal.record_partial_response.side_effect = RuntimeError("journal down")

        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=broken_journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        cp.aput.assert_called_once()

    # --------------------------------------------------------------------
    # Fix 1: AIMessage already recorded (on_llm_end fired), tool was still
    # executing when cancel landed. Closure must still be written via
    # record_synthetic_closures.
    # --------------------------------------------------------------------
    async def test_writes_orphan_closure_when_tool_was_executing(self):
        # accumulator saw chunks for the AIMessage during streaming.
        acc = PartialMessageAccumulator()
        acc.feed(
            AIMessageChunk(
                id="m_done",
                content="let me run that",
                tool_call_chunks=[{"name": "bash", "args": '{"cmd":"sleep 60"}', "id": "call_b1", "index": 0}],
            )
        )

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        # on_llm_end already fired and recorded the AIMessage in journal
        journal._recorded_ai_message_ids.add("m_done")

        # Checkpoint already has the AIMessage (LangGraph wrote it after the
        # `agent` node completed), but no ToolMessage yet — the tool was
        # still executing when cancel landed.
        completed_ai = AIMessage(
            id="m_done",
            content="let me run that",
            tool_calls=[{"id": "call_b1", "name": "bash", "args": {"cmd": "sleep 60"}}],
        )
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="ls"), completed_ai]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        # AIMessage is NOT re-emitted (it's already in run_events from on_llm_end)
        ai_events = [e for e in events if e["event_type"] == "llm.ai.response"]
        assert ai_events == []
        # Synthetic closure event was written via record_synthetic_closures
        # with the "during_execution" reason marker
        tool_events = [e for e in events if e["event_type"] == "llm.tool.result"]
        assert len(tool_events) == 1
        assert tool_events[0]["metadata"]["interrupted"] is True
        assert tool_events[0]["metadata"]["synthetic"] is True
        assert tool_events[0]["metadata"]["reason"] == "tool_call_interrupted_during_execution"
        assert tool_events[0]["content"]["tool_call_id"] == "call_b1"

        # Checkpoint append: just the closure (no new AIMessage)
        cp.aput.assert_called_once()
        _, ckpt, _, _ = cp.aput.call_args.args
        written = ckpt["channel_values"]["messages"]
        # human + completed_ai + new closure_tm = 3
        assert len(written) == 3
        assert any(getattr(m, "tool_call_id", None) == "call_b1" for m in written)
        # Make sure we did NOT append a second copy of the AIMessage
        ai_count = sum(1 for m in written if isinstance(m, AIMessage) and m.id == "m_done")
        assert ai_count == 1

    # --------------------------------------------------------------------
    # Fix 2: Historical dangling tool_calls (from a prior run or pending
    # HITL state) must NOT be closed by this run's cancel path.
    # --------------------------------------------------------------------
    async def test_does_not_close_historical_dangling_tool_call(self):
        acc = PartialMessageAccumulator()
        # This run's partial is text-only — no tool_calls
        acc.feed(AIMessageChunk(id="m_new", content="just text"))

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r2", thread_id="t1", event_store=store)

        # Existing checkpoint has a dangling tool_call from a prior run /
        # HITL interrupt waiting to resume.
        historical_ai = AIMessage(
            id="m_old",
            content="old",
            tool_calls=[{"id": "call_old", "name": "external", "args": {}}],
        )
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="hi"), historical_ai]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r2", limit=100)
        ai_events = [e for e in events if e["event_type"] == "llm.ai.response"]
        tool_events = [e for e in events if e["event_type"] == "llm.tool.result"]
        assert len(ai_events) == 1
        assert ai_events[0]["content"]["id"] == "m_new"
        # KEY: call_old (not in this run's accumulator) was NOT closed
        assert tool_events == []

        # Checkpoint append: only m_new, no synthetic closure for call_old
        _, ckpt, _, _ = cp.aput.call_args.args
        written = ckpt["channel_values"]["messages"]
        # h1 + m_old + m_new = 3
        assert len(written) == 3
        assert not any(getattr(m, "tool_call_id", None) == "call_old" for m in written)

    # --------------------------------------------------------------------
    # Fix 3 (end-to-end): id-less tool_call from a partial AIMessage gets
    # a fallback id that lands on BOTH the AIMessage and the closure.
    # --------------------------------------------------------------------
    async def test_finalized_ai_message_and_closure_share_normalized_id(self):
        acc = PartialMessageAccumulator()
        acc.feed(
            AIMessageChunk(
                id="m1",
                content="",
                tool_call_chunks=[{"name": "bash", "args": '{"cmd":"ls"}', "id": None, "index": 0}],
            )
        )

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="x")]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is True

        _, ckpt, _, _ = cp.aput.call_args.args
        written = ckpt["channel_values"]["messages"]
        ai_msgs = [m for m in written if isinstance(m, AIMessage)]
        tool_msgs = [m for m in written if isinstance(m, ToolMessage)]
        assert len(ai_msgs) == 1
        assert len(tool_msgs) == 1
        # AIMessage's own tool_call.id matches the closure's tool_call_id
        ai_tc_id = ai_msgs[0].tool_calls[0]["id"]
        assert ai_tc_id is not None
        assert ai_tc_id.startswith("tc_interrupted_")
        assert tool_msgs[0].tool_call_id == ai_tc_id

    # --------------------------------------------------------------------
    # Negative: accumulator has only ids that were already recorded AND
    # their tools all completed. Nothing should be persisted.
    # --------------------------------------------------------------------
    async def test_all_recorded_no_open_calls_is_noop(self):
        acc = PartialMessageAccumulator()
        acc.feed(AIMessageChunk(id="m_done", content="already done"))

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        journal._recorded_ai_message_ids.add("m_done")

        # Existing has the AIMessage but no pending tool_calls
        completed_ai = AIMessage(id="m_done", content="already done")
        cp = _make_checkpointer_mock(aget_return=_make_checkpoint_tuple([HumanMessage(id="h1", content="x"), completed_ai]))

        ok = await persist_partial_on_cancel(accumulator=acc, journal=journal, checkpointer=cp, thread_id="t1", abort_action="interrupt")
        assert ok is False
        cp.aput.assert_not_called()


# ---------------------------------------------------------------------------
# RunJournal.record_synthetic_closures (Fix 1 supporting API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordSyntheticClosures:
    async def test_writes_tool_result_events_with_during_execution_reason(self):
        from langchain_core.messages import ToolMessage as TM

        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        tm = TM(
            id="tm_interrupted_call_1",
            content="[Tool call was interrupted and did not return a result.]",
            tool_call_id="call_1",
            status="error",
            name="bash",
        )
        journal.record_synthetic_closures([tm], abort_action="interrupt")
        await journal.flush()

        events = await store.list_messages_by_run("t1", "r1", limit=100)
        tool_events = [e for e in events if e["event_type"] == "llm.tool.result"]
        assert len(tool_events) == 1
        meta = tool_events[0]["metadata"]
        assert meta["interrupted"] is True
        assert meta["synthetic"] is True
        assert meta["reason"] == "tool_call_interrupted_during_execution"
        assert meta["abort_action"] == "interrupt"

    async def test_no_op_on_empty_list(self):
        store = MemoryRunEventStore()
        journal = RunJournal(run_id="r1", thread_id="t1", event_store=store)
        journal.record_synthetic_closures([])
        await journal.flush()
        events = await store.list_messages_by_run("t1", "r1", limit=100)
        assert events == []
