"""Recovery retries must not duplicate END or truncate retained output."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.deps import _mark_latest_startup_recovered_threads_error, _publish_recovered_run_stream_end
from deerflow.runtime.runs.manager import ORPHAN_RECOVERY_STOP_REASON, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.stream_bridge import END_SENTINEL
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest.mark.anyio
async def test_recovered_stream_retries_schedule_cleanup_once(monkeypatch):
    bridge = MemoryStreamBridge(queue_maxsize=2)
    cleanup = AsyncMock()
    monkeypatch.setattr(bridge, "cleanup", cleanup)
    record = SimpleNamespace(run_id="recovered", thread_id="thread-1")
    await bridge.publish(record.run_id, "values", {"answer": "retained"})

    results = await asyncio.gather(*(_publish_recovered_run_stream_end(bridge, [record]) for _ in range(5)))
    cleanup_tasks = [task for tasks, _complete in results for _run_id, task in tasks]
    await asyncio.gather(*cleanup_tasks)

    assert all(complete for _tasks, complete in results)
    assert len(cleanup_tasks) == 1
    cleanup.assert_awaited_once_with(record.run_id, delay=60.0)
    received = [item async for item in bridge.subscribe(record.run_id)]
    assert received[0].data == {"answer": "retained"}
    assert received[1:] == [END_SENTINEL]


@pytest.mark.anyio
async def test_recovered_end_preserves_missing_stream_and_existing_end():
    bridge = MemoryStreamBridge()
    assert await bridge.publish_recovered_end("missing") is False
    assert not await bridge.stream_exists("missing")

    await bridge.publish("finished", "values", {"answer": "retained"})
    await bridge.publish_end("finished")
    assert await bridge.publish_recovered_end("finished") is False
    received = [item async for item in bridge.subscribe("finished")]
    assert received[0].data == {"answer": "retained"}
    assert received[1:] == [END_SENTINEL]


@pytest.mark.anyio
async def test_recovered_end_does_not_turn_empty_subscriber_handle_into_history():
    bridge = MemoryStreamBridge()
    bridge._get_or_create_stream("waiting-subscriber")
    assert await bridge.publish_recovered_end("waiting-subscriber") is False
    assert not await bridge.stream_exists("waiting-subscriber")


@pytest.mark.anyio
@pytest.mark.parametrize("recovered_status", [RunStatus.error, RunStatus.interrupted])
async def test_startup_projects_the_recovered_outcome_including_accepted_cancellation(recovered_status):
    manager = RunManager()
    record = await manager.create("thread-startup-projection")
    await manager.set_status(record.run_id, recovered_status, stop_reason=ORPHAN_RECOVERY_STOP_REASON)
    thread_store = SimpleNamespace(update_status=AsyncMock())

    await _mark_latest_startup_recovered_threads_error(manager, thread_store, [record])

    thread_store.update_status.assert_awaited_once_with(record.thread_id, recovered_status.value, user_id=None)
