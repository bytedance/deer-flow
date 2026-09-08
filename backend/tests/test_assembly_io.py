"""Unit tests for the assembly pool's pending counter.

The starvation warning in :func:`deerflow.utils.assembly_io.run_assembly`
fires once the pending (submitted, unfinished) count exceeds the worker
count. Nothing else in the suite reads ``_pending_assemblies``, so a drift
in the decrement would silently ratchet the count up and eventually fire
the warning with no starvation behind it — pin the two behaviors here.
"""

from __future__ import annotations

import asyncio
import threading
import time

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
