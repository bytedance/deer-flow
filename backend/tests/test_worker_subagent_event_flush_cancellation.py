from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.worker import _SubagentEventBuffer


class _BlockingStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = fail
        self.batches: list[list[dict]] = []

    async def put_batch(self, events):
        self.entered.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("event store write failed")
        self.batches.append([dict(event) for event in events])
        return list(events)


def _buffer(store: _BlockingStore) -> _SubagentEventBuffer:
    buffer = _SubagentEventBuffer(store, "thread-1", "run-1")
    buffer._pending.append(
        {
            "thread_id": "thread-1",
            "run_id": "run-1",
            "event_type": "subagent.step",
            "category": "subagent",
            "content": {"task_id": "task-1"},
        }
    )
    return buffer


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_inflight_subagent_event_flush() -> None:
    store = _BlockingStore()
    buffer = _buffer(store)
    flush_task = asyncio.create_task(buffer.flush())

    await store.entered.wait()
    flush_task.cancel()
    await asyncio.sleep(0)
    flush_task.cancel()
    await asyncio.sleep(0)

    assert not flush_task.done()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await flush_task

    assert len(store.batches) == 1
    assert buffer._pending == []


@pytest.mark.asyncio
async def test_cancelled_failed_subagent_event_flush_rebuffers_before_propagating() -> None:
    store = _BlockingStore(fail=True)
    buffer = _buffer(store)
    original = list(buffer._pending)
    flush_task = asyncio.create_task(buffer.flush())

    await store.entered.wait()
    flush_task.cancel()
    await asyncio.sleep(0)
    store.release.set()

    with pytest.raises(asyncio.CancelledError):
        await flush_task
    assert buffer._pending == original
