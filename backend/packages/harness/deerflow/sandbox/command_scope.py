"""Process ownership for cancellable bash calls; retained only for one execution lease."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

COMMAND_OWNER_ENV = "DEERFLOW_COMMAND_OWNER"


class CommandScopeCancelled(RuntimeError):
    """An explicitly cancelled execution must not start or retry commands."""


@dataclass
class CommandScope:
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    cancelled: threading.Event = field(default_factory=threading.Event)
    cleaned: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    processes: list[Any] = field(default_factory=list)

    def check(self) -> None:
        if self.cancelled.is_set():
            raise CommandScopeCancelled("Sandbox execution was cancelled")


class CommandScopes:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scopes: dict[str, CommandScope] = {}

    def get(self, owner: str) -> CommandScope:
        with self._lock:
            scope = self._scopes.get(owner)
            if scope is None:
                scope = self._scopes[owner] = CommandScope()
            return scope

    def find(self, owner: str) -> CommandScope | None:
        with self._lock:
            return self._scopes.get(owner)

    def request_cancel(self, owner: str) -> None:
        scope = self.get(owner)
        scope.cancelled.set()

    def release(self, owner: str) -> None:
        with self._lock:
            self._scopes.pop(owner, None)


_active: ContextVar[tuple[object, CommandScope] | None] = ContextVar("sandbox_command_owner", default=None)


@contextmanager
def command_owner(sandbox: object, owner: str | None):
    """Bind server-owned execution identity across the synchronous tool bridge."""
    if not owner or not getattr(sandbox, "supports_command_cancellation", False):
        yield
        return
    scope = sandbox._command_scopes.get(owner)
    scope.check()
    token = _active.set((sandbox, scope))
    try:
        yield
    finally:
        _active.reset(token)


def current_command_scope(sandbox: object | None = None) -> CommandScope | None:
    active = _active.get()
    if active is None or (sandbox is not None and active[0] is not sandbox):
        return None
    return active[1]


@contextmanager
def command_lock(lock, scope: CommandScope | None):
    """A cancelled queued command must not wait for another execution's I/O."""
    if scope is None:
        with lock:
            yield
        return
    while not lock.acquire(timeout=0.1):
        scope.check()
    try:
        scope.check()
        yield
    finally:
        lock.release()
