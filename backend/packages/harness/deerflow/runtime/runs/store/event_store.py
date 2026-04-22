"""Run event store boundary used by runs callbacks."""

from __future__ import annotations

from typing import Any, Protocol


class RunEventStore(Protocol):
    """Minimal append-only event store protocol for execution callbacks."""

    async def put_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
