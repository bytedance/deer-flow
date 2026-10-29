from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from deerflow.utils.file_io import run_file_io


@pytest.mark.anyio
async def test_run_file_io_propagates_contextvars_to_worker() -> None:
    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="missing")
    marker.set("owner-1")

    def read_marker() -> tuple[str, str]:
        return marker.get(), threading.current_thread().name

    value, thread_name = await run_file_io(read_marker)

    assert value == "owner-1"
    assert thread_name.startswith("file-io")


@pytest.mark.anyio
async def test_run_file_io_passes_args_and_kwargs() -> None:
    def join_values(prefix: str, *, suffix: str) -> str:
        return f"{prefix}:{suffix}"

    assert await run_file_io(join_values, "left", suffix="right") == "left:right"


@pytest.mark.anyio
async def test_await_drained_completes_inner_work_before_cancelling() -> None:
    """Cancellation waits for the inner coroutine: the worker's effect lands
    BEFORE the CancelledError unwinds (the locked-transaction invariant)."""
    from deerflow.utils.file_io import await_drained

    started = threading.Event()
    finish = threading.Event()
    completed = False

    async def inner() -> str:
        nonlocal completed
        await asyncio.to_thread(lambda: (started.set(), finish.wait(5)))
        completed = True
        return "done"

    task = asyncio.create_task(await_drained(inner()))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.1)
    # Still draining: the cancellation has not unwound past the inner work.
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed


@pytest.mark.anyio
async def test_await_drained_passes_through_results_and_errors() -> None:
    from deerflow.utils.file_io import await_drained

    assert await await_drained(asyncio.sleep(0, result=42)) == 42

    async def boom() -> None:
        raise ValueError("inner failure")

    with pytest.raises(ValueError, match="inner failure"):
        await await_drained(boom())
