import asyncio
import threading

import pytest
from deerflow_extension_api.host_capabilities import HostCapabilityError

from deerflow.skills.mutations.workers import MutationWorkers


@pytest.mark.asyncio
async def test_publication_work_does_not_use_the_shared_default_executor(monkeypatch):
    workers = MutationWorkers(limit=1)
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor

    def require_dedicated(executor, func, *args):
        assert executor is not None, "publication must not queue behind unrelated default-executor work"
        return original(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", require_dedicated)
    try:
        assert await workers.run(lambda _: 42) == 42
    finally:
        await workers.close()


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_release_running_worker_slot():
    pool = MutationWorkers(limit=1)
    entered, release = threading.Event(), threading.Event()

    def work(check):
        entered.set()
        release.wait(2)
        return 1

    caller = asyncio.create_task(pool.run(work))
    await asyncio.to_thread(entered.wait, 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    with pytest.raises(HostCapabilityError, match="BUSY"):
        await pool.run(lambda check: 2)
    release.set()
    await pool.close()


@pytest.mark.asyncio
async def test_waiting_worker_gets_cancellation_checkpoint():
    from deerflow.skills.mutations.workers import MutationWorkers

    pool = MutationWorkers(limit=1)
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()

    def work(check):
        entered.set()
        release.wait(2)
        try:
            check()
        except HostCapabilityError as exc:
            if exc.code == "CANCELLED":
                cancelled.set()
            raise

    caller = asyncio.create_task(pool.run(work))
    await asyncio.to_thread(entered.wait, 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    await pool.close()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_pool_closes_to_new_work():
    from deerflow.skills.mutations.workers import MutationWorkers

    pool = MutationWorkers()
    assert await pool.run(lambda check: 42) == 42
    await pool.close()
    with pytest.raises(HostCapabilityError, match="UNAVAILABLE"):
        await pool.run(lambda check: 1)
