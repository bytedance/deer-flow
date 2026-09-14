"""Bounded FIFO admission shared by synchronous calls and independent loops.

No executor worker or timer task is retained while waiting. Short polling sleeps
allow cancellation and deadlines without storing references to caller loops.
Requests are evenly spaced; idle time never accumulates a burst allowance.
"""

import asyncio
import threading
import time
from collections import deque
from time import monotonic

from langchain_core.rate_limiters import BaseRateLimiter

from deerflow.config.model_config import RequestAdmissionConfig


class AdmissionError(RuntimeError):
    """Local admission failed before making an upstream request."""


class RequestAdmission(BaseRateLimiter):
    def __init__(self, config: RequestAdmissionConfig):
        self.config = config
        self._interval = 60 / config.requests_per_minute
        self._next = 0.0
        self._lock = threading.Lock()
        self._waiters: deque[object] = deque()

    def _try(self, ticket: object | None) -> bool:
        with self._lock:
            now = monotonic()
            if self._waiters and self._waiters[0] is not ticket:
                return False
            if now < self._next:
                return False
            self._next = now + self._interval
            return True

    def _enqueue(self) -> object:
        ticket = object()
        with self._lock:
            if len(self._waiters) >= self.config.max_queue_size:
                raise AdmissionError("LLM admission queue is full; reduce workload or increase queue capacity.")
            self._waiters.append(ticket)
        return ticket

    def _remove(self, ticket: object) -> None:
        with self._lock:
            self._waiters.remove(ticket)

    def _delay(self, deadline: float) -> float:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AdmissionError("LLM admission timed out before dispatch; increase max_wait_seconds or reduce workload.")
        return min(0.05, remaining)

    def acquire(self, *, blocking: bool = True) -> bool:
        if self._try(None):
            return True
        if not blocking:
            return False
        deadline = monotonic() + self.config.max_wait_seconds
        ticket = self._enqueue()
        try:
            while True:
                delay = self._delay(deadline)
                if self._try(ticket):
                    return True
                time.sleep(delay)
        finally:
            self._remove(ticket)

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if self._try(None):
            return True
        if not blocking:
            return False
        deadline = monotonic() + self.config.max_wait_seconds
        ticket = self._enqueue()
        try:
            while True:
                delay = self._delay(deadline)
                if self._try(ticket):
                    return True
                await asyncio.sleep(delay)
        finally:
            self._remove(ticket)


_registry_lock = threading.Lock()
_registry: dict[tuple[str, str], RequestAdmission] = {}


def get_request_admission(model_name: str, config: RequestAdmissionConfig) -> RequestAdmission:
    # Explicit group names never collide with implicit model names. Operator
    # configuration determines the finite set; no user IDs or secrets are keys.
    key = ("group", config.group) if config.group else ("model", model_name)
    with _registry_lock:
        existing = _registry.get(key)
        if existing is not None:
            if existing.config != config:
                raise ValueError("Model request admission policy changed or conflicts within a shared group; align settings and restart the Gateway.")
            return existing
        limiter = RequestAdmission(config)
        _registry[key] = limiter
        return limiter
