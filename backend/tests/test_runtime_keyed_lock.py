from __future__ import annotations

import asyncio
import gc
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.runs.worker import _checkpoint_thread_lock


class _WeakThreadId(str):
    pass


class _WeakKey:
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lock_factory",
    [goal_thread_lock, _checkpoint_thread_lock],
    ids=["goal", "checkpoint"],
)
async def test_runtime_thread_lock_releases_idle_thread_id(lock_factory) -> None:
    thread_id = _WeakThreadId(f"retention-{uuid4().hex}")
    thread_id_ref = weakref.ref(thread_id)

    async with lock_factory(thread_id):
        pass

    del thread_id
    gc.collect()

    assert thread_id_ref() is None


@pytest.mark.asyncio
async def test_goal_and_checkpoint_lock_domains_remain_independent() -> None:
    release_checkpoint = asyncio.Event()
    checkpoint_entered = asyncio.Event()
    goal_entered = asyncio.Event()
    thread_id = f"independent-{uuid4().hex}"

    async def hold_checkpoint() -> None:
        async with _checkpoint_thread_lock(thread_id):
            checkpoint_entered.set()
            await release_checkpoint.wait()

    async def hold_goal() -> None:
        async with goal_thread_lock(thread_id):
            goal_entered.set()

    checkpoint_task = asyncio.create_task(hold_checkpoint())
    await checkpoint_entered.wait()
    goal_task = asyncio.create_task(hold_goal())
    try:
        await asyncio.wait_for(goal_entered.wait(), timeout=1)
    finally:
        release_checkpoint.set()
        await checkpoint_task
        await goal_task


@pytest.mark.asyncio
async def test_late_arrival_cannot_bypass_queued_waiter() -> None:
    from deerflow.runtime.keyed_lock import AsyncKeyedLockTable

    table = AsyncKeyedLockTable[str]()
    release_first = asyncio.Event()
    release_second = asyncio.Event()
    first_entered = asyncio.Event()
    second_started = asyncio.Event()
    second_entered = asyncio.Event()
    third_started = asyncio.Event()
    third_entered = asyncio.Event()
    active = 0
    max_active = 0
    order: list[str] = []

    async def participant(
        name: str,
        started: asyncio.Event | None,
        entered: asyncio.Event,
        release: asyncio.Event | None,
    ) -> None:
        nonlocal active, max_active
        if started is not None:
            started.set()
        async with table.hold("thread"):
            active += 1
            max_active = max(max_active, active)
            order.append(name)
            entered.set()
            try:
                if release is not None:
                    await release.wait()
            finally:
                active -= 1

    first = asyncio.create_task(participant("first", None, first_entered, release_first))
    await first_entered.wait()

    second = asyncio.create_task(participant("second", second_started, second_entered, release_second))
    await second_started.wait()

    release_first.set()
    await second_entered.wait()

    third = asyncio.create_task(participant("third", third_started, third_entered, None))
    await third_started.wait()

    assert not third_entered.is_set()
    assert max_active == 1

    release_second.set()
    await asyncio.gather(first, second, third)

    assert order == ["first", "second", "third"]
    assert max_active == 1


@pytest.mark.asyncio
async def test_cancelled_waiter_releases_its_participation() -> None:
    from deerflow.runtime.keyed_lock import AsyncKeyedLockTable

    table = AsyncKeyedLockTable[_WeakKey]()
    key = _WeakKey()
    key_ref = weakref.ref(key)
    release_holder = asyncio.Event()
    holder_entered = asyncio.Event()
    waiter_started = asyncio.Event()

    async def holder(lock_key: _WeakKey) -> None:
        async with table.hold(lock_key):
            holder_entered.set()
            await release_holder.wait()

    async def waiter(lock_key: _WeakKey) -> None:
        waiter_started.set()
        async with table.hold(lock_key):
            raise AssertionError("cancelled waiter entered the critical section")

    holder_task = asyncio.create_task(holder(key))
    await holder_entered.wait()
    waiter_task = asyncio.create_task(waiter(key))
    await waiter_started.wait()

    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    release_holder.set()
    await holder_task

    del holder_task, waiter_task, key
    gc.collect()
    assert key_ref() is None


@pytest.mark.asyncio
async def test_many_unique_keys_are_reclaimed() -> None:
    from deerflow.runtime.keyed_lock import AsyncKeyedLockTable

    table = AsyncKeyedLockTable[_WeakKey]()
    keys = [_WeakKey() for _ in range(1000)]
    key_refs = [weakref.ref(key) for key in keys]

    for key in keys:
        async with table.hold(key):
            pass

    del key, keys
    gc.collect()

    assert all(key_ref() is None for key_ref in key_refs)


def test_same_key_is_independent_across_event_loops() -> None:
    from deerflow.runtime.keyed_lock import AsyncKeyedLockTable

    table = AsyncKeyedLockTable[str]()
    barrier = threading.Barrier(2, timeout=2)

    def run_loop() -> None:
        async def run() -> None:
            async with table.hold("thread"):
                await asyncio.to_thread(barrier.wait)

        asyncio.run(run())

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_loop) for _ in range(2)]
        for future in futures:
            future.result(timeout=3)


def test_keyed_lock_table_late_arrival_cannot_bypass_queued_waiter() -> None:
    """Thread-side counterpart of the async table's late-arrival test.

    Overlapping ``hold()`` calls on one key serialize the bodies, and a
    queued waiter keeps the entry alive: an arrival that shows up while
    waiters are still queued must join the live entry instead of creating
    a second lock and entering concurrently (which is what an early
    reclamation would allow).
    """
    from deerflow.runtime.keyed_lock import KeyedLockTable

    table = KeyedLockTable[str]()
    release_first = threading.Event()
    release_second = threading.Event()
    release_third = threading.Event()
    first_entered = threading.Event()
    second_started = threading.Event()
    second_entered = threading.Event()
    third_started = threading.Event()
    third_entered = threading.Event()
    fourth_started = threading.Event()
    fourth_entered = threading.Event()
    guard = threading.Lock()
    active = 0
    max_active = 0
    entered: list[str] = []

    def participant(name: str, started: threading.Event | None, entered_event: threading.Event, release: threading.Event | None) -> None:
        nonlocal active, max_active
        if started is not None:
            started.set()
        with table.hold("key"):
            with guard:
                active += 1
                max_active = max(max_active, active)
                entered.append(name)
            entered_event.set()
            try:
                if release is not None:
                    release.wait(timeout=10)
            finally:
                with guard:
                    active -= 1

    first = threading.Thread(target=participant, args=("first", None, first_entered, release_first))
    first.start()
    assert first_entered.wait(timeout=5)

    second = threading.Thread(target=participant, args=("second", second_started, second_entered, release_second))
    second.start()
    assert second_started.wait(timeout=5)
    assert not second_entered.is_set(), "second must queue while the first still holds the entry"

    third = threading.Thread(target=participant, args=("third", third_started, third_entered, release_third))
    third.start()
    assert third_started.wait(timeout=5)
    time.sleep(0.05)
    assert not third_entered.is_set(), "third must queue on the live entry, not enter"

    # Hand the entry off: first leaves, exactly one queued waiter gets in
    # and parks inside its body on its release event.
    release_first.set()
    first.join(timeout=10)
    deadline = time.monotonic() + 5
    while not (second_entered.is_set() or third_entered.is_set()) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert second_entered.is_set() != third_entered.is_set(), "exactly one waiter holds the entry"

    # A late arrival while a waiter is still queued must join the live
    # entry (and therefore stay out until that waiter leaves), never enter
    # through a freshly created second lock.
    fourth = threading.Thread(target=participant, args=("fourth", fourth_started, fourth_entered, None))
    fourth.start()
    assert fourth_started.wait(timeout=5)
    time.sleep(0.05)
    assert not fourth_entered.is_set(), "late arrival bypassed a queued waiter"

    release_second.set()
    release_third.set()
    for thread in (second, third, fourth):
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert max_active == 1
    assert len(entered) == 4 and set(entered) == {"first", "second", "third", "fourth"}
    assert table._entries == {}, "the last check-in must pop the entry"


def test_keyed_lock_table_many_unique_keys_are_reclaimed() -> None:
    from deerflow.runtime.keyed_lock import KeyedLockTable

    table = KeyedLockTable[int]()

    for key in range(1000):
        with table.hold(key):
            assert len(table._entries) == 1
        assert key not in table._entries

    assert table._entries == {}
