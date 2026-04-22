"""Active execution handle management for runs domain."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ...types import CancelAction


@dataclass
class RunHandle:
    """In-process control handle for an active run."""

    run_id: str
    task: asyncio.Task[Any] | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_action: CancelAction = "interrupt"


class RunSupervisor:
    """Own and control active run handles within the current process."""

    def __init__(self) -> None:
        self._handles: dict[str, RunHandle] = {}
        self._lock = asyncio.Lock()

    async def launch(
        self,
        run_id: str,
        *,
        runner: Callable[[RunHandle], Awaitable[Any]],
    ) -> RunHandle:
        """Create a handle and start a background task for it."""
        handle = RunHandle(run_id=run_id)

        async with self._lock:
            if run_id in self._handles:
                raise RuntimeError(f"Run {run_id} is already active")
            self._handles[run_id] = handle

        task = asyncio.create_task(runner(handle))
        handle.task = task
        task.add_done_callback(lambda _: asyncio.create_task(self.cleanup(run_id)))
        return handle

    async def cancel(
        self,
        run_id: str,
        *,
        action: CancelAction = "interrupt",
    ) -> bool:
        """Signal cancellation for an active handle."""
        async with self._lock:
            handle = self._handles.get(run_id)
            if handle is None:
                return False

            handle.cancel_action = action
            handle.cancel_event.set()
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()

        return True

    def get_handle(self, run_id: str) -> RunHandle | None:
        """Return the active handle for a run, if any."""
        return self._handles.get(run_id)

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Remove a handle after optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)

        async with self._lock:
            self._handles.pop(run_id, None)
