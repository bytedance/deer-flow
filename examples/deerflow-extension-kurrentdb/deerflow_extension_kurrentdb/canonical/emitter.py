"""Best-effort, serialized appends of canonical events, off the caller's critical path.

``CanonicalEmitter.emit(stream, events, primary=, deadline=)`` (and the async
twin) never raises. Each attempt:

1. **pre-check**: drop every event a primary-committed deletion intent of
   ``primary`` covers (``mapping.matches``: its criteria, and origin below the
   intent's exclusive cutoff). Intents count whether open or done, never abandoned
   (``committed_intents_for``), so a delivery delayed past a finished cleanup is
   still suppressed
2. append the rest at the canonical stream's current head (when the stream does
   not exist yet, preceded by ``opening(pending)``, e.g. a session's ``SessionStarted``) (an expected version,
   never ``StreamState.ANY``); a conflict re-reads the head and retries, up to
   ``APPEND_ATTEMPTS`` in all
3. **post-check** (also after an append whose outcome is unknown): if an intent
   covering an appended event became primary-committed meanwhile, append
   ``CanonicalCleanupReopened`` to the deletions index, so that intent's canonical
   cleanup runs again and removes the stale event

Every emission has a fixed wall-clock lifetime, ``MAX_LIFETIME_SECONDS`` from the
primary commit that produced it (``deadline``): once it has passed, the emission
gives up, and each client call's timeout is cut to what is left, so no append is
sent after the deadline. Canonical cleanup verification (Task 13) relies on this.
Ambiguous appends are not fenced (a fence is not a schema event and canonical
streams hold only schema events); verification catches a stale event they leave.

Off the critical path:

- ``BackgroundQueue`` (memory, sync callers on timer threads): one worker thread,
  FIFO, so per-stream order follows commit order (jobs are submitted under the
  scope lock). The thread starts on demand and exits when the queue is empty;
  ``flush`` waits for it. The queue is bounded; a full queue drops the job (logged)
- ``AsyncChains`` (run events): one task per ``(event loop, key)`` draining a FIFO,
  so a thread's emissions keep commit order without holding the store's lock
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from kurrentdbclient import StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .mapping import CanonicalEvent, matches_intent

logger = logging.getLogger(__name__)

#: The maximum lifetime of one emission, from the primary commit that produced it.
MAX_LIFETIME_SECONDS = 60.0
#: Appends per emission across conflicting canonical writers.
APPEND_ATTEMPTS = 5
#: Jobs waiting in one queue (memory) or across one store's chains (run events).
MAX_PENDING = 1024

WORKER_THREAD_NAME = "kurrentdb-canonical"

Outcome = Literal["appended", "suppressed", "conflicted", "expired", "failed", "empty"]


def deadline_from_now() -> float:
    """The deadline of an emission whose primary commit just happened."""
    return time.monotonic() + MAX_LIFETIME_SECONDS


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _keep(events: Sequence[CanonicalEvent], intents: Sequence[Any]) -> list[CanonicalEvent]:
    return [event for event in events if not any(matches_intent(intent, event.metadata) for intent in intents)]


def _covering(events: Sequence[CanonicalEvent], intents: Sequence[Any]) -> list[Any]:
    return [intent for intent in intents if any(matches_intent(intent, event.metadata) for event in events)]


# ``opening(pending)``: the event that opens a stream this emission creates (a session's ``SessionStarted``).
Opening = Callable[[list[CanonicalEvent]], CanonicalEvent | None]


def _with_opening(pending: list[CanonicalEvent], head: int | StreamState, opening: Opening | None) -> list[CanonicalEvent]:
    if opening is None or head is not StreamState.NO_STREAM:
        return pending
    first = opening(pending)
    return pending if first is None else [first, *pending]


def _head(value: Any) -> int | StreamState:
    return StreamState.NO_STREAM if isinstance(value, StreamState) else int(value)


class CanonicalEmitter:
    """Sync emitter; ``client()`` and ``engine()`` are called lazily, in the emitting thread."""

    def __init__(self, client: Callable[[], Any], engine: Callable[[], Any], *, timeout: float):
        self._client = client
        self._engine = engine
        self._timeout = timeout

    def emit(self, stream: str, events: Sequence[CanonicalEvent], *, primary: str, deadline: float, opening: Opening | None = None) -> Outcome:
        try:
            return self._emit(stream, list(events), primary, deadline, opening)
        except Exception:
            logger.warning("Canonical emission of %d event(s) to %r failed", len(events), stream, exc_info=True)
            return "failed"

    def _emit(self, stream: str, pending: list[CanonicalEvent], primary: str, deadline: float, opening: Opening | None) -> Outcome:
        if not pending:
            return "empty"
        engine = self._engine()
        for _attempt in range(APPEND_ATTEMPTS):
            if _remaining(deadline) <= 0:
                logger.warning("Canonical emission to %r outlived its %ss lifetime; dropped", stream, MAX_LIFETIME_SECONDS)
                return "expired"
            pending = _keep(pending, engine.committed_intents_for(primary))
            if not pending:
                return "suppressed"
            client = self._client()
            try:
                head = _head(client.get_current_version(stream, timeout=min(self._timeout, max(_remaining(deadline), 0.001))))
            except NotFoundError:
                head = StreamState.NO_STREAM
            remaining = _remaining(deadline)
            if remaining <= 0:
                continue
            batch = _with_opening(pending, head, opening)
            try:
                client.append_to_stream(stream, events=[event.new_event() for event in batch], current_version=head, timeout=min(self._timeout, remaining))
            except WrongCurrentVersionError:
                continue
            except Exception:
                logger.warning("Canonical append to %r has an unknown outcome; checking for stale deliveries", stream, exc_info=True)
                self._post_check(engine, stream, batch, primary)
                return "failed"
            self._post_check(engine, stream, batch, primary)
            return "appended"
        if _remaining(deadline) <= 0:
            logger.warning("Canonical emission to %r outlived its %ss lifetime; dropped", stream, MAX_LIFETIME_SECONDS)
            return "expired"
        logger.warning("Canonical append to %r kept conflicting with other writers; gave up", stream)
        return "conflicted"

    def _post_check(self, engine: Any, stream: str, appended: list[CanonicalEvent], primary: str) -> None:
        try:
            for intent in _covering(appended, engine.committed_intents_for(primary)):
                logger.info("Stale canonical delivery to %r is covered by deletion %s; reopening its cleanup", stream, intent.intent_id)
                engine.reopen_canonical(intent, str(appended[0].event_id))
        except Exception:
            logger.warning("Post-append deletion check for %r failed; verification will catch a stale delivery", stream, exc_info=True)


class AsyncCanonicalEmitter:
    """``CanonicalEmitter`` over an async client and ``AsyncDeletionEngine``."""

    def __init__(self, client: Callable[[], Awaitable[Any]], engine: Callable[[Any], Any], *, timeout: float):
        self._client = client
        self._engine = engine  # engine(client)
        self._timeout = timeout

    async def emit(self, stream: str, events: Sequence[CanonicalEvent], *, primary: str, deadline: float, opening: Opening | None = None) -> Outcome:
        try:
            return await self._emit(stream, list(events), primary, deadline, opening)
        except Exception:
            logger.warning("Canonical emission of %d event(s) to %r failed", len(events), stream, exc_info=True)
            return "failed"

    async def _emit(self, stream: str, pending: list[CanonicalEvent], primary: str, deadline: float, opening: Opening | None) -> Outcome:
        if not pending:
            return "empty"
        client = await self._client()
        engine = self._engine(client)
        for _attempt in range(APPEND_ATTEMPTS):
            if _remaining(deadline) <= 0:
                logger.warning("Canonical emission to %r outlived its %ss lifetime; dropped", stream, MAX_LIFETIME_SECONDS)
                return "expired"
            pending = _keep(pending, await engine.committed_intents_for(primary))
            if not pending:
                return "suppressed"
            try:
                head = _head(await client.get_current_version(stream, timeout=min(self._timeout, max(_remaining(deadline), 0.001))))
            except NotFoundError:
                head = StreamState.NO_STREAM
            remaining = _remaining(deadline)
            if remaining <= 0:
                continue
            batch = _with_opening(pending, head, opening)
            try:
                await client.append_to_stream(stream, events=[event.new_event() for event in batch], current_version=head, timeout=min(self._timeout, remaining))
            except WrongCurrentVersionError:
                continue
            except Exception:
                logger.warning("Canonical append to %r has an unknown outcome; checking for stale deliveries", stream, exc_info=True)
                await self._post_check(engine, stream, batch, primary)
                return "failed"
            await self._post_check(engine, stream, batch, primary)
            return "appended"
        if _remaining(deadline) <= 0:
            logger.warning("Canonical emission to %r outlived its %ss lifetime; dropped", stream, MAX_LIFETIME_SECONDS)
            return "expired"
        logger.warning("Canonical append to %r kept conflicting with other writers; gave up", stream)
        return "conflicted"

    async def _post_check(self, engine: Any, stream: str, appended: list[CanonicalEvent], primary: str) -> None:
        try:
            for intent in _covering(appended, await engine.committed_intents_for(primary)):
                logger.info("Stale canonical delivery to %r is covered by deletion %s; reopening its cleanup", stream, intent.intent_id)
                await engine.reopen_canonical(intent, str(appended[0].event_id))
        except Exception:
            logger.warning("Post-append deletion check for %r failed; verification will catch a stale delivery", stream, exc_info=True)


class BackgroundQueue:
    """A FIFO of jobs run by one on-demand worker thread that exits when the queue is empty."""

    def __init__(self, *, max_pending: int = MAX_PENDING):
        self._max_pending = max_pending
        self._jobs: deque[Callable[[], Any]] = deque()
        self._cond = threading.Condition()
        self._worker: threading.Thread | None = None
        self._last_worker: threading.Thread | None = None

    def submit(self, job: Callable[[], Any]) -> bool:
        with self._cond:
            if len(self._jobs) >= self._max_pending:
                logger.warning("Canonical emission queue is full (%d); dropping an emission", self._max_pending)
                return False
            self._jobs.append(job)
            if self._worker is None:
                self._worker = self._last_worker = threading.Thread(target=self._run, name=WORKER_THREAD_NAME, daemon=True)
                self._worker.start()
            return True

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._jobs:
                    self._worker = None
                    self._cond.notify_all()
                    return
                job = self._jobs.popleft()
            try:
                job()
            except Exception:
                logger.warning("Canonical emission job failed", exc_info=True)

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every submitted job ran and the worker thread exited; ``False`` on timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._worker is not None:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(left)
            last = self._last_worker
        if last is not None:
            last.join(None if deadline is None else max(deadline - time.monotonic(), 0))
            return not last.is_alive()
        return True


class AsyncChains:
    """Per-``(event loop, key)`` FIFO chains of coroutine factories, each drained by one task."""

    def __init__(self, *, max_pending: int = MAX_PENDING):
        self._max_pending = max_pending
        self._queues: dict[tuple[int, str], deque[Callable[[], Awaitable[Any]]]] = {}
        self._tasks: dict[tuple[int, str], asyncio.Task[None]] = {}

    def submit(self, key: str, factory: Callable[[], Awaitable[Any]]) -> bool:
        """Queue ``factory`` behind earlier submissions for ``key``; call from the running loop."""
        loop = asyncio.get_running_loop()
        self._prune()
        if sum(len(queue) for queue in self._queues.values()) >= self._max_pending:
            logger.warning("Canonical emission chains are full (%d); dropping an emission", self._max_pending)
            return False
        chain = (id(loop), key)
        self._queues.setdefault(chain, deque()).append(factory)
        if chain not in self._tasks:
            self._tasks[chain] = loop.create_task(self._drain(chain), name=f"{WORKER_THREAD_NAME}:{key}")
        return True

    def _prune(self) -> None:
        """Forget chains whose drain finished or whose loop closed with a drain still pending."""
        for chain, task in list(self._tasks.items()):
            if task.done() or task.get_loop().is_closed():
                self._tasks.pop(chain, None)
                self._queues.pop(chain, None)

    async def _drain(self, chain: tuple[int, str]) -> None:
        queue = self._queues[chain]
        try:
            while queue:
                factory = queue.popleft()
                try:
                    await factory()
                except Exception:
                    logger.warning("Canonical emission job failed", exc_info=True)
        finally:
            self._queues.pop(chain, None)
            self._tasks.pop(chain, None)

    async def flush(self) -> None:
        """Wait for every chain of the running loop to drain."""
        loop_id = id(asyncio.get_running_loop())
        while True:
            tasks = [task for (owner, _key), task in list(self._tasks.items()) if owner == loop_id]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)
