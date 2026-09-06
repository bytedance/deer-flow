"""Per-key acquire serialization with bounded lock-table growth (RFC #4741).

Shared component for sandbox providers. Each provider selects the key that
preserves its current collision and lifecycle semantics (``(user_id,
thread_id)`` for AIO/E2B, the derived sandbox id for BoxLite/Tenki/
OpenSandbox); the serializer never interprets it.

The async path runs the blocking ``threading.Lock.acquire`` on a bounded
dedicated executor (never the default executor, never the event loop). A small
handoff state makes the acquire worker release an abandoned lock itself, so
cleanup does not depend on the cancelling event loop running a done callback.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import threading
from collections.abc import AsyncIterator, Callable, Hashable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import partial

DEFAULT_MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)


@dataclass
class _Entry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    refs: int = 0  # holders + waiters


class _AsyncAcquire:
    """Race-safe ownership handoff between an event loop and acquire worker."""

    def __init__(self, entry: _Entry, cleanup: Callable[[], None]) -> None:
        self._entry = entry
        self._cleanup = cleanup
        self._state_lock = threading.Lock()
        self._abandoned = False
        self._acquired = False
        self._cleaned = False

    def run(self) -> bool:
        self._entry.lock.acquire()
        with self._state_lock:
            if self._abandoned:
                cleanup = self._mark_cleaned()
            else:
                self._acquired = True
                cleanup = False
        if cleanup:
            self._entry.lock.release()
            self._cleanup()
        return not cleanup

    def abandon(self) -> None:
        with self._state_lock:
            self._abandoned = True
            cleanup = self._acquired and self._mark_cleaned()
            if cleanup:
                self._acquired = False
        if cleanup:
            self._entry.lock.release()
            self._cleanup()

    def cancel_queued(self) -> None:
        """Clean up an executor job cancelled before its worker started."""
        with self._state_lock:
            cleanup = self._mark_cleaned()
        if cleanup:
            self._cleanup()

    def worker_done(self, future: Future[bool]) -> None:
        """Reclaim a checkout if executor shutdown cancelled queued work."""
        if future.cancelled():
            self.cancel_queued()

    def release(self) -> None:
        with self._state_lock:
            cleanup = self._acquired and self._mark_cleaned()
            if cleanup:
                self._acquired = False
        if not cleanup:  # pragma: no cover - indicates an internal ownership bug
            raise RuntimeError("Serializer lock is not held")
        self._entry.lock.release()
        self._cleanup()

    def _mark_cleaned(self) -> bool:
        if self._cleaned:
            return False
        self._cleaned = True
        return True


class AcquireSerializer[KeyT: Hashable]:
    """Serialize provider-selected lifecycle transitions per key."""

    def __init__(
        self,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
        thread_name_prefix: str = "sandbox-acquire-wait",
    ) -> None:
        self._table: dict[KeyT, _Entry] = {}
        self._table_lock = threading.Lock()
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)

    @property
    def executor(self) -> ThreadPoolExecutor:
        """The dedicated bounded executor backing async waits.

        Providers may offload an entire synchronous acquire (with hold()
        inside) here so a cancelled awaiter abandons the worker, not the
        lock: the hold then follows the body to completion, matching the
        pre-serializer to_thread bridge semantics.
        """
        return self._executor

    async def run_on_executor[**P, T](self, func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
        """Run a blocking callable on the serializer's dedicated executor.

        ``asyncio.to_thread`` copies ``ContextVar`` values automatically; raw
        ``loop.run_in_executor`` does not. The providers whose ``acquire_async``
        offloads the whole synchronous acquire here replaced the inherited
        ``to_thread`` bridge, so copy the calling context explicitly: without
        it, request-scoped ContextVars (e.g. the trace id bound by
        ``request_trace_context``) read as unset inside the worker thread.
        """
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        call = partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._executor, ctx.run, call)

    @contextmanager
    def hold(self, key: KeyT) -> Iterator[None]:
        entry = self._checkout(key)
        entry.lock.acquire()
        try:
            yield
        finally:
            entry.lock.release()
            self._checkin(key, entry)

    @asynccontextmanager
    async def hold_async(self, key: KeyT) -> AsyncIterator[None]:
        entry = self._checkout(key)
        loop = asyncio.get_running_loop()
        acquire = _AsyncAcquire(entry, lambda: self._checkin(key, entry))
        try:
            worker_future = self._executor.submit(acquire.run)
        except RuntimeError:  # executor shut down between checkout and scheduling
            self._checkin(key, entry)
            raise RuntimeError("AcquireSerializer is closed") from None
        # concurrent.futures callbacks run in the cancelling/worker thread, so
        # executor-shutdown cleanup does not depend on this loop progressing.
        worker_future.add_done_callback(acquire.worker_done)
        acquire_future = asyncio.wrap_future(worker_future, loop=loop)
        try:
            acquired = await asyncio.shield(acquire_future)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if acquire_future.cancelled() and task is not None and task.cancelling() == 0:
                # close() cancelled the queued wait via executor shutdown, not
                # the caller: check in exactly once (no done callback — the
                # cancelled future is already done) and report the documented
                # closure error instead of a spurious CancelledError. The
                # `cancelling() == 0` guard assumes this await is the task's
                # only pending cancellation (no stale count left by an outer
                # swallowed CancelledError).
                acquire.cancel_queued()
                raise RuntimeError("AcquireSerializer is closed") from None
            if acquire_future.cancelled():
                acquire.cancel_queued()
            else:
                acquire.abandon()
            raise
        # run() returns False only when the worker observed _abandoned, and
        # abandon() is called solely from the except handler above, which
        # always re-raises — so a normal completion implies the lock is held.
        # If this were reachable, the worker would already have checked in;
        # an extra _checkin here would underflow the refcount, so assert.
        assert acquired, "acquire worker returned without holding the lock"
        try:
            yield
        finally:
            acquire.release()

    def close(self) -> None:
        """Reject new holders and release executor resources. Idempotent.

        A currently executing critical section is not invalidated: its exit
        still releases its lock and reclaims its table entry.
        """
        with self._table_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _checkout(self, key: KeyT) -> _Entry:
        with self._table_lock:
            if self._closed:
                raise RuntimeError("AcquireSerializer is closed")
            entry = self._table.get(key)
            if entry is None:
                entry = _Entry()
                self._table[key] = entry
            entry.refs += 1
            return entry

    def _checkin(self, key: KeyT, entry: _Entry) -> None:
        with self._table_lock:
            entry.refs -= 1
            if entry.refs == 0 and not entry.lock.locked():
                self._table.pop(key, None)
