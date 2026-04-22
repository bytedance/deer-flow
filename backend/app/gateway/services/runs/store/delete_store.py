"""App-owned durable run deletion adapter."""

from __future__ import annotations

from deerflow.runtime.runs.store import RunDeleteStore

from app.infra.storage.runs import RunDeleteRepository


class AppRunDeleteStore(RunDeleteStore):
    """Delete durable run rows via the app storage adapter."""

    def __init__(self, repo: RunDeleteRepository) -> None:
        self._repo = repo

    async def delete_run(self, run_id: str) -> bool:
        return await self._repo.delete(run_id)
