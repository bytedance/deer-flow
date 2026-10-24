"""P1: skip the summarizer LLM call when the exact input already produced an unchanged summary."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


def _model(output: str = "S"):
    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text=output)
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text=output))
    model.with_config.return_value = model
    return model


def _middleware(output: str = "S", **kwargs) -> DeerFlowSummarizationMiddleware:
    return DeerFlowSummarizationMiddleware(model=_model(output), trigger=("messages", 4), keep=("messages", 2), token_counter=len, **kwargs)


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


def test_summary_counters_start_at_zero():
    mw = _middleware()
    assert (mw.summary_call_count, mw.summary_noop_count, mw.summary_skip_count) == (0, 0, 0)


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
    assert mw.summary_skip_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["exception", "blank"])
async def test_fallback_noop_does_not_hide_primary_recovery(asynchronous, failure):
    fallback = _model("S")
    mw = _middleware(configured_model_name="summary-model", run_model_name="run-model", prebuilt_models={"run-model": fallback})
    first_response = RuntimeError("primary temporarily unavailable") if failure == "exception" else SimpleNamespace(text=" \n ")
    mw.model.invoke.side_effect = [first_response, SimpleNamespace(text="recovered primary summary")]
    mw.model.ainvoke.side_effect = [first_response, SimpleNamespace(text="recovered primary summary")]
    state = _state("S")
    snapshot = copy.deepcopy(state)

    first = await _compact(mw, state, _runtime(), asynchronous)
    second = await _compact(mw, state, _runtime(), asynchronous)

    assert first.summary_text == "S"
    assert second.summary_text == "recovered primary summary"
    assert _calls(mw) == 2
    assert fallback.invoke.call_count + fallback.ainvoke.await_count == 1
    assert _ids(first)[1:] == _ids(second)[1:]
    assert state == snapshot
    assert mw.summary_skip_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_primary_noop_with_fallback_configured_still_skips(asynchronous):
    fallback = _model("fallback summary")
    mw = _middleware(configured_model_name="summary-model", run_model_name="run-model", prebuilt_models={"run-model": fallback})

    first = await _compact(mw, _state("S"), _runtime(), asynchronous)
    second = await _compact(mw, _state("S"), _runtime(), asynchronous)

    assert _ids(first) == _ids(second)
    assert _calls(mw) == 1
    fallback.invoke.assert_not_called()
    fallback.ainvoke.assert_not_awaited()
    assert mw.summary_skip_count == 1


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
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_skip_is_visible_in_p0_telemetry(asynchronous):
    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    mw = _middleware("S")
    await _compact(mw, _state("S"), _runtime(journal), asynchronous)
    await _compact(mw, _state("S"), _runtime(journal), asynchronous)
    await journal.flush()

    events = [e for e in await store.list_events("t1", "r1") if e["event_type"] == "middleware:summarize"]
    changes = [e["content"]["changes"] for e in events]
    assert [c["llm_call_skipped"] for c in changes] == [False, True]
    assert [c["noop"] for c in changes] == [True, True]  # P0 fields intact
    assert [c["call_count"] for c in changes] == [1, 2]
    assert [c["skip_count"] for c in changes] == [0, 1]
    assert [c["noop_count"] for c in changes] == [1, 2]
    assert mw.summary_noop_count == 2 and mw.summary_call_count == 2
    assert mw.summary_skip_count == 1


def test_concurrent_compactions_keep_consistent_counter_snapshots():
    first_waiting = threading.Event()
    release_first = threading.Event()
    journal = MagicMock()

    class PausedContext(dict):
        def get(self, key, default=None):
            if key == "__run_journal":
                first_waiting.set()
                assert release_first.wait(timeout=5)
            return super().get(key, default)

    mw = _middleware("S")
    runtime = SimpleNamespace(context=PausedContext(thread_id="t1", __run_journal=journal))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(mw.compact_state, _state("S"), runtime, force=True)
        try:
            assert first_waiting.wait(timeout=5)
            second = executor.submit(mw.compact_state, _state("S"), _runtime(journal), force=True)
            assert second.result(timeout=5) is not None
        finally:
            release_first.set()
        assert first.result(timeout=5) is not None

    changes = [call.kwargs["changes"] for call in journal.record_middleware.call_args_list]
    assert sorted((c["call_count"], c["skip_count"], c["noop_count"]) for c in changes) == [(1, 0, 1), (2, 1, 2)]
    assert (mw.summary_call_count, mw.summary_skip_count, mw.summary_noop_count) == (2, 1, 2)
    assert _calls(mw) == 1


def test_cache_failure_falls_back_to_llm(monkeypatch):
    mw = _middleware("S")
    mw.compact_state(_state("S"), _runtime(), force=True)

    cache_lock = mw._noop_prompt_cache_lock
    broken_lock = MagicMock()
    broken_lock.__enter__.side_effect = RuntimeError("cache broken")
    monkeypatch.setattr(mw, "_noop_prompt_cache_lock", broken_lock)
    result = mw.compact_state(_state("S"), _runtime(), force=True)
    assert result is not None and result.summary_text == "S"
    assert _calls(mw) == 2  # lookup failed -> normal LLM path
    assert broken_lock.__enter__.call_count == 2  # lookup and store both exercise the injected exception
    broken_lock.__exit__.assert_not_called()

    monkeypatch.setattr(mw, "_noop_prompt_cache_lock", cache_lock)
    broken_hash = MagicMock(side_effect=RuntimeError("cache key broken"))
    monkeypatch.setattr("deerflow.agents.middlewares.summarization_middleware.hashlib", SimpleNamespace(sha256=broken_hash))
    assert mw.compact_state(_state("S"), _runtime(), force=True).summary_text == "S"
    assert _calls(mw) == 3
    broken_hash.assert_called_once()


def test_telemetry_failure_does_not_change_skip_behavior():
    journal = MagicMock()
    journal.record_middleware.side_effect = RuntimeError("journal down")
    mw = _middleware("S")
    first = mw.compact_state(_state("S"), _runtime(journal), force=True)
    second = mw.compact_state(_state("S"), _runtime(journal), force=True)
    assert _calls(mw) == 1
    assert _ids(second) == _ids(first)
