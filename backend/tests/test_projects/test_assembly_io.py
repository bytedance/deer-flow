"""Unit tests for the assembly pool's pending counter.

The starvation warning in :func:`deerflow.utils.assembly_io.run_assembly`
fires once the pending (submitted, unfinished) count exceeds the worker
count. Nothing else in the suite reads ``_pending_assemblies``, so a drift
in the decrement would silently ratchet the count up and eventually fire
the warning with no starvation behind it — pin the three behaviors here.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import deerflow.utils.assembly_io as assembly_io


def test_pending_count_returns_to_zero_after_healthy_call() -> None:
    async def main() -> str:
        return await assembly_io.run_assembly(lambda: "ok")

    assert asyncio.run(main()) == "ok"
    assert assembly_io._pending_assemblies == 0


def test_abandoned_loop_does_not_wedge_the_counter() -> None:
    """A submitting loop that dies while its worker is still parked must not
    wedge the count: the decrement rides the dispatched work item's ``finally``
    (pool thread), not the asyncio future's done callback (submitting loop)."""
    worker_started = threading.Event()
    worker_release = threading.Event()

    def _parked() -> str:
        worker_started.set()
        worker_release.wait(timeout=10)
        return "done"

    loop = asyncio.new_event_loop()
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            loop.run_until_complete(assembly_io.run_assembly(_parked))
        except BaseException as exc:  # the abandoned submission is cancelled/raises
            errors.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    assert worker_started.wait(timeout=5)

    # Abandon the submission loop: stop it while the coroutine is still
    # awaiting the dispatched work, so its future can never resolve and the
    # old done-callback decrement would never fire.
    loop.call_soon_threadsafe(loop.stop)
    worker_release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    loop.close()

    # Give the pool worker time to finish its finally-block decrement.
    deadline = time.monotonic() + 5
    while assembly_io._pending_assemblies != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert assembly_io._pending_assemblies == 0, errors or "counter was not decremented by the dispatched work item"


def test_queued_cancellation_releases_the_pending_count() -> None:
    """A job cancelled while still queued never runs its work item, so the
    dispatched finally never fires; the cancelled-future cleanup must
    release the slot exactly once instead (WillemJiang, PR #5224 review)."""
    worker_started = threading.Event()
    worker_release = threading.Event()

    def _parked() -> str:
        worker_started.set()
        worker_release.wait(timeout=10)
        return "done"

    pool = ThreadPoolExecutor(max_workers=1)
    original_executor = assembly_io._ASSEMBLY_EXECUTOR
    assembly_io._ASSEMBLY_EXECUTOR = pool
    try:

        async def main() -> None:
            loop = asyncio.get_running_loop()
            first = asyncio.ensure_future(assembly_io.run_assembly(_parked))
            assert await loop.run_in_executor(None, worker_started.wait, 5.0)
            assert assembly_io._pending_assemblies == 1

            # The single worker is parked in the first call, so the second
            # submission is queued, not started.
            second = asyncio.ensure_future(assembly_io.run_assembly(lambda: "queued"))
            deadline = time.monotonic() + 5
            while assembly_io._pending_assemblies != 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert assembly_io._pending_assemblies == 2

            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            assert assembly_io._pending_assemblies == 1, "cancelled queued job must release its slot without running _work"

            worker_release.set()
            assert await first == "done"
            assert assembly_io._pending_assemblies == 0

        asyncio.run(main())
    finally:
        assembly_io._ASSEMBLY_EXECUTOR = original_executor
        pool.shutdown(wait=True)
