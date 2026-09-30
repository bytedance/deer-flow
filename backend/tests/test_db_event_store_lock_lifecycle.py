import asyncio
import weakref

import pytest

from deerflow.runtime.events.store.db import DbRunEventStore


class _PausedDeleteSession:
    """Fake session that pauses the deletion on its first aggregate read.

    The fixed deletion path opens the session, takes the thread mutation fence
    (a no-op on this fake's dialect) and only then reads the expected count, so
    pausing in ``scalar`` proves the caller already owns the thread's mutation
    critical section.
    """

    def __init__(self, scalar_started: asyncio.Event, allow_scalar: asyncio.Event) -> None:
        self._scalar_started = scalar_started
        self._allow_scalar = allow_scalar

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get_bind(self):
        # Non-PostgreSQL dialect: ``_acquire_thread_mutation_fence`` must not
        # emit advisory-lock SQL here — the in-process lock is the only fence.
        return None

    def begin(self):
        return self

    async def scalar(self, _stmt):
        self._scalar_started.set()
        await self._allow_scalar.wait()
        return 1

    async def execute(self, _stmt, _params=None):
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.anyio
async def test_delete_waiter_handoff_keeps_one_write_lock_generation():
    scalar_started = asyncio.Event()
    allow_scalar = asyncio.Event()
    session = _PausedDeleteSession(scalar_started, allow_scalar)
    store = DbRunEventStore(lambda: session)

    old_lock = store._get_write_lock("t1")
    old_lock_ref = weakref.ref(old_lock)
    await old_lock.acquire()

    waiter_resolved = asyncio.Event()
    waiter_entered = asyncio.Event()
    release_waiter = asyncio.Event()

    async def queued_writer() -> None:
        lock = store._get_write_lock("t1")
        waiter_resolved.set()
        async with lock:
            waiter_entered.set()
            await release_waiter.wait()

    delete_task = asyncio.create_task(store.delete_by_thread("t1", user_id=None))
    await asyncio.sleep(0)

    # B1 contract: deletion is queued behind the existing holder instead of
    # running concurrently with it.
    assert not scalar_started.is_set()
    assert not delete_task.done()

    waiter_task = asyncio.create_task(queued_writer())
    await waiter_resolved.wait()
    await asyncio.sleep(0)
    assert not waiter_entered.is_set()

    # Resume deletion first, then release the holder. asyncio.Lock.release()
    # marks the lock unlocked before the queued waiter resumes, so the old
    # implementation can evict the registry entry in that handoff window.
    old_lock.release()
    del old_lock

    # Delete now owns the same generation, and the queued writer is still
    # waiting behind it.
    await scalar_started.wait()
    assert not waiter_entered.is_set()

    allow_scalar.set()
    await delete_task
    await waiter_entered.wait()

    try:
        # The waiter still owns the old generation. Any later writer must
        # resolve that exact lock rather than creating a concurrent generation.
        assert store._get_write_lock("t1") is old_lock_ref()
    finally:
        release_waiter.set()
        await waiter_task


@pytest.mark.anyio
async def test_delete_by_thread_waits_for_thread_write_lock():
    """Deletion must not enter its DB mutation while a writer holds the lock."""
    scalar_started = asyncio.Event()
    allow_scalar = asyncio.Event()
    allow_scalar.set()

    session = _PausedDeleteSession(scalar_started, allow_scalar)
    store = DbRunEventStore(lambda: session)

    lock = store._get_write_lock("t1")
    await lock.acquire()

    task = asyncio.create_task(store.delete_by_thread("t1", user_id=None))
    await asyncio.sleep(0)

    assert not scalar_started.is_set()
    assert not task.done()

    lock.release()

    assert await task == 1
    assert scalar_started.is_set()


@pytest.mark.anyio
async def test_delete_by_run_waits_for_thread_write_lock():
    """delete_by_run shares the same fence as delete_by_thread."""
    scalar_started = asyncio.Event()
    allow_scalar = asyncio.Event()
    allow_scalar.set()

    session = _PausedDeleteSession(scalar_started, allow_scalar)
    store = DbRunEventStore(lambda: session)

    lock = store._get_write_lock("t1")
    await lock.acquire()

    task = asyncio.create_task(store.delete_by_run("t1", "r1", user_id=None))
    await asyncio.sleep(0)

    assert not scalar_started.is_set()
    assert not task.done()

    lock.release()

    assert await task == 1
    assert scalar_started.is_set()
