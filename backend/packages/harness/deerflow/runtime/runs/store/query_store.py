"""Read-side boundary for durable run queries."""

from __future__ import annotations

from typing import Protocol

from ..types import RunRecord


class RunQueryStore(Protocol):
    """Read durable run records for public query APIs."""

    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def list_runs(
        self,
        thread_id: str,
        *,
        limit: int = 100,
    ) -> list[RunRecord]: ...
