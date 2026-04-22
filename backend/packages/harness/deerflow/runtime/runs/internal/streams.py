"""Internal run stream adapter over StreamBridge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.runtime.stream_bridge import JSONValue, StreamBridge, StreamEvent

from deerflow.runtime.stream_bridge import StreamStatus


class RunStreamService:
    """Thin runs-domain adapter over the harness stream bridge contract."""

    def __init__(self, bridge: "StreamBridge") -> None:
        self._bridge = bridge

    async def publish_event(
        self,
        run_id: str,
        *,
        event: str,
        data: "JSONValue",
    ) -> str:
        """Publish a replayable run event."""
        return await self._bridge.publish(run_id, event, data)

    async def publish_end(self, run_id: str) -> str:
        """Publish a successful terminal signal."""
        return await self._bridge.publish_terminal(run_id, StreamStatus.ENDED)

    async def publish_cancelled(
        self,
        run_id: str,
        *,
        data: "JSONValue" = None,
    ) -> str:
        """Publish a cancelled terminal signal."""
        return await self._bridge.publish_terminal(
            run_id,
            StreamStatus.CANCELLED,
            data,
        )

    async def publish_error(
        self,
        run_id: str,
        *,
        data: "JSONValue",
    ) -> str:
        """Publish a failed terminal signal."""
        return await self._bridge.publish_terminal(
            run_id,
            StreamStatus.ERRORED,
            data,
        )

    def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        """Subscribe to a run stream with resume support."""
        return self._bridge.subscribe(
            run_id,
            last_event_id=last_event_id,
            heartbeat_interval=heartbeat_interval,
        )

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release per-run bridge resources after completion."""
        await self._bridge.cleanup(run_id, delay=delay)
