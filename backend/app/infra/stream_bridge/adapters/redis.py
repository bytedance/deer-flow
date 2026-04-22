"""Redis-backed stream bridge placeholder owned by the app layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from deerflow.runtime.stream_bridge import StreamBridge, StreamEvent


class RedisStreamBridge(StreamBridge):
    """Reserved app-owned Redis implementation.

    Phase 1 intentionally keeps Redis out of the harness package. The concrete
    implementation will live here once cross-process streaming is introduced.
    """

    def __init__(self, *, redis_url: str) -> None:
        self._redis_url = redis_url

    async def publish(self, run_id: str, event: str, data: Any) -> str:
        raise NotImplementedError("Redis stream bridge will be implemented in app infra")

    async def publish_end(self, run_id: str) -> str:
        raise NotImplementedError("Redis stream bridge will be implemented in app infra")

    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("Redis stream bridge will be implemented in app infra")

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        raise NotImplementedError("Redis stream bridge will be implemented in app infra")
