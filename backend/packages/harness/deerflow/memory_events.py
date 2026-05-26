"""In-process pub/sub for memory update events.

Provides SSE-compatible broadcasting so connected clients can receive
real-time notifications when memory facts are created, updated, or deleted.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


class MemoryEventBus:
    """Simple in-process event bus for memory updates.

    Each subscriber gets an asyncio.Queue. Events are filtered by tenant_id
    at publish time so subscribers only see events for their tenant.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, tenant_id: str) -> asyncio.Queue:
        """Create a subscription queue for a tenant."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(tenant_id, []).append(queue)
        return queue

    def unsubscribe(self, tenant_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscription queue."""
        subs = self._subscribers.get(tenant_id, [])
        if queue in subs:
            subs.remove(queue)
        if not subs:
            self._subscribers.pop(tenant_id, None)

    async def publish(
        self,
        tenant_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Publish an event to all subscribers of a tenant."""
        subs = self._subscribers.get(tenant_id, [])
        if not subs:
            return
        message = {"event": event_type, "data": data}
        dead: list[asyncio.Queue] = []
        for queue in subs:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self.unsubscribe(tenant_id, queue)

    async def stream(
        self,
        tenant_id: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings for a subscriber.

        Used as the body of a StreamingResponse for the /api/memory/events endpoint.
        """
        queue = self.subscribe(tenant_id)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    payload = json.dumps(message["data"], default=str, ensure_ascii=False)
                    yield f"event: {message['event']}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(tenant_id, queue)


_bus: MemoryEventBus | None = None


def get_memory_event_bus() -> MemoryEventBus:
    """Get the singleton memory event bus."""
    global _bus
    if _bus is None:
        _bus = MemoryEventBus()
    return _bus
