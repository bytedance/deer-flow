"""Create-side boundary for durable run initialization."""

from __future__ import annotations

from typing import Protocol

from ..types import RunRecord


class RunCreateStore(Protocol):
    """Persist the initial durable row for a newly created run."""

    async def create_run(self, record: RunRecord) -> None: ...
