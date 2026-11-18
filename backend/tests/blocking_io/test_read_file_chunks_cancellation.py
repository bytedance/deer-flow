"""Cancellation-safety regression anchors for ``read_file_chunks`` (#7491).

Each test gates the real ``run_file_io`` dispatch with an ``asyncio.Event`` at
the worker boundary (real executor, real temporary files) to reproduce one of
the three unsafe windows: a cancellation racing the open-result handoff, a
close racing an in-flight read, and a repeated cancellation trying to escape a
pending close. The expected contract: once an operation has been admitted to
the worker, the caller's cancellation is delivered only after it settles, the
handle always reaches the cleanup path, and the close never races a read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from deerflow.projects.documents import read_file_chunks
from deerflow.utils.file_io import run_file_io as _real_run_file_io

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.allow_blocking_io,
]


class _Gate:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.admitted = asyncio.Event()
        self.hold = asyncio.Event()
        self.released = False

    def release(self) -> None:
        self.released = True
        self.hold.set()


def _gated_offload(
    gates: dict[str, _Gate],
    on_call,
    on_done,
) -> tuple[list[str], Callable[..., Coroutine[Any, Any, Any]]]:
    """Wrap ``documents.run_file_io`` call-through with worker-boundary gates.

    ``on_call`` fires when a dispatch enters the wrapper (admission),
    ``on_done`` fires after the real worker call settles.
    """
    calls: list[str] = []

    async def gated(func, /, *args, **kwargs):
        name = getattr(func, "__name__", "")
        calls.append(name)
        on_call(name)
        gate = gates.get(name)
        if gate is None:
            result = await _real_run_file_io(func, *args, **kwargs)
        elif gate.mode == "before":
            gate.admitted.set()
            await gate.hold.wait()
            result = await _real_run_file_io(func, *args, **kwargs)
        else:
            result = await _real_run_file_io(func, *args, **kwargs)
            gate.admitted.set()
            await gate.hold.wait()
        on_done(name)
        return result

    return calls, gated


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_cancel_racing_open_handoff_still_closes_handle(tmp_path, monkeypatch) -> None:
    """Window 1: the open worker returns, then cancellation lands before the
    result reaches the coroutine — the handle must still be closed."""
    path = tmp_path / "doc.bin"
    path.write_bytes(b"payload")
    open_gate = _Gate("after")
    state: dict[str, bool] = {"closed": False}

    def on_call(name: str) -> None: ...
    def on_done(name: str) -> None:
        if name == "close":
            state["closed"] = True

    calls, gated = _gated_offload({"_open": open_gate}, on_call, on_done)
    monkeypatch.setattr("deerflow.projects.documents.run_file_io", gated)

    agen = read_file_chunks(path, chunk_size=4)
    task = asyncio.create_task(agen.__anext__())
    await asyncio.wait_for(open_gate.admitted.wait(), 5)
    task.cancel()
    await _settle()
    assert "close" not in calls, "cleanup must wait for the open handoff to settle"

    open_gate.release()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["closed"], "handle retained at handoff must reach the cleanup close"


async def test_cancel_during_read_does_not_race_close(tmp_path, monkeypatch) -> None:
    """Window 2: cancellation while a read is admitted must not start the
    cleanup close before that read settles."""
    path = tmp_path / "doc.bin"
    path.write_bytes(b"abcdefgh")
    read_gate = _Gate("before")
    state: dict[str, bool] = {"close_raced": False, "read_settled": False}

    def on_call(name: str) -> None:
        if name == "close" and not state["read_settled"]:
            state["close_raced"] = True

    def on_done(name: str) -> None:
        if name == "read" and read_gate.released:
            state["read_settled"] = True

    calls, gated = _gated_offload({"read": read_gate}, on_call, on_done)
    monkeypatch.setattr("deerflow.projects.documents.run_file_io", gated)

    agen = read_file_chunks(path, chunk_size=4)
    task = asyncio.create_task(agen.__anext__())
    await asyncio.wait_for(read_gate.admitted.wait(), 5)
    task.cancel()
    await _settle()
    assert "close" not in calls, "close must wait for the admitted read to settle"

    read_gate.release()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["read_settled"], "the admitted read must run to completion"
    assert not state["close_raced"], "close must not precede or overlap the in-flight read"


async def test_repeated_cancellation_cannot_escape_pending_close(tmp_path, monkeypatch) -> None:
    """Window 3: a cancellation arriving while the cleanup close is admitted
    must be delivered only after the close settles — repeated cancellation
    included."""
    path = tmp_path / "doc.bin"
    path.write_bytes(b"abc")
    close_gate = _Gate("before")
    state: dict[str, bool] = {"close_completed": False}

    def on_call(name: str) -> None: ...

    def on_done(name: str) -> None:
        if name == "close" and close_gate.released:
            state["close_completed"] = True

    calls, gated = _gated_offload({"close": close_gate}, on_call, on_done)
    monkeypatch.setattr("deerflow.projects.documents.run_file_io", gated)

    async def consume() -> list[bytes]:
        return [chunk async for chunk in read_file_chunks(path, chunk_size=8)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(close_gate.admitted.wait(), 5)
    task.cancel()
    await _settle()
    task.cancel()
    await _settle()
    close_gate.release()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["close_completed"], "the caller may escape only after the close settles"


async def test_read_file_chunks_happy_path_unchanged(tmp_path, monkeypatch) -> None:
    """Sanity: full consumption still yields the exact bytes."""
    path = tmp_path / "doc.bin"
    path.write_bytes(b"abcdefgh")
    calls, gated = _gated_offload({}, lambda name: None, lambda name: None)
    monkeypatch.setattr("deerflow.projects.documents.run_file_io", gated)

    chunks = [chunk async for chunk in read_file_chunks(path, chunk_size=4)]

    assert chunks == [b"abcd", b"efgh"]
    assert calls[0] == "_open" and calls[-1] == "close"


async def test_missing_path_raises_file_not_found(tmp_path) -> None:
    """Pins the open-failure path: the error surfaces as-is and the cleanup
    skips the close (``retained`` is empty — no handle was ever opened)."""
    with pytest.raises(FileNotFoundError):
        async for _ in read_file_chunks(tmp_path / "absent.bin", chunk_size=4):
            pass
