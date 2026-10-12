"""Opt-in Jina attempt admission, shared by threads/loops in this process.

Tool extra ``request_admission`` is null (disabled before first enablement) or a
mapping containing all three Policy fields. Once enabled, the policy applies to
all later Jina calls in the process and is immutable until process restart.
Tickets reserve capacity under a short threading lock; only their owning loop
touches the wakeup future. No credentials, URLs, or caller identities are keys.
"""

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


class JinaAdmissionError(Exception):
    """Terminal local rejection; never a provider status or retryable I/O error."""


@dataclass(frozen=True)
class Policy:
    max_concurrent_requests: int
    max_queue_size: int
    max_wait_seconds: float

    @classmethod
    def parse(cls, value: object) -> "Policy":
        if not isinstance(value, dict) or set(value) != {"max_concurrent_requests", "max_queue_size", "max_wait_seconds"}:
            raise ValueError("request_admission requires max_concurrent_requests, max_queue_size, max_wait_seconds")
        for name, minimum in (("max_concurrent_requests", 1), ("max_queue_size", 0)):
            if type(value[name]) is not int or value[name] < minimum:
                raise ValueError(f"request_admission.{name} must be an integer >= {minimum}")
        wait = value["max_wait_seconds"]
        try:
            valid_wait = type(wait) in (int, float) and math.isfinite(wait) and wait > 0
        except OverflowError:
            valid_wait = False
        if not valid_wait:
            raise ValueError("request_admission.max_wait_seconds must be finite and positive")
        return cls(**value)


@dataclass(eq=False)
class _Ticket:
    loop: asyncio.AbstractEventLoop
    wakeup: asyncio.Future
    deadline: float
    state: str = "queued"

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise JinaAdmissionError("wait expired")

    def wake(self) -> None:
        if not self.wakeup.done():
            self.wakeup.set_result(None)


class Admission:
    def __init__(self, policy: Policy):
        self.policy = policy
        self._lock = threading.Lock()
        self._queue: deque[_Ticket] = deque()
        self._active = 0

    def _drain(self) -> None:
        """Called only under _lock; reserve before waking to prevent barging."""
        while self._queue:
            ticket = self._queue[0]
            expired = time.monotonic() >= ticket.deadline
            if not expired and self._active >= self.policy.max_concurrent_requests:
                break
            self._queue.popleft()
            ticket.state = "expired" if expired else "granted"
            if not expired:
                self._active += 1
            try:
                ticket.loop.call_soon_threadsafe(ticket.wake)
            except RuntimeError:  # An owner loop was closed without draining tasks.
                if ticket.state == "granted":
                    self._active -= 1
                ticket.state = "released"

    def _finish(self, ticket: _Ticket) -> None:
        with self._lock:
            if ticket.state == "queued":
                self._queue.remove(ticket)
            elif ticket.state == "granted":
                self._active -= 1
            ticket.state = "released"
            self._drain()

    @asynccontextmanager
    async def attempt(self, remaining: float | None) -> AsyncIterator[_Ticket]:
        loop = asyncio.get_running_loop()
        wait = self.policy.max_wait_seconds if remaining is None else min(remaining, self.policy.max_wait_seconds)
        ticket = _Ticket(loop, loop.create_future(), time.monotonic() + wait)
        with self._lock:
            self._drain()
            if wait <= 0:
                raise JinaAdmissionError("wait expired")
            if not self._queue and self._active < self.policy.max_concurrent_requests:
                ticket.state = "granted"
                self._active += 1
            elif len(self._queue) >= self.policy.max_queue_size:
                raise JinaAdmissionError("queue full")
            else:
                self._queue.append(ticket)
        try:
            if ticket.state == "queued":
                try:
                    async with asyncio.timeout(max(0, ticket.deadline - time.monotonic())):
                        await ticket.wakeup
                except TimeoutError:
                    raise JinaAdmissionError("wait expired") from None
            # A grant can race timeout/cancellation or sit in a stalled loop.
            if ticket.state != "granted" or time.monotonic() >= ticket.deadline:
                raise JinaAdmissionError("wait expired")
            yield ticket
        finally:
            self._finish(ticket)


_registry_lock = threading.Lock()
_admission: Admission | None = None


def get_admission(value: object) -> Admission | None:
    """Null is disabled initially; after enablement every caller shares the policy."""
    global _admission
    with _registry_lock:
        if value is None:
            return _admission
        policy = Policy.parse(value)
        if _admission is None:
            _admission = Admission(policy)
        elif _admission.policy != policy:
            raise ValueError("Jina request_admission changed; restart required")
        return _admission
