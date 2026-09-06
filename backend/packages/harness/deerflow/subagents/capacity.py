"""Shared process-local admission control for native subagent execution."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig


class SubagentCapacityError(RuntimeError):
    """Base class for explicit admission failures."""


class SubagentCapacityRejected(SubagentCapacityError):
    """The process queue is full or configured to reject when saturated."""


class SubagentCapacityTimeout(SubagentCapacityError):
    """A queued execution did not receive a slot before its deadline."""


@dataclass(frozen=True)
class SubagentCapacitySnapshot:
    max_running: int
    running: int
    max_queued: int
    queued: int
    admission_policy: str


class SubagentExecutionCapacity:
    """FIFO async capacity controller; queued work never owns a thread."""

    def __init__(self, config: SubagentRuntimeConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._running = 0
        self._waiters: deque[asyncio.Future[None]] = deque()

    def snapshot(self) -> SubagentCapacitySnapshot:
        # snapshot() is read from non-loop threads (notably
        # configure_subagent_execution_capacity), while the loop thread mutates
        # the waiters deque under its own asyncio lock — iterating cross-thread
        # can raise "deque mutated during iteration". ``len()`` reads the
        # deque's size atomically instead. The raw length may count a waiter
        # that just timed out but has not removed itself yet; that only makes
        # the "capacity busy" answer more conservative, never less.
        return SubagentCapacitySnapshot(
            max_running=self._config.max_running,
            running=self._running,
            max_queued=self._config.max_queued,
            queued=len(self._waiters),
            admission_policy=self._config.admission_policy,
        )

    async def _acquire(self) -> None:
        waiter: asyncio.Future[None] | None = None
        async with self._lock:
            if self._running < self._config.max_running:
                self._running += 1
                return
            queued = sum(not candidate.done() for candidate in self._waiters)
            if self._config.admission_policy == "reject" or queued >= self._config.max_queued:
                raise SubagentCapacityRejected(f"Subagent execution capacity is full ({self._config.max_running} running, {queued} queued)")
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)

        try:
            await asyncio.wait_for(
                waiter,
                timeout=self._config.queue_timeout_seconds,
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            async with self._lock:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    # A release transferred the slot just as the timeout fired.
                    # If the future completed, this caller owns that transfer and
                    # must release it before reporting the timeout.
                    if waiter.done() and not waiter.cancelled():
                        self._release_locked()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise SubagentCapacityTimeout(f"Timed out after {self._config.queue_timeout_seconds}s waiting for a subagent execution slot") from exc

    def _release_locked(self) -> None:
        while self._waiters:
            waiter = self._waiters.popleft()
            if waiter.done():
                continue
            # Transfer the existing slot; _running intentionally stays flat.
            waiter.set_result(None)
            return
        if self._running <= 0:
            raise RuntimeError("Subagent execution capacity released without an owner")
        self._running -= 1

    async def _release(self) -> None:
        async with self._lock:
            self._release_locked()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        try:
            yield
        finally:
            await self._release()


_config = SubagentRuntimeConfig()
_controller: SubagentExecutionCapacity | None = None
_controller_loop: asyncio.AbstractEventLoop | None = None
_state_lock = threading.Lock()


def configure_subagent_execution_capacity(config: SubagentRuntimeConfig) -> None:
    """Install the startup snapshot used by the lazily-created loop controller."""
    global _config, _controller, _controller_loop
    candidate = config.model_copy(deep=True)
    with _state_lock:
        # Gateway startup and embedded clients may initialize the same process.
        # Treat installing the same frozen startup configuration as a no-op so
        # those entry points cannot reset a live queue.
        if _config == candidate:
            return
        if _controller is not None:
            snapshot = _controller.snapshot()
            if snapshot.running or snapshot.queued:
                raise RuntimeError("Cannot reconfigure subagent capacity while executions are active")
        _config = candidate
        _controller = None
        _controller_loop = None


def get_subagent_execution_capacity() -> SubagentExecutionCapacity:
    """Return the controller bound to the current execution loop."""
    global _controller, _controller_loop
    loop = asyncio.get_running_loop()
    with _state_lock:
        if _controller is None:
            _controller = SubagentExecutionCapacity(_config)
            _controller_loop = loop
        elif _controller_loop is not loop:
            snapshot = _controller.snapshot()
            if snapshot.running or snapshot.queued:
                raise RuntimeError("Native subagent capacity cannot move event loops while executions are active")
            # Direct async consumers (notably embedded callers and tests) may
            # legitimately use a new event loop after the previous idle loop
            # has closed. Rebind only while completely idle; production sync
            # and background paths still share the persistent isolated loop.
            _controller = SubagentExecutionCapacity(_config)
            _controller_loop = loop
        return _controller


def configured_subagent_max_running() -> int:
    """Return the startup snapshot without requiring an event loop."""
    with _state_lock:
        return _config.max_running
