"""P0 per-LLM-call telemetry: observation only, fail-soft."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


def _response(*, usage=None, response_metadata=None, additional_kwargs=None) -> LLMResult:
    message = AIMessage(content="hello", usage_metadata=usage, response_metadata=response_metadata or {}, additional_kwargs=additional_kwargs or {})
    return LLMResult(generations=[[ChatGeneration(message=message)]])


async def _events(journal: RunJournal, store: MemoryRunEventStore, event_type: str) -> list[dict]:
    await journal.flush()
    return [e for e in await store.list_events("t1", "r1") if e["event_type"] == event_type]


@pytest.mark.anyio
async def test_normal_call_records_telemetry_and_rendered_request_size():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid = uuid4()
    messages = [[SystemMessage(content="sys"), HumanMessage(content="question")]]
    journal.on_chat_model_start(
        {"id": ["langchain", "ChatAnthropic"]},
        messages,
        run_id=rid,
        tags=["lead_agent"],
        metadata={"ls_provider": "anthropic", "ls_model_name": "claude-x"},
        invocation_params={"tools": [{"name": "t", "description": "d"}]},
    )
    journal.on_llm_end(
        _response(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, response_metadata={"stop_reason": "end_turn", "model_name": "claude-x-1"}),
        run_id=rid,
        tags=["lead_agent"],
    )

    (event,) = await _events(journal, store, "llm.ai.response")
    meta = event["metadata"]
    assert meta["langchain_run_id"] == str(rid)
    assert meta["caller"] == "lead_agent"
    assert meta["caller_category"] == "lead_agent"
    assert meta["provider"] == "anthropic"
    assert meta["model"] == "claude-x-1"
    assert meta["stop_reason"] == "end_turn"
    assert (meta["input_tokens"], meta["output_tokens"], meta["total_tokens"]) == (10, 5, 15)
    assert meta["request_message_chars"] == len("sys") + len("question")
    assert meta["request_message_count"] == 2
    assert meta["request_tools_chars"] > 0
    assert meta["request_chars"] == meta["request_message_chars"] + meta["request_tools_chars"]
    assert event["thread_id"] == "t1" and event["run_id"] == "r1" and event["created_at"]


@pytest.mark.anyio
async def test_unavailable_values_are_none_not_fabricated():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid = uuid4()
    journal.on_llm_end(_response(), run_id=rid, tags=None)  # no on_chat_model_start

    (event,) = await _events(journal, store, "llm.ai.response")
    meta = event["metadata"]
    assert meta["stop_reason"] is None
    assert meta["input_tokens"] is None
    assert meta["provider"] is None
    assert "request_chars" not in meta


@pytest.mark.anyio
async def test_middleware_and_fallback_caller_classification():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    mid, fb = uuid4(), uuid4()
    journal.on_llm_end(_response(), run_id=mid, tags=["middleware:summarize"])
    journal.on_llm_end(_response(additional_kwargs={"deerflow_error_fallback": True}), run_id=fb, tags=["lead_agent"])

    events = await _events(journal, store, "llm.ai.response")
    by_run = {e["metadata"]["langchain_run_id"]: e["metadata"] for e in events}
    assert by_run[str(mid)]["caller_category"] == "middleware"
    assert by_run[str(fb)]["caller_category"] == "fallback"
    assert by_run[str(fb)]["status"] == "fallback"


@pytest.mark.anyio
async def test_llm_error_is_recorded_with_status():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid = uuid4()
    journal.on_chat_model_start({}, [[HumanMessage(content="abc")]], run_id=rid, tags=["middleware:title"])
    journal.on_llm_error(RuntimeError("boom"), run_id=rid, tags=["middleware:title"])

    (event,) = await _events(journal, store, "llm.error")
    assert event["metadata"]["status"] == "error"
    assert event["metadata"]["caller_category"] == "middleware"
    assert event["metadata"]["request_chars"] == 3
    assert event["content"] == "boom"


@pytest.mark.anyio
async def test_telemetry_failure_does_not_affect_call_or_event(monkeypatch):
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)

    def explode(*_a, **_k):
        raise RuntimeError("telemetry broken")

    monkeypatch.setattr("deerflow.runtime.journal._rendered_request_size", explode)
    monkeypatch.setattr("deerflow.runtime.journal._llm_caller_category", explode)
    rid = uuid4()
    journal.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=rid, tags=["lead_agent"])  # must not raise
    usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    journal.on_llm_end(_response(usage=usage), run_id=rid, tags=["lead_agent"])  # must not raise

    (event,) = await _events(journal, store, "llm.ai.response")
    assert event["metadata"]["usage"] == usage  # pre-existing fields intact
    assert event["metadata"]["caller"] == "lead_agent"
    assert "langchain_run_id" not in event["metadata"]
    assert journal._total_tokens == 5


@pytest.mark.anyio
async def test_llm_error_without_prior_start_records_unavailable_request_size():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid = uuid4()
    journal.on_llm_error(ValueError("bad"), run_id=rid, tags=["subagent:general-purpose"])  # no on_chat_model_start

    (event,) = await _events(journal, store, "llm.error")
    meta = event["metadata"]
    assert meta["status"] == "error"
    assert meta["caller"] == "subagent:general-purpose"
    assert meta["caller_category"] == "subagent"
    assert meta["error_type"] == "ValueError"
    assert meta["provider"] is None and meta["model"] is None
    assert "request_chars" not in meta  # unavailable, not fabricated


@pytest.mark.anyio
@pytest.mark.parametrize(
    "initial_usage",
    [None, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}],
    ids=["missing-usage", "zero-usage"],
)
async def test_replayed_on_llm_end_keeps_canonical_request_metadata(initial_usage):
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid, parent_id = uuid4(), uuid4()
    journal.on_chat_model_start(
        {},
        [[HumanMessage(content="question")]],
        run_id=rid,
        tags=["lead_agent"],
        metadata={"ls_provider": "anthropic", "ls_model_name": "requested-model"},
    )
    response_metadata = {"model_name": "canonical-model", "finish_reason": "stop"}
    # The first callback has missing or zero usage; the adjacent replay fills it in.
    journal.on_llm_end(_response(usage=initial_usage, response_metadata=response_metadata), run_id=rid, parent_run_id=parent_id, tags=["lead_agent"])
    assert journal._pending_llm_response is not None
    canonical_metadata = dict(journal._pending_llm_response.events[0]["metadata"])
    usage = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    journal.on_llm_end(
        _response(
            usage=usage,
            response_metadata={"model_name": "replay-model", "finish_reason": "length"},
            additional_kwargs={"deerflow_error_fallback": True, "error_detail": "replay fallback"},
        ),
        run_id=rid,
        parent_run_id=uuid4(),
        tags=["middleware:summarize"],
    )

    (event,) = await _events(journal, store, "llm.ai.response")
    meta = event["metadata"]
    assert meta == {**canonical_metadata, "usage": usage, **usage}
    assert event["content"]["usage_metadata"] == usage
    assert event["content"]["response_metadata"] == response_metadata
    assert meta["request_message_chars"] == len("question")  # canonical request size preserved
    assert meta["request_message_count"] == 1
    assert meta["langchain_run_id"] == str(rid)
    assert meta["langchain_parent_run_id"] == str(parent_id)
    assert meta["caller_category"] == "lead_agent" and meta["status"] == "ok"
    assert meta["model"] == "canonical-model" and meta["stop_reason"] == "stop"
    assert not journal.had_llm_error_fallback
    assert journal.get_completion_data()["total_tokens"] == 10


@pytest.mark.anyio
@pytest.mark.parametrize(
    "initial_usage",
    [None, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}],
    ids=["missing-usage", "zero-usage"],
)
async def test_usage_replay_after_flush_keeps_committed_telemetry(initial_usage):
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    rid = uuid4()
    journal.on_llm_end(_response(usage=initial_usage), run_id=rid, tags=["lead_agent"])
    (canonical_event,) = await _events(journal, store, "llm.ai.response")
    canonical_event = deepcopy(canonical_event)

    usage = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    journal.on_llm_end(_response(usage=usage), run_id=rid, tags=["lead_agent"])

    (event,) = await _events(journal, store, "llm.ai.response")
    assert event == canonical_event
    assert journal.get_completion_data()["total_tokens"] == 10


@pytest.mark.anyio
async def test_telemetry_metadata_round_trips_through_db_store(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    try:
        store = DbRunEventStore(get_session_factory())
        journal = RunJournal("r1", "t1", store, flush_threshold=100)
        ok_id, err_id = uuid4(), uuid4()
        journal.on_chat_model_start({}, [[HumanMessage(content="hello")]], run_id=ok_id, tags=["lead_agent"], metadata={"ls_provider": "anthropic"})
        journal.on_llm_end(_response(usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}, response_metadata={"stop_reason": "end_turn"}), run_id=ok_id, tags=["lead_agent"])
        journal.on_chat_model_start({}, [[HumanMessage(content="abc")]], run_id=err_id, tags=["middleware:title"])
        journal.on_llm_error(RuntimeError("boom"), run_id=err_id, tags=["middleware:title"])
        journal.record_middleware("summarize", name="DeerFlowSummarizationMiddleware", hook="before_model", action="summary_result", changes={"noop": False})
        await journal.flush()

        events = await store.list_events("t1", "r1")
        by_type = {e["event_type"]: e for e in events}
        ai = by_type["llm.ai.response"]["metadata"]
        assert ai["langchain_run_id"] == str(ok_id) and ai["provider"] == "anthropic" and ai["stop_reason"] == "end_turn"
        assert ai["input_tokens"] == 2 and ai["request_chars"] == len("hello")
        err = by_type["llm.error"]["metadata"]
        assert err["status"] == "error" and err["caller_category"] == "middleware" and err["request_chars"] == 3
        assert by_type["middleware:summarize"]["content"]["changes"] == {"noop": False}
    finally:
        await close_engine()


def _summarizer(text: str) -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text=text)
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text=text))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(model=model, trigger=("messages", 4), keep=("messages", 2), token_counter=len)


def _state(summary: str | None) -> dict:
    messages = [HumanMessage(content="u1"), AIMessage(content="a1"), HumanMessage(content="u2"), AIMessage(content="a2")]
    return {"messages": messages, "summary_text": summary}


@pytest.mark.anyio
async def test_summarization_noop_detected_and_call_not_skipped():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    runtime = SimpleNamespace(context={"thread_id": "t1", "__run_journal": journal})
    middleware = _summarizer("same summary")

    result = middleware.compact_state(_state("same summary"), runtime, force=True)
    assert result is not None and result.summary_text == "same summary"  # behavior unchanged
    assert middleware.model.invoke.call_count == 1  # call NOT skipped
    assert middleware.summary_noop_count == 1

    middleware.compact_state(_state("different"), runtime, force=True)
    middleware.compact_state(_state(None), runtime, force=True)
    assert middleware.summary_noop_count == 1
    assert middleware.summary_call_count == 3

    events = await _events(journal, store, "middleware:summarize")
    assert [e["content"]["changes"]["noop"] for e in events] == [True, False, False]


def test_summarization_telemetry_failure_does_not_break_compaction():
    journal = MagicMock()
    journal.record_middleware.side_effect = RuntimeError("journal down")
    runtime = SimpleNamespace(context={"thread_id": "t1", "__run_journal": journal})
    middleware = _summarizer("s")

    result = middleware.compact_state(_state(None), runtime, force=True)

    assert result is not None and result.summary_text == "s"
