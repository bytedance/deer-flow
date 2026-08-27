"""Regression tests for in-memory run-record eviction after a run finishes.

The ``RunManager._runs`` registry used to grow without bound: ``cleanup()``
existed but no production path ever called it, so every ``RunRecord`` —
including its ``kwargs["input"]`` copy of the full conversation payload —
stayed resident for the lifetime of the Gateway process. These tests pin the
delayed-eviction scheduling on every terminal path.
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent

CLEANUP_TASK_NAME = "deerflow-run-record-cleanup-{run_id}"


def _make_bridge():
    class _Bridge:
        async def publish(self, run_id, event, data):
            return None

        async def publish_end(self, run_id):
            return None

        async def cleanup(self, run_id, *, delay=0):
            return None

    return _Bridge()


def _scheduled_cleanup_task(run_id: str) -> asyncio.Task | None:
    for task in asyncio.all_tasks():
        if task.get_name() == CLEANUP_TASK_NAME.format(run_id=run_id):
            return task
    return None


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class _OkAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield {"messages": [AIMessage(content="done")]}


class _ExplodingAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover - keeps this a generator


async def _run_to_completion(run_manager: RunManager, record, *, agent_factory) -> None:
    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=None),
        agent_factory=agent_factory,
        graph_input={},
        config={},
    )


@pytest.mark.anyio
async def test_successful_run_schedules_delayed_record_cleanup():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    await _run_to_completion(run_manager, record, agent_factory=lambda *, config: _OkAgent())
    assert record.status == RunStatus.success

    task = _scheduled_cleanup_task(record.run_id)
    assert task is not None, "run_agent must schedule delayed in-memory record cleanup"
    await _cancel(task)

    # The scheduled task would remove the record after its delay; verify the
    # record is in an evictable state and removal actually empties the registry.
    await run_manager.cleanup(record.run_id, delay=0)
    assert await run_manager.get(record.run_id) is None
    assert await run_manager.list_by_thread("thread-1") == []


@pytest.mark.anyio
async def test_failed_run_schedules_delayed_record_cleanup():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    await _run_to_completion(run_manager, record, agent_factory=lambda *, config: _ExplodingAgent())
    assert record.status == RunStatus.error

    task = _scheduled_cleanup_task(record.run_id)
    assert task is not None, "cleanup must also be scheduled when the run fails"
    await _cancel(task)

    await run_manager.cleanup(record.run_id, delay=0)
    assert await run_manager.get(record.run_id) is None


@pytest.mark.anyio
async def test_fail_start_if_pending_schedules_delayed_record_cleanup():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    marked = await run_manager.fail_start_if_pending(record.run_id, error="worker attach failed")
    assert marked is True

    task = _scheduled_cleanup_task(record.run_id)
    assert task is not None, "fail_start_if_pending must schedule cleanup for the terminal record"
    await _cancel(task)

    await run_manager.cleanup(record.run_id, delay=0)
    assert await run_manager.get(record.run_id) is None


@pytest.mark.anyio
async def test_idempotent_reuse_of_terminal_store_run_schedules_cleanup():
    """A hydrated store-only overlay must not outlive its reuse either."""
    store = MemoryRunStore()
    owning = RunManager(store=store)
    admitted = await owning.create_or_reject("thread-1", idempotency_key="idem-1")
    await owning.set_status(admitted.run_id, RunStatus.success)

    # A second worker sharing the store reuses the idempotency key and
    # hydrates the terminal row into its own in-memory registry.
    reusing = RunManager(store=store)
    reused = await reusing.create_or_reject("thread-1", idempotency_key="idem-1")
    assert reused.run_id == admitted.run_id
    assert reused.status == RunStatus.success

    task = _scheduled_cleanup_task(admitted.run_id)
    assert task is not None, "hydrated terminal overlays must schedule their own eviction"
    await _cancel(task)

    await reusing.cleanup(admitted.run_id, delay=0)
    assert await reusing.get(admitted.run_id, raise_on_store_error=True) is not None  # store row survives
    assert admitted.run_id not in reusing._runs


@pytest.mark.anyio
async def test_idempotent_reuse_of_active_local_run_does_not_schedule_cleanup():
    """An in-flight run's record is owned by its worker; no speculative eviction."""
    run_manager = RunManager()
    record = await run_manager.create_or_reject("thread-1", idempotency_key="idem-2")

    reused = await run_manager.create_or_reject("thread-1", idempotency_key="idem-2")
    assert reused is record
    assert reused.idempotency_reused is True

    assert _scheduled_cleanup_task(record.run_id) is None
