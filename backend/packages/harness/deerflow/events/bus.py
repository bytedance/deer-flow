"""Event bus — in-memory pub/sub for system events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from deerflow.events.models import Event, EventType

logger = logging.getLogger(__name__)

Callback = Callable[[Event], Awaitable[None]]


class EventBus:
    """In-memory pub/sub event bus (singleton)."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Callback]] = {}
        self._wildcard_subscribers: list[Callback] = []

    def subscribe(self, event_type: EventType | None, callback: Callback) -> None:
        """Register a callback for a specific event type, or all types if None."""
        if event_type is None:
            self._wildcard_subscribers.append(callback)
        else:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: EventType | None, callback: Callback) -> None:
        """Remove a previously registered callback."""
        if event_type is None:
            self._wildcard_subscribers = [cb for cb in self._wildcard_subscribers if cb is not callback]
        else:
            subs = self._subscribers.get(event_type, [])
            self._subscribers[event_type] = [cb for cb in subs if cb is not callback]

    def publish(self, event: Event) -> None:
        """Synchronously publish an event to all matching subscribers.

        Each callback is scheduled as a fire-and-forget asyncio task.
        """
        callbacks: list[Callback] = list(self._wildcard_subscribers)
        callbacks.extend(self._subscribers.get(event.type, []))

        for cb in callbacks:
            try:
                asyncio.create_task(cb(event))
            except Exception:
                logger.exception("Failed to schedule event callback for %s", event.type)

    async def apublish(self, event: Event) -> None:
        """Asynchronously publish an event and await all callbacks."""
        callbacks: list[Callback] = list(self._wildcard_subscribers)
        callbacks.extend(self._subscribers.get(event.type, []))

        results = await asyncio.gather(
            *(cb(event) for cb in callbacks),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Event callback failed: %s", result)


# Singleton
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    global _event_bus
    _event_bus = None
