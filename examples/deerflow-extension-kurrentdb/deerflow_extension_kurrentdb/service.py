"""``KurrentRecoveryService``: the extension's Gateway service for deletion recovery.

Registered by ``install()`` (``registry.service``). It owns its own memory storage
and run-event store (same environment settings as the Gateway's, so the same
KurrentDB), and:

- **at start**, finishes or abandons the primary side of every open deletion
  (memory, then run events, ruling R13), bounded by ``startup_budget`` (default
  one ``settings.timeout``): Gateway startup never waits longer, and never on a
  canonical stream, which primary recovery does not touch. Whatever the budget
  cut short is retried by the loop
- **in the background**, runs a pass right away and then every ``interval``
  seconds (sooner when a verification falls due): primary recovery again, then
  the canonical obligations (cleanups, and verifications whose wait is over) when
  ``KURRENTDB_CANONICAL_EVENTS`` is on. A failing pass is logged at WARNING and
  retried on the next

Missing settings (no ``KURRENTDB_CONNECTION_STRING``) or a failure to build the
storage leave the service idle with a warning; start never raises for them.
The memory storage is synchronous, so its work runs on one dedicated thread
(``kurrentdb-recovery``); ``stop`` cancels the loop and waits a bounded time for
that thread's current job.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from collections.abc import Callable
from typing import Any

from ._settings import load_settings

logger = logging.getLogger(__name__)

#: Seconds between background passes when no verification is due sooner.
DEFAULT_INTERVAL_SECONDS = 30.0
#: The shortest sleep between passes.
MIN_INTERVAL_SECONDS = 1.0
THREAD_NAME = "kurrentdb-recovery"


def _default_memory(clock: Callable[[], float]) -> Any:
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    from .memory import KurrentdbMemoryStorage

    return KurrentdbMemoryStorage(DeerMemConfig(), clock=clock)


def _default_store(clock: Callable[[], float]) -> Any:
    from .run_events import KurrentRunEventStore

    return KurrentRunEventStore({}, clock=clock)


class KurrentRecoveryService:
    """Deletion recovery: primary sides at start (bounded), then primary and canonical obligations in the background."""

    def __init__(
        self,
        *,
        memory_factory: Callable[[], Any] | None = None,
        store_factory: Callable[[], Any] | None = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        startup_budget: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        # Nothing here connects or reads settings: install() builds the service.
        self._clock = clock or time.time
        self._memory_factory = memory_factory or (lambda: _default_memory(self._clock))
        self._store_factory = store_factory or (lambda: _default_store(self._clock))
        self._interval = interval
        self._startup_budget = startup_budget
        self._memory: Any = None
        self._store: Any = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._inflight: concurrent.futures.Future | None = None
        self._task: asyncio.Task[None] | None = None
        self._timeout = 10.0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, deps: Any = None) -> None:
        try:
            settings = load_settings()
            self._timeout = settings.timeout
            self._memory = self._memory_factory()
            self._store = self._store_factory()
        except Exception:
            logger.warning("KurrentDB recovery service not started: settings or storage unavailable", exc_info=True)
            return
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=THREAD_NAME)
        budget = self._startup_budget if self._startup_budget is not None else self._timeout
        try:
            await asyncio.wait_for(self.recover_primary(), budget)
        except TimeoutError:
            logger.warning("Startup deletion recovery did not finish within %ss; continuing in the background", budget)
        self._task = asyncio.get_running_loop().create_task(self._loop(), name=THREAD_NAME)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        executor, self._executor = self._executor, None
        if executor is not None:
            inflight = self._inflight
            if inflight is not None and not inflight.done():
                await asyncio.wait([asyncio.wrap_future(inflight)], timeout=self._timeout * 2)
            executor.shutdown(wait=False, cancel_futures=True)

    async def _in_thread(self, job: Callable[[], Any]) -> Any:
        if self._executor is None:
            raise RuntimeError("the recovery service is not started")
        future = self._executor.submit(job)
        self._inflight = future
        return await asyncio.wrap_future(future)

    async def recover_primary(self) -> None:
        """Finish or abandon every open primary deletion side: memory, then run events; failures are logged."""
        try:
            await self._in_thread(self._memory.recover_deletions)
        except Exception:
            logger.warning("Memory deletion recovery failed; retrying in the background", exc_info=True)
        try:
            await self._store.recover_deletions()
        except Exception:
            logger.warning("Run-event deletion recovery failed; retrying in the background", exc_info=True)

    async def run_canonical(self) -> float | None:
        """One pass over the canonical obligations; returns when the next verification is due (``None``: none waiting)."""
        due: list[float] = []
        for name, runner in (("memory", lambda: self._in_thread(self._memory.run_canonical_obligations)), ("run-event", self._store.run_canonical_obligations)):
            try:
                report = await runner()
            except Exception:
                logger.warning("The %s canonical cleanup pass failed; retrying in the background", name, exc_info=True)
                continue
            if report is not None and report.next_due is not None:
                due.append(report.next_due)
        return min(due) if due else None

    async def run_once(self) -> float | None:
        await self.recover_primary()
        return await self.run_canonical()

    async def _loop(self) -> None:
        next_due = await self._pass(self.run_canonical)
        while True:
            delay = self._interval
            if next_due is not None:
                delay = min(delay, max(next_due - self._clock(), MIN_INTERVAL_SECONDS))
            await asyncio.sleep(delay)
            next_due = await self._pass(self.run_once)

    @staticmethod
    async def _pass(run: Callable[[], Any]) -> float | None:
        try:
            return await run()
        except Exception:
            logger.warning("KurrentDB recovery pass failed; retrying on the next", exc_info=True)
            return None
