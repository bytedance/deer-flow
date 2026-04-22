"""Delete-side durable boundary for runs."""

from __future__ import annotations

from typing import Protocol


class RunDeleteStore(Protocol):
    """Minimal protocol for removing durable run records."""

    async def delete_run(self, run_id: str) -> bool: ...
