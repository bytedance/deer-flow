"""Tests for RunJournal.record_context_snapshot (context observability M1).

The journal is the transport for the input-side context ledger: it stamps a
context snapshot with the run's ``(thread_id, run_id)`` spine under a dedicated
``category="context"`` so it joins the rest of the run timeline. A separate
guard pins that ``context`` events are never subject to the trace-only
content truncation.
"""

from __future__ import annotations

import pytest

from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


@pytest.mark.asyncio
async def test_record_context_snapshot_emits_context_event_on_run_spine():
    store = MemoryRunEventStore()
    journal = RunJournal(run_id="run-1", thread_id="thread-1", event_store=store)

    payload = {
        "fact_ids": ["f-high", "f-mid"],
        "fact_count": 2,
        "total_facts": 5,
        "sections": ["user_context", "facts"],
        "token_count": 123,
        "max_tokens": 2000,
        "content_hash": "sha256:deadbeef",
    }
    journal.record_context_snapshot("memory", payload=payload)
    await journal.flush()

    events = store._events["thread-1"]
    assert len(events) == 1
    event = events[0]
    assert event["category"] == "context"
    assert event["event_type"] == "context:memory"
    assert event["content"] == payload
    # Joins the rest of the run on the (thread_id, run_id) spine.
    assert event["thread_id"] == "thread-1"
    assert event["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_record_context_snapshot_kind_drives_event_type():
    store = MemoryRunEventStore()
    journal = RunJournal(run_id="run-2", thread_id="thread-2", event_store=store)

    journal.record_context_snapshot("skills", payload={"enabled": ["a", "b"]})
    await journal.flush()

    event = store._events["thread-2"][0]
    assert event["event_type"] == "context:skills"
    assert event["category"] == "context"


def test_context_category_is_not_truncated():
    """F4 guard: only ``category == "trace"`` is truncated to ``max_trace_content``.

    A context snapshot is bounded by construction (ids + counts + budget + hash),
    so it must pass through untouched — otherwise large payloads would be silently
    mangled into invalid JSON. This pins the boundary against regressions in the
    truncation rule.
    """
    store = DbRunEventStore(None, max_trace_content=10)  # type: ignore[arg-type]
    big_payload = {"fact_ids": ["x" * 100], "content_hash": "sha256:" + "a" * 64}

    content, metadata = store._truncate_trace("context", big_payload, None)
    assert content == big_payload  # untouched
    assert "content_truncated" not in metadata

    # Sanity: the same store *does* truncate an oversized trace event.
    trace_content, trace_meta = store._truncate_trace("trace", "a" * 100, None)
    assert trace_meta.get("content_truncated") is True
    assert len(trace_content) <= 10
