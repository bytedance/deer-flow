"""Per-scope typed storage handed to extensions."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any


class ExtensionData:
    """Extension-private state attached to one host-owned scope.

    Keyed by type rather than by string so independent extensions cannot
    collide on a key. The host creates one instance per scope (app, task) and
    drops it when that scope ends, which is why extensions never need a
    stale-handle check: they are handed the store for the current scope on
    every callback instead of capturing one.
    """

    __slots__ = ("_scope_id", "_entries", "_lock")

    def __init__(self, scope_id: str) -> None:
        self._scope_id = scope_id
        self._entries: dict[type, Any] = {}
        self._lock = RLock()

    @property
    def scope_id(self) -> str:
        """Host identity of the scope this store is attached to."""
        return self._scope_id

    def get[T](self, typ: type[T]) -> T | None:
        with self._lock:
            return self._entries.get(typ)

    def get_or_init[T](self, typ: type[T], init: Callable[[], T]) -> T:
        """Return the stored value, creating it from ``init`` when absent.

        ``init`` runs while the store is locked. It may compose other state in
        this store, but heavyweight lazy work belongs inside the stored value
        itself.
        """
        with self._lock:
            existing = self._entries.get(typ)
            if existing is not None:
                return existing
            created = init()
            self._entries[typ] = created
            return created

    def set[T](self, value: T) -> None:
        with self._lock:
            self._entries[type(value)] = value

    def remove[T](self, typ: type[T]) -> T | None:
        with self._lock:
            return self._entries.pop(typ, None)
