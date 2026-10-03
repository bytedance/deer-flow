"""P1: skip the summarizer LLM call when the exact input already produced an unchanged summary."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


def _middleware(output: str = "S") -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text=output)
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text=output))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(model=model, trigger=("messages", 4), keep=("messages", 2), token_counter=len)


def _state(summary: str | None = "S", first: str = "u1") -> dict:
    messages = [
        HumanMessage(content=first, id="m1"),
        AIMessage(content="a1", id="m2"),
        HumanMessage(content="u2", id="m3"),
        AIMessage(content="a2", id="m4"),
    ]
    return {"messages": messages, "summary_text": summary}


def _runtime(journal=None) -> SimpleNamespace:
    context = {"thread_id": "t1"}
    if journal is not None:
        context["__run_journal"] = journal
    return SimpleNamespace(context=context)


def _calls(mw) -> int:
    return mw.model.invoke.call_count + mw.model.ainvoke.await_count


def _ids(result) -> tuple:
    return (result.summary_text, [m.id for m in result.messages_to_summarize], [m.id for m in result.preserved_messages])


async def _compact(mw, state, runtime, asynchronous: bool):
    if asynchronous:
        return await mw.acompact_state(state, runtime, force=True)
    return mw.compact_state(state, runtime, force=True)


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_unchanged_window_skips_llm_and_preserves_state(asynchronous):
    mw = _middleware("S")
    state = _state("S")
    snapshot = copy.deepcopy(state)

    first = await _compact(mw, state, _runtime(), asynchronous)
    assert _calls(mw) == 1  # first time the input is seen: LLM is called, proves no-op
    second = await _compact(mw, state, _runtime(), asynchronous)

    assert _calls(mw) == 1  # skipped
    assert second.summary_text == "S" and type(second.summary_text) is str
    assert _ids(second) == _ids(first)  # same compaction outcome as the LLM path
    assert state["summary_text"] == snapshot["summary_text"]
    assert [m.id for m in state["messages"]] == [m.id for m in snapshot["messages"]]  # input untouched
    assert mw.summary_skip_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_changed_window_still_calls_llm(asynchronous):
    mw = _middleware("S")
    await _compact(mw, _state("S"), _runtime(), asynchronous)
    assert _calls(mw) == 1

    await _compact(mw, _state("S", first="different window"), _runtime(), asynchronous)
    assert _calls(mw) == 2  # new messages -> new prompt

    await _compact(mw, _state("older summary"), _runtime(), asynchronous)
    assert _calls(mw) == 3  # new previous summary -> new prompt


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_non_noop_result_is_never_cached(asynchronous):
    mw = _middleware("brand new summary")
    await _compact(mw, _state("S"), _runtime(), asynchronous)
    await _compact(mw, _state("S"), _runtime(), asynchronous)
    assert _calls(mw) == 2
    assert not hasattr(mw, "summary_skip_count")


@pytest.mark.anyio
async def test_sync_and_async_equivalent():
    results = []
    for asynchronous in (False, True):
        mw = _middleware("S")
        state = _state("S")
        await _compact(mw, state, _runtime(), asynchronous)
        results.append((_ids(await _compact(mw, state, _runtime(), asynchronous)), _calls(mw)))
    assert results[0] == results[1]


@pytest.mark.anyio
async def test_skip_is_visible_in_p0_telemetry():
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    mw = _middleware("S")
    await _compact(mw, _state("S"), _runtime(journal), False)
    await _compact(mw, _state("S"), _runtime(journal), False)
    await journal.flush()

    events = [e for e in await store.list_events("t1", "r1") if e["event_type"] == "middleware:summarize"]
    changes = [e["content"]["changes"] for e in events]
    assert [c["llm_call_skipped"] for c in changes] == [False, True]
    assert [c["noop"] for c in changes] == [True, True]  # P0 fields intact
    assert mw.summary_noop_count == 2 and mw.summary_call_count == 2


def test_cache_failure_falls_back_to_llm(monkeypatch):
    mw = _middleware("S")
    mw.compact_state(_state("S"), _runtime(), force=True)

    def boom(*_a, **_k):
        raise RuntimeError("cache broken")

    monkeypatch.setattr(mw, "_noop_prompt_cache_lock", SimpleNamespace(__enter__=boom, __exit__=boom))
    result = mw.compact_state(_state("S"), _runtime(), force=True)
    assert result is not None and result.summary_text == "S"
    assert _calls(mw) == 2  # lookup failed -> normal LLM path

    monkeypatch.setattr(DeerFlowSummarizationMiddleware, "_noop_cache_key", staticmethod(lambda *_a, **_k: None))  # key failure degrades to None
    assert mw.compact_state(_state("S"), _runtime(), force=True).summary_text == "S"
    assert _calls(mw) == 3


def test_telemetry_failure_does_not_change_skip_behavior():
    journal = MagicMock()
    journal.record_middleware.side_effect = RuntimeError("journal down")
    mw = _middleware("S")
    first = mw.compact_state(_state("S"), _runtime(journal), force=True)
    second = mw.compact_state(_state("S"), _runtime(journal), force=True)
    assert _calls(mw) == 1
    assert _ids(second) == _ids(first)
