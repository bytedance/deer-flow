"""Regression coverage for Buzz replay-guard persistence on async paths.

Buzz receives and stops channels on the Gateway event loop. Persisting the
seen-event replay guard must therefore stay off that loop while still making a
clean stop durable before it returns.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.channels import buzz_seen_events
from app.channels.buzz_seen_events import BuzzSeenEventStore

pytestmark = pytest.mark.asyncio

_CHANNEL_ID = "136852ee-63e1-49c2-8927-413b5ee8e5f7"


async def test_async_replay_guard_round_trips_without_blocking_the_event_loop(tmp_path: Path) -> None:
    """An async flush makes a recorded event visible to a fresh store."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)

    await store.arecord(_CHANNEL_ID, "event-1")
    await store.aflush()

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")


async def test_loaded_store_does_not_dispatch_hot_path_lookups_to_a_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the cold file load needs the shared worker pool."""
    store = BuzzSeenEventStore(tmp_path / "buzz-seen-events.json")
    assert not await store.aseen(_CHANNEL_ID, "event-1")

    async def unexpected_to_thread(*_args, **_kwargs):
        raise AssertionError("loaded seen-event store used the worker pool")

    monkeypatch.setattr(asyncio, "to_thread", unexpected_to_thread)

    await store.arecord(_CHANNEL_ID, "event-1")
    assert await store.aseen(_CHANNEL_ID, "event-1")


async def test_event_recorded_during_a_final_write_remains_retryable(tmp_path: Path) -> None:
    """An in-flight snapshot must not mark a newer generation as clean."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)
    write_started = threading.Event()
    release_write = threading.Event()
    snapshots: list[dict[str, list[str]]] = []
    write_snapshot = store._write_snapshot

    def pause_first_write(payload: dict[str, list[str]]) -> bool:
        snapshots.append(payload)
        if len(snapshots) == 1:
            write_started.set()
            assert release_write.wait(timeout=2)
        return write_snapshot(payload)

    store._write_snapshot = pause_first_write
    await store.arecord(_CHANNEL_ID, "event-1")
    flush = asyncio.create_task(store.aflush())

    assert await asyncio.to_thread(write_started.wait, 2)
    await store.arecord(_CHANNEL_ID, "event-2")
    release_write.set()
    await flush
    assert await store.aseen(_CHANNEL_ID, "event-2")

    # The final flush deliberately cancels its trailing timer, but the newer
    # generation stays dirty so a retried cleanup can make it durable.
    await store.aflush()

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")
    assert await restarted.aseen(_CHANNEL_ID, "event-2")


async def test_final_flush_is_bounded_while_records_keep_arriving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown must return instead of chasing an active producer forever."""
    store = BuzzSeenEventStore(tmp_path / "buzz-seen-events.json")
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    second_write_started = threading.Event()
    release_second_write = threading.Event()
    snapshots: list[dict[str, list[str]]] = []
    write_snapshot = store._write_snapshot

    def pause_bounded_writes(payload: dict[str, list[str]]) -> bool:
        snapshots.append(payload)
        if len(snapshots) == 1:
            first_write_started.set()
            assert release_first_write.wait(timeout=2)
        elif len(snapshots) == 2:
            second_write_started.set()
            assert release_second_write.wait(timeout=2)
        return write_snapshot(payload)

    store._write_snapshot = pause_bounded_writes
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.01)
    await store.arecord(_CHANNEL_ID, "event-0")
    assert await asyncio.to_thread(first_write_started.wait, 2)

    # Leave enough time to finish the bounded flush before a timer armed by a
    # late record can fire. Once aflush() returns, no third write may remain
    # scheduled for a store whose owning channel has stopped.
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.05)
    final_flush = asyncio.create_task(store.aflush())
    await store.arecord(_CHANNEL_ID, "late-1")
    release_first_write.set()

    assert await asyncio.to_thread(second_write_started.wait, 2)
    await store.arecord(_CHANNEL_ID, "late-2")
    release_second_write.set()
    await final_flush
    await asyncio.sleep(0.1)

    assert len(snapshots) == 2
    assert await store.aseen(_CHANNEL_ID, "late-2")


async def test_final_flush_ignores_a_task_from_a_closed_event_loop(tmp_path: Path) -> None:
    """A stale loop-owned task must not abort shutdown on the current loop."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)

    def leave_cancelled_task_from_closed_loop() -> None:
        async def seed() -> None:
            await store.arecord(_CHANNEL_ID, "event-1")
            store._flush_task = asyncio.create_task(asyncio.sleep(60))

        asyncio.run(seed())

    await asyncio.to_thread(leave_cancelled_task_from_closed_loop)
    await store.aflush()

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")


async def test_final_flush_recovers_when_an_in_flight_flush_task_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A background persistence failure must not escape channel shutdown."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)
    write_started = threading.Event()
    release_write = threading.Event()
    write_snapshot = store._write_snapshot
    write_count = 0

    def fail_first_write(payload: dict[str, list[str]]) -> bool:
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            write_started.set()
            assert release_write.wait(timeout=2)
            raise RuntimeError("worker pool is shutting down")
        return write_snapshot(payload)

    store._write_snapshot = fail_first_write
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.01)
    await store.arecord(_CHANNEL_ID, "event-1")
    assert await asyncio.to_thread(write_started.wait, 2)

    final_flush = asyncio.create_task(store.aflush())
    await asyncio.sleep(0)
    release_write.set()
    await final_flush

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")


async def test_cancelled_final_flush_does_not_rearm_timer_from_existing_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retained scheduled write must not create new work after stop."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)
    write_started = threading.Event()
    release_write = threading.Event()
    snapshots: list[dict[str, list[str]]] = []
    write_snapshot = store._write_snapshot

    def pause_first_write(payload: dict[str, list[str]]) -> bool:
        snapshots.append(payload)
        if len(snapshots) == 1:
            write_started.set()
            assert release_write.wait(timeout=2)
        return write_snapshot(payload)

    store._write_snapshot = pause_first_write
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.01)
    await store.arecord(_CHANNEL_ID, "event-1")
    assert await asyncio.to_thread(write_started.wait, 2)

    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0.05)
    await store.arecord(_CHANNEL_ID, "event-2")
    final_flush = asyncio.create_task(store.aflush())
    await asyncio.sleep(0)
    final_flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await final_flush

    release_write.set()
    await asyncio.sleep(0.1)
    assert len(snapshots) == 1
    assert await store.aseen(_CHANNEL_ID, "event-2")

    await store.aflush()
    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-2")


async def test_scheduled_flush_replaces_a_pending_task_from_a_closed_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale task must not disable normal coalesced persistence on a new loop."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)

    def pending_task_from_closed_loop() -> asyncio.Task:
        loop = asyncio.new_event_loop()

        async def remain_pending() -> None:
            await asyncio.sleep(60)

        task = loop.create_task(remain_pending())
        loop.run_until_complete(asyncio.sleep(0))
        task._log_destroy_pending = False
        loop.close()
        return task

    stale_task = await asyncio.to_thread(pending_task_from_closed_loop)
    store._flush_task = stale_task
    monkeypatch.setattr(buzz_seen_events, "FLUSH_DELAY_SECONDS", 0)

    try:
        await store.arecord(_CHANNEL_ID, "event-1")
        deadline = asyncio.get_running_loop().time() + 1
        while asyncio.get_running_loop().time() < deadline:
            if await BuzzSeenEventStore(path).aseen(_CHANNEL_ID, "event-1"):
                break
            await asyncio.sleep(0.01)

        assert await BuzzSeenEventStore(path).aseen(_CHANNEL_ID, "event-1")
    finally:
        if store._flush_task is stale_task:
            store._flush_task = None
