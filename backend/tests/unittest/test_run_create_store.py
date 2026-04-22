from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.gateway.services.runs.store.create_store import AppRunCreateStore
from deerflow.runtime.runs.types import RunRecord, RunStatus


@pytest.mark.anyio
async def test_create_run_syncs_thread_meta_assistant_id():
    repo = AsyncMock()
    thread_meta_storage = AsyncMock()
    thread_meta_storage.ensure_thread.return_value.assistant_id = None

    store = AppRunCreateStore(repo, thread_meta_storage=thread_meta_storage)
    record = RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id="lead_agent",
        status=RunStatus.pending,
        temporary=False,
        multitask_strategy="reject",
    )

    await store.create_run(record)

    repo.create.assert_awaited_once()
    thread_meta_storage.ensure_thread.assert_awaited_once_with(
        thread_id="thread-1",
        assistant_id="lead_agent",
    )
    thread_meta_storage.sync_thread_assistant_id.assert_awaited_once_with(
        thread_id="thread-1",
        assistant_id="lead_agent",
    )
