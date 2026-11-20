"""Lock-registry lifecycle regressions for the JSONL run-event store."""

from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore


def _event(content: str = "message") -> dict:
    return {
        "thread_id": "t1",
        "run_id": "r1",
        "event_type": "message",
        "category": "message",
        "content": content,
    }


class _PausedDelete:
    def __init__(self, operation):
        self.operation = operation
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = threading.Event()

    def __call__(self, *args):
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            if not self.release.wait(10):
                raise TimeoutError("test did not release paused delete")
            return self.operation(*args)
        finally:
            self.loop.call_soon_threadsafe(self.finished.set)


async def _checkpoint() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.anyio
async def test_delete_keeps_one_lock_generation_while_waiter_exists(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**_event("baseline"))

    paused_delete = _PausedDelete(store._delete_thread_files)
    monkeypatch.setattr(store, "_delete_thread_files", paused_delete)

    original_get_lock = store._get_write_lock
    second_lookup = asyncio.Event()
    lookup_count = 0

    def observed_get_lock(thread_id: str):
        nonlocal lookup_count
        lock = original_get_lock(thread_id)
        lookup_count += 1
        if lookup_count == 2:
            second_lookup.set()
        return lock

    monkeypatch.setattr(store, "_get_write_lock", observed_get_lock)

    release_queued = asyncio.Event()
    queued_entered = asyncio.Event()
    later_entered = asyncio.Event()
    deletion = asyncio.create_task(store.delete_by_thread("t1"))
    queued = None
    later = None
    try:
        await asyncio.wait_for(paused_delete.entered.wait(), 5)

        async def queued_operation():
            queued_entered.set()
            await release_queued.wait()

        queued = asyncio.create_task(store._run_mutation("t1", queued_operation))
        await asyncio.wait_for(second_lookup.wait(), 5)
        await _checkpoint()

        paused_delete.release.set()
        assert await deletion == 1
        await asyncio.wait_for(queued_entered.wait(), 5)

        async def later_operation():
            later_entered.set()

        later = asyncio.create_task(store._run_mutation("t1", later_operation))
        await _checkpoint()
        assert not later_entered.is_set(), "a later mutation acquired a new lock generation while the old waiter still owned the thread"

        release_queued.set()
        await queued
        await later
        assert later_entered.is_set()
        await _checkpoint()
        assert "t1" not in store._write_locks
    finally:
        paused_delete.release.set()
        release_queued.set()
        await asyncio.gather(deletion, *([queued] if queued is not None else []), *([later] if later is not None else []), return_exceptions=True)
        await asyncio.wait_for(paused_delete.finished.wait(), 5)
