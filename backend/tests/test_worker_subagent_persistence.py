"""Worker-side persistence of subagent step events (issue #3779).

The worker streams ``task_*`` custom events to the SSE bridge for live display.
``_SubagentEventBuffer`` additionally writes them to the RunEventStore so the
subtask card's full step history survives a reload. This module tests that glue:
recognized events are buffered and flushed via ``put_batch`` (not per-event
``put``, which the store documents as a low-frequency path), unknown chunks are
skipped, a missing store is a no-op, terminal events flush eagerly, and store
failures never bubble into the stream loop.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from deerflow.runtime.runs.worker import _SubagentEventBuffer


def test_worker_imports_first_without_circular_import():
    """Gateway startup imports worker early; importing it first must not trigger
    a circular import through deerflow.subagents (regression for the #3779 fix).

    pytest preloads many modules, so the cycle only reproduces when worker is the
    first deerflow import — hence a clean subprocess.
    """
    repo_backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONPATH": repo_backend}
    result = subprocess.run(
        [sys.executable, "-c", "import deerflow.runtime.runs.worker"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr


class _FakeStore:
    def __init__(self):
        self.puts: list[dict] = []
        self.batches: list[list[dict]] = []

    async def put(self, **kwargs):
        self.puts.append(kwargs)
        return kwargs

    async def put_batch(self, events):
        # Copy so later buffer reuse can't mutate what we recorded.
        self.batches.append([dict(e) for e in events])
        return list(events)


class _BoomStore:
    async def put_batch(self, events):
        raise RuntimeError("db down")


def _running_step(task_id="call_1", message_index=1):
    return {
        "type": "task_running",
        "task_id": task_id,
        "message": {"type": "tool", "name": "web_search", "content": "results"},
        "message_index": message_index,
    }


@pytest.mark.asyncio
async def test_steps_are_buffered_not_put_per_event():
    # Steps must not hit the low-frequency put() path; they accumulate until flush.
    store = _FakeStore()
    buffer = _SubagentEventBuffer(store, "thread_1", "run_1")

    await buffer.add(_running_step(message_index=1))
    await buffer.add(_running_step(message_index=2))

    assert store.puts == []  # never uses the per-event put path
    assert store.batches == []  # nothing flushed yet

    await buffer.flush()

    assert len(store.batches) == 1
    batch = store.batches[0]
    assert [e["metadata"]["message_index"] for e in batch] == [1, 2]
    assert all(e["thread_id"] == "thread_1" and e["run_id"] == "run_1" for e in batch)
    assert all(e["event_type"] == "subagent.step" and e["category"] == "subagent" for e in batch)


@pytest.mark.asyncio
async def test_flush_is_idempotent_when_empty():
    store = _FakeStore()
    buffer = _SubagentEventBuffer(store, "t", "r")

    await buffer.flush()  # nothing buffered
    await buffer.flush()

    assert store.batches == []


@pytest.mark.asyncio
async def test_terminal_event_flushes_eagerly():
    # A completed subagent's steps should be durable promptly, not stuck in the
    # buffer until the whole run ends.
    store = _FakeStore()
    buffer = _SubagentEventBuffer(store, "thread_1", "run_1")

    await buffer.add(_running_step(message_index=1))
    await buffer.add({"type": "task_completed", "task_id": "call_1", "result": "done"})

    assert len(store.batches) == 1
    batch = store.batches[0]
    assert [e["event_type"] for e in batch] == ["subagent.step", "subagent.end"]


@pytest.mark.asyncio
async def test_size_threshold_triggers_flush():
    store = _FakeStore()
    buffer = _SubagentEventBuffer(store, "thread_1", "run_1")

    for i in range(_SubagentEventBuffer.FLUSH_THRESHOLD):
        await buffer.add(_running_step(message_index=i + 1))

    # Reaching the threshold flushes without waiting for the run to end.
    assert len(store.batches) == 1
    assert len(store.batches[0]) == _SubagentEventBuffer.FLUSH_THRESHOLD


@pytest.mark.asyncio
async def test_skips_non_task_chunk():
    store = _FakeStore()
    buffer = _SubagentEventBuffer(store, "t", "r")

    await buffer.add({"type": "messages"})
    await buffer.flush()

    assert store.batches == []


@pytest.mark.asyncio
async def test_missing_store_is_noop():
    # Must not raise when run_events is not configured.
    buffer = _SubagentEventBuffer(None, "t", "r")
    await buffer.add({"type": "task_started", "task_id": "c1"})
    await buffer.flush()


@pytest.mark.asyncio
async def test_store_errors_do_not_propagate():
    # A persistence failure must never break the live stream loop.
    buffer = _SubagentEventBuffer(_BoomStore(), "t", "r")
    await buffer.add(_running_step())
    await buffer.flush()  # BoomStore raises inside; must be swallowed


@pytest.mark.asyncio
async def test_roundtrip_step_is_listable_but_not_in_message_feed():
    # End-to-end against the real in-memory store: a persisted subagent step is
    # retrievable via list_events (fetch-on-expand) yet never leaks into the
    # thread message feed (list_messages), which filters category == "message".
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    store = MemoryRunEventStore()
    buffer = _SubagentEventBuffer(store, "thread_1", "run_1")

    await buffer.add(_running_step(message_index=1))
    await buffer.flush()

    events = await store.list_events("thread_1", "run_1", event_types=["subagent.step"])
    assert len(events) == 1
    assert events[0]["metadata"]["task_id"] == "call_1"

    messages = await store.list_messages("thread_1")
    assert messages == []
