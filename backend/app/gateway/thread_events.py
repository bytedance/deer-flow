"""In-process thread event fan-out for browser notifications."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ThreadEvent:
    event: str
    data: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)


ThreadEventQueue = asyncio.Queue[ThreadEvent | None]


class ThreadEventHub:
    """Small SSE fan-out hub keyed by thread and owner user.

    Events are intentionally ephemeral. Durable conversation state remains in
    run/checkpoint storage; this hub only wakes active browser sessions so they
    can refresh the authoritative thread history.
    """

    def __init__(self) -> None:
        self._subscribers: defaultdict[tuple[str, str | None], set[ThreadEventQueue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(self, thread_id: str, user_id: str | None) -> AsyncIterator[ThreadEventQueue]:
        queue: ThreadEventQueue = asyncio.Queue(maxsize=100)
        key = (thread_id, user_id)
        async with self._lock:
            self._subscribers[key].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                queues = self._subscribers.get(key)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._subscribers.pop(key, None)

    async def publish(
        self,
        thread_id: str,
        event: str,
        data: dict[str, Any],
        *,
        user_id: str | None,
    ) -> None:
        item = ThreadEvent(event=event, data=data)
        async with self._lock:
            queues = list(self._subscribers.get((thread_id, user_id), set()))
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(item)

    async def close(self) -> None:
        async with self._lock:
            queues = [queue for group in self._subscribers.values() for queue in group]
            self._subscribers.clear()
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(None)
