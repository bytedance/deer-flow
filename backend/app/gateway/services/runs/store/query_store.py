"""App-owned durable run query adapter."""

from __future__ import annotations

from deerflow.runtime.runs.store import RunQueryStore
from deerflow.runtime.runs.types import RunRecord, RunStatus

from app.infra.storage.runs import RunReadRepository, RunRow


class AppRunQueryStore(RunQueryStore):
    """Map app-side durable run rows into harness RunRecord DTOs."""

    def __init__(self, repo: RunReadRepository) -> None:
        self._repo = repo

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = await self._repo.get(run_id)
        if row is None:
            return None
        return self._to_run_record(row)

    async def list_runs(
        self,
        thread_id: str,
        *,
        limit: int = 100,
    ) -> list[RunRecord]:
        rows = await self._repo.list_by_thread(thread_id, limit=limit)
        return [self._to_run_record(row) for row in rows]

    def _to_run_record(self, row: RunRow) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            assistant_id=row.get("assistant_id"),
            status=RunStatus(row.get("status", "pending")),
            temporary=False,
            multitask_strategy=row.get("multitask_strategy", "reject"),
            metadata=row.get("metadata", {}),
            follow_up_to_run_id=row.get("follow_up_to_run_id"),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
            error=row.get("error"),
        )
