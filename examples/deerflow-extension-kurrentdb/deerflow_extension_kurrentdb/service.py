"""``KurrentRecoveryService``: the extension's Gateway service for deletion recovery.

Registered by ``install()`` (``registry.service``). It reads the Gateway config at
start (``backends_from``): it works only for the KurrentDB backends in use, the
memory storage when ``memory.backend_config.storage_class`` is
``KurrentdbMemoryStorage`` and the run-event store when ``run_events.backend`` is
``kurrent``; with neither it stays idle. It owns its own instances, with the same
environment settings as the Gateway's (so the same KurrentDB), and builds the
memory storage from the Gateway's own ``DeerMemConfig`` (``from_backend_config``):
sidecar recovery folds and persists sidecar state with config-dependent caps and
decay, which must match the Gateway's. Then:

- **at start**, finishes or abandons the primary side of every open deletion
  (memory, then run events, ruling R13), each bounded by its own
  ``startup_budget`` (default one ``settings.timeout``): Gateway startup never
  waits longer, and never on a canonical stream, which primary recovery does not
  touch. When a budget cut recovery short, the loop's first pass retries it
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
import importlib
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ._settings import load_settings

logger = logging.getLogger(__name__)

#: Seconds between background passes when no verification is due sooner.
DEFAULT_INTERVAL_SECONDS = 30.0
#: The shortest sleep between passes.
MIN_INTERVAL_SECONDS = 1.0
THREAD_NAME = "kurrentdb-recovery"


RUN_EVENT_BACKEND = "kurrent"


@dataclass(frozen=True)
class Backends:
    """The KurrentDB backends the Gateway uses: the memory ``backend_config`` (``None``: not KurrentDB) and whether run events are."""

    memory: Mapping[str, Any] | None
    run_events: bool


def _is_kurrent_storage(storage_class: Any) -> bool:
    if not isinstance(storage_class, str) or "." not in storage_class:
        return False
    try:
        from .memory import KurrentdbMemoryStorage

        module_path, name = storage_class.rsplit(".", 1)
        found = getattr(importlib.import_module(module_path), name)
    except Exception:
        return False
    return isinstance(found, type) and issubclass(found, KurrentdbMemoryStorage)


def backends_from(memory_backend_config: Mapping[str, Any] | None, run_events_backend: Any) -> Backends:
    """Which KurrentDB backends a Gateway config uses (``memory.backend_config``, ``run_events.backend``)."""
    memory = dict(memory_backend_config or {})
    return Backends(memory=memory if _is_kurrent_storage(memory.get("storage_class")) else None, run_events=run_events_backend == RUN_EVENT_BACKEND)


def gateway_backends() -> Backends:
    """The default ``config_source``: the Gateway's loaded app config."""
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    return backends_from(getattr(app_config.memory, "backend_config", None), getattr(app_config.run_events, "backend", None))


def _default_memory(config: Any, clock: Callable[[], float]) -> Any:
    from .memory import KurrentdbMemoryStorage

    return KurrentdbMemoryStorage(config, clock=clock)


def _default_store(clock: Callable[[], float]) -> Any:
    from .run_events import KurrentRunEventStore

    return KurrentRunEventStore({}, clock=clock)


class KurrentRecoveryService:
    """Deletion recovery: primary sides at start (bounded), then primary and canonical obligations in the background."""

    def __init__(
        self,
        *,
        memory_factory: Callable[[Any], Any] | None = None,
        store_factory: Callable[[], Any] | None = None,
        config_source: Callable[[], Backends] | None = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        startup_budget: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        # Nothing here connects or reads settings: install() builds the service.
        self._clock = clock or time.time
        self._memory_factory = memory_factory or (lambda config: _default_memory(config, self._clock))
        self._config_source = config_source or gateway_backends
        self._store_factory = store_factory or (lambda: _default_store(self._clock))
        self._interval = interval
        self._startup_budget = startup_budget
        self._memory: Any = None
        self._store: Any = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._inflight: concurrent.futures.Future | None = None
        self._task: asyncio.Task[None] | None = None
        self._timeout = 10.0
        self._startup_complete = True

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, deps: Any = None) -> None:
        try:
            backends = self._config_source()
        except Exception:
            logger.warning("KurrentDB recovery service not started: the Gateway config could not be read", exc_info=True)
            return
        if backends.memory is None and not backends.run_events:
            logger.info("KurrentDB recovery service idle: neither memory nor run events use KurrentDB")
            return
        try:
            settings = load_settings()
            self._timeout = settings.timeout
            if backends.memory is not None:
                from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

                self._memory = self._memory_factory(DeerMemConfig.from_backend_config(dict(backends.memory)))
            if backends.run_events:
                self._store = self._store_factory()
        except Exception:
            logger.warning("KurrentDB recovery service not started: settings or storage unavailable", exc_info=True)
            self._memory = self._store = None
            return
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=THREAD_NAME)
        budget = self._startup_budget if self._startup_budget is not None else self._timeout
        # Separate budgets: a stuck memory recovery never keeps run-event recovery from being tried.
        self._startup_complete = True
        for name, recover in (("memory", self._recover_memory), ("run-event", self._recover_run_events)):
            try:
                await asyncio.wait_for(recover(), budget)
            except TimeoutError:
                self._startup_complete = False
                logger.warning("Startup %s deletion recovery did not finish within %ss; continuing in the background", name, budget)
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

    async def _recover_memory(self) -> None:
        if self._memory is None:
            return
        try:
            await self._in_thread(self._memory.recover_deletions)
        except Exception:
            logger.warning("Memory deletion recovery failed; retrying in the background", exc_info=True)

    async def _recover_run_events(self) -> None:
        if self._store is None:
            return
        try:
            await self._store.recover_deletions()
        except Exception:
            logger.warning("Run-event deletion recovery failed; retrying in the background", exc_info=True)

    async def recover_primary(self) -> None:
        """Finish or abandon every open primary deletion side: memory, then run events; failures are logged."""
        await self._recover_memory()
        await self._recover_run_events()

    async def run_canonical(self) -> float | None:
        """One pass over the canonical obligations; returns when the next verification is due (``None``: none waiting)."""
        runners = []
        if self._memory is not None:
            runners.append(("memory", lambda: self._in_thread(self._memory.run_canonical_obligations)))
        if self._store is not None:
            runners.append(("run-event", self._store.run_canonical_obligations))
        due: list[float] = []
        for name, runner in runners:
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
        # A startup recovery cut short by its budget is retried first, with the canonical work.
        next_due = await self._pass(self.run_canonical if self._startup_complete else self.run_once)
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
