"""Worker-side persistence of subagent step events (issue #3779).

The worker streams ``task_*`` custom events to the SSE bridge for live display.
``_persist_subagent_event`` additionally writes them to the RunEventStore so the
subtask card's full step history survives a reload. This module tests that glue:
recognized events are persisted, unknown chunks are skipped, a missing store is a
no-op, and store failures never bubble into the stream loop.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from deerflow.runtime.runs.worker import _persist_subagent_event


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

    async def put(self, **kwargs):
        self.puts.append(kwargs)
        return kwargs


class _BoomStore:
    async def put(self, **kwargs):
        raise RuntimeError("db down")


@pytest.mark.asyncio
async def test_persists_task_running_step():
    store = _FakeStore()
    chunk = {
        "type": "task_running",
        "task_id": "call_1",
        "message": {"type": "tool", "name": "web_search", "content": "results"},
        "message_index": 2,
    }

    await _persist_subagent_event(store, "thread_1", "run_1", chunk)

    assert len(store.puts) == 1
    put = store.puts[0]
    assert put["thread_id"] == "thread_1"
    assert put["run_id"] == "run_1"
    assert put["event_type"] == "subagent.step"
    assert put["category"] == "subagent"
    assert put["metadata"] == {"task_id": "call_1", "message_index": 2}


@pytest.mark.asyncio
async def test_skips_non_task_chunk():
    store = _FakeStore()

    await _persist_subagent_event(store, "t", "r", {"type": "messages"})

    assert store.puts == []


@pytest.mark.asyncio
async def test_missing_store_is_noop():
    # Must not raise when run_events is not configured.
    await _persist_subagent_event(None, "t", "r", {"type": "task_started", "task_id": "c1"})


@pytest.mark.asyncio
async def test_store_errors_do_not_propagate():
    # A persistence failure must never break the live stream loop.
    await _persist_subagent_event(_BoomStore(), "t", "r", {"type": "task_started", "task_id": "c1"})


@pytest.mark.asyncio
async def test_roundtrip_step_is_listable_but_not_in_message_feed():
    # End-to-end against the real in-memory store: a persisted subagent step is
    # retrievable via list_events (fetch-on-expand) yet never leaks into the
    # thread message feed (list_messages), which filters category == "message".
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    store = MemoryRunEventStore()
    chunk = {
        "type": "task_running",
        "task_id": "call_1",
        "message": {"type": "tool", "name": "web_search", "content": "results"},
        "message_index": 1,
    }

    await _persist_subagent_event(store, "thread_1", "run_1", chunk)

    events = await store.list_events("thread_1", "run_1", event_types=["subagent.step"])
    assert len(events) == 1
    assert events[0]["metadata"]["task_id"] == "call_1"

    messages = await store.list_messages("thread_1")
    assert messages == []
