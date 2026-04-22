"""App-owned durable run creation adapter."""

from __future__ import annotations

from deerflow.runtime.runs.store import RunCreateStore
from deerflow.runtime.runs.types import RunRecord

from app.infra.storage import ThreadMetaStorage
from app.infra.storage.runs import RunWriteRepository


class AppRunCreateStore(RunCreateStore):
    """Write the initial durable row for a newly created run."""

    def __init__(self, repo: RunWriteRepository, thread_meta_storage: ThreadMetaStorage | None = None) -> None:
        self._repo = repo
        self._thread_meta_storage = thread_meta_storage

    async def create_run(self, record: RunRecord) -> None:
        await self._repo.create(
            run_id=record.run_id,
            thread_id=record.thread_id,
            assistant_id=record.assistant_id,
            status=str(record.status),
            metadata=record.metadata,
            follow_up_to_run_id=record.follow_up_to_run_id,
            created_at=record.created_at,
        )
        if self._thread_meta_storage is not None and record.assistant_id:
            thread = await self._thread_meta_storage.ensure_thread(
                thread_id=record.thread_id,
                assistant_id=record.assistant_id,
            )
            if thread.assistant_id != record.assistant_id:
                await self._thread_meta_storage.sync_thread_assistant_id(
                    thread_id=record.thread_id,
                    assistant_id=record.assistant_id,
                )
