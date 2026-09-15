from __future__ import annotations

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
