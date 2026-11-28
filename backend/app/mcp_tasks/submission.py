"""Keep a submission owned until its caller accepts it or cleanup settles."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Literal

from deerflow.runtime.cancellation import wait_for_task_until

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class _Submission[T]:
    delivery: Future[T] = field(default_factory=Future)
    settled: Future[None] = field(default_factory=Future)
    lock: threading.Lock = field(default_factory=threading.Lock)
    receipt: Literal["waiting", "delivered", "abandoned"] = "waiting"
    task: asyncio.Task[T] | None = None
    handoff: asyncio.Task[None] | None = None

    def resolve(self, receipt: Literal["delivered", "abandoned"]) -> bool:
        # Delivery and shutdown can race on different event-loop threads.
        with self.lock:
            if self.receipt == "waiting":
                self.receipt = receipt
            return self.receipt == receipt


def _observe(future: asyncio.Future) -> None:
    if not future.cancelled():
        future.exception()


class SubmissionOwner[T]:
    """An owner-loop registry with explicit acknowledgement across caller loops."""

    def __init__(self, abandon: Callable[[T], Awaitable[None]]) -> None:
        self._abandon = abandon
        self._loop: asyncio.AbstractEventLoop | None = None
        self._gate = threading.Lock()
        self._accepting = True
        self._generation = 0
        self._submissions: set[_Submission[T]] = set()
        self._deadline: float | None = None

    def _bind(self) -> asyncio.AbstractEventLoop:
        with self._gate:
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            return self._loop

    def start(self) -> bool:
        if self._bind() is not asyncio.get_running_loop():
            raise RuntimeError("MCP task service must restart on its owning event loop")
        for submission in tuple(self._submissions):
            self._settle(submission)
        if self._submissions:
            return False
        with self._gate:
            if not self._accepting:
                self._generation += 1
                self._accepting = True
                self._deadline = None
        return True

    async def submit(self, operation: Callable[[], Awaitable[T]], *, timeout: float) -> T:
        owner_loop = self._bind()
        with self._gate:
            if not self._accepting:
                raise RuntimeError("MCP task service is stopping; new submissions are unavailable")
            generation = self._generation
        submission = _Submission[T]()
        # Schedule a factory, not a coroutine: rejecting a stopped loop must
        # not leave a never-awaited coroutine or start a remote request.
        owner_loop.call_soon_threadsafe(self._admit, submission, generation, operation, context=copy_context())
        delivery = asyncio.wrap_future(submission.delivery)
        delivery.add_done_callback(_observe)
        try:
            result = await asyncio.shield(delivery)
            if not submission.resolve("delivered"):
                raise asyncio.CancelledError
            return result
        except asyncio.CancelledError:
            submission.resolve("abandoned")
            self._notify_settlement(submission)
            settled = asyncio.wrap_future(submission.settled)
            deadline = asyncio.get_running_loop().time() + timeout
            if not await wait_for_task_until(settled, deadline=deadline):
                logger.warning("MCP submission cleanup reached its deadline; ownership resolution continues in the background")
            raise
        finally:
            # An exception is also a delivered outcome. Successful remote
            # results stay retained until this acknowledgement or abandonment.
            submission.resolve("delivered")
            self._notify_settlement(submission)

    def _notify_settlement(self, submission: _Submission[T]) -> None:
        assert self._loop is not None
        if self._loop is asyncio.get_running_loop():
            self._settle(submission)
            return
        try:
            self._loop.call_soon_threadsafe(self._settle, submission)
        except RuntimeError:
            # Preserve caller cancellation when the process loop is already
            # closed; no coroutine has been created by this notification.
            logger.warning("MCP submission acknowledgement arrived after its owner loop closed")

    def _admit(self, submission: _Submission[T], generation: int, operation: Callable[[], Awaitable[T]]) -> None:
        with self._gate:
            admitted = self._accepting and generation == self._generation
        if not admitted or submission.receipt == "abandoned":
            submission.delivery.set_exception(asyncio.CancelledError("MCP submission was abandoned before admission"))
            submission.settled.set_result(None)
            return
        self._submissions.add(submission)
        submission.task = asyncio.create_task(operation(), name="mcp-owned-submission")
        submission.task.add_done_callback(lambda _task: self._completed(submission))

    def _completed(self, submission: _Submission[T]) -> None:
        assert submission.task is not None
        try:
            result = submission.task.result()
        except BaseException as exc:
            submission.delivery.set_exception(exc)
            if submission.receipt == "abandoned" and not isinstance(exc, asyncio.CancelledError):
                logger.warning("Abandoned MCP submission failed during ownership resolution", exc_info=(type(exc), exc, exc.__traceback__))
            self._finish(submission)
            return
        submission.delivery.set_result(result)
        self._settle(submission)

    def _settle(self, submission: _Submission[T]) -> None:
        if submission not in self._submissions or submission.task is None or not submission.task.done():
            return
        if submission.receipt == "delivered":
            self._finish(submission)
        elif submission.receipt == "abandoned" and submission.handoff is None:
            # _completed may still be queued behind the cancellation callback.
            # It alone consumes submission failures; only a result can transfer
            # newly established ownership to the durable cancellation path.
            if submission.task.cancelled() or submission.task.exception() is not None:
                return
            submission.handoff = asyncio.create_task(self._abandon(submission.task.result()), name="mcp-submission-handoff")
            submission.handoff.add_done_callback(lambda task: self._handoff_completed(submission, task))

    def _handoff_completed(self, submission: _Submission[T], task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except BaseException:
            logger.exception("Failed to finish abandoned MCP submission cancellation")
        self._finish(submission)

    def _finish(self, submission: _Submission[T]) -> None:
        self._submissions.discard(submission)
        if not submission.settled.done():
            submission.settled.set_result(None)

    def close(self, *, timeout: float) -> float:
        loop = self._bind()
        if loop is not asyncio.get_running_loop():
            raise RuntimeError("MCP task service must stop on its owning event loop")
        with self._gate:
            self._accepting = False
            if self._deadline is None:
                self._deadline = loop.time() + timeout
            deadline = self._deadline
        for submission in tuple(self._submissions):
            submission.resolve("abandoned")
            self._settle(submission)
        return deadline

    async def drain(self, *, deadline: float) -> None:
        # Admission is closed before shutdown drains. Each retained receipt
        # includes its handoff, so completion cannot create unobserved cleanup.
        for submission in tuple(self._submissions):
            if not await wait_for_task_until(asyncio.wrap_future(submission.settled), deadline=deadline):
                logger.warning("MCP submission drain reached its deadline; %d submission(s) remain owned", len(self._submissions))
                return
