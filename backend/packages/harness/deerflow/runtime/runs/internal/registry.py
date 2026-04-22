"""In-memory run registry for runs domain state."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from ..types import INFLIGHT_STATUSES, RunRecord, RunSpec, RunStatus


class RunRegistry:
    """In-memory source of truth for run records and their status."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self._thread_index: dict[str, set[str]] = {}  # thread_id -> set[run_id]
        self._lock = asyncio.Lock()

    async def create(self, spec: RunSpec) -> RunRecord:
        """Create a new RunRecord from RunSpec."""
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        record = RunRecord(
            run_id=run_id,
            thread_id=spec.scope.thread_id,
            assistant_id=spec.assistant_id,
            status="pending",
            temporary=spec.scope.temporary,
            multitask_strategy=spec.multitask_strategy,
            metadata=dict(spec.metadata),
            follow_up_to_run_id=spec.follow_up_to_run_id,
            created_at=now,
            updated_at=now,
        )

        async with self._lock:
            self._records[run_id] = record
            # Update thread index
            if spec.scope.thread_id not in self._thread_index:
                self._thread_index[spec.scope.thread_id] = set()
            self._thread_index[spec.scope.thread_id].add(run_id)

        return record

    def get(self, run_id: str) -> RunRecord | None:
        """Get RunRecord by run_id."""
        return self._records.get(run_id)

    async def list_by_thread(self, thread_id: str) -> list[RunRecord]:
        """List all RunRecords for a thread."""
        async with self._lock:
            run_ids = self._thread_index.get(thread_id, set())
            return [self._records[rid] for rid in run_ids if rid in self._records]

    async def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> None:
        """Update run status and optional fields."""
        async with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return

            record.status = status
            record.updated_at = datetime.now(timezone.utc).isoformat()

            if error is not None:
                record.error = error
            if started_at is not None:
                record.started_at = started_at
            if ended_at is not None:
                record.ended_at = ended_at

    async def has_inflight(self, thread_id: str) -> bool:
        """Check if thread has any inflight runs."""
        async with self._lock:
            run_ids = self._thread_index.get(thread_id, set())
            for rid in run_ids:
                record = self._records.get(rid)
                if record and record.status in INFLIGHT_STATUSES:
                    return True
            return False

    async def interrupt_inflight(self, thread_id: str) -> list[str]:
        """
        Mark all inflight runs for a thread as interrupted.

        Returns list of interrupted run_ids.
        """
        interrupted: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            run_ids = self._thread_index.get(thread_id, set())
            for rid in run_ids:
                record = self._records.get(rid)
                if record and record.status in INFLIGHT_STATUSES:
                    record.status = "interrupted"
                    record.updated_at = now
                    record.ended_at = now
                    interrupted.append(rid)

        return interrupted

    async def update_metadata(self, run_id: str, metadata: dict[str, Any]) -> None:
        """Update run metadata."""
        async with self._lock:
            record = self._records.get(run_id)
            if record is not None:
                record.metadata.update(metadata)
                record.updated_at = datetime.now(timezone.utc).isoformat()

    async def delete(self, run_id: str) -> bool:
        """Delete a run record. Returns True if deleted."""
        async with self._lock:
            record = self._records.pop(run_id, None)
            if record is None:
                return False

            # Update thread index
            thread_runs = self._thread_index.get(record.thread_id)
            if thread_runs:
                thread_runs.discard(run_id)

            return True

    def count(self) -> int:
        """Return total number of records."""
        return len(self._records)

    def count_by_status(self, status: RunStatus) -> int:
        """Return count of records with given status."""
        return sum(1 for r in self._records.values() if r.status == status)


# Compatibility alias during the refactor.
RuntimeRunRegistry = RunRegistry
