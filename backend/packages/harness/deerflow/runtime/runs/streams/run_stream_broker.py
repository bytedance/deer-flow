"""Realtime run stream broker contract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from ..domain import RunId


@dataclass(frozen=True)
class RunStreamEvent:
    id: str
    event: str
    data: Any


class RunStreamBroker(Protocol):
    """Realtime publish/subscribe boundary for run streams."""

    async def publish(self, run_id: RunId, event: str, data: Any) -> None:
        pass

    async def publish_terminal(self, run_id: RunId, *, event: str = "end", data: Any = None) -> None:
        pass

    def subscribe(
        self,
        run_id: RunId,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[RunStreamEvent]:
        pass

    async def cleanup(self, run_id: RunId, *, delay: float = 0) -> None:
        pass


__all__ = [
    "RunStreamBroker",
    "RunStreamEvent",
]
