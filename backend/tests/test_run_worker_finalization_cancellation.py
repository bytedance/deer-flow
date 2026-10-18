"""Host cancellation must preserve the terminal lifecycle and owned cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import deerflow.runtime.runs.worker as worker_module
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.runtime.stream_bridge import MemoryStreamBridge


class DummyAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield {"type": "task_started", "task_id": "verification-subtask", "description": "offline verification"}


async def start_run(monkeypatch, *, event_store, thread_store=None, run_store=None, bridge=None):
    run_store = run_store or MemoryRunStore()
    manager = RunManager(store=run_store)
    record = await manager.create_or_reject("verify-6914")
    bridge = bridge or MemoryStreamBridge()
    completed = AsyncMock()
    cleanup_tasks = []
    original_create = worker_module._create_contextless_task

    def track_cleanup(coro):
        task = original_create(coro)
        cleanup_tasks.append(task)
        return task

    monkeypatch.setattr(worker_module, "_create_contextless_task", track_cleanup)
    worker = asyncio.create_task(
        run_agent(
            bridge,
            manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=event_store, thread_store=thread_store, on_run_completed=completed),
            agent_factory=lambda *, config: DummyAgent(),
            graph_input={},
            config={},
            stream_modes=["custom"],
        )
    )
    record.task = worker
    return SimpleNamespace(worker=worker, manager=manager, record=record, bridge=bridge, completed=completed, run_store=run_store, event_store=event_store, cleanup_tasks=cleanup_tasks)


async def snapshot(run):
    record = run.record
    stored = await run.run_store.get(record.run_id)
    events = await run.event_store.list_events(record.thread_id, record.run_id)
    try:
        await run.manager.create_or_reject(record.thread_id)
        replacement_admitted = True
    except ConflictError:
        replacement_admitted = False
    return {
        "cancelled": run.worker.cancelled(),
        "local_status": record.status.value,
        "stored_status": stored["status"],
        "terminal_commit_pending": record.terminal_commit_pending,
        "finalizing": record.finalizing,
        "receipt_count": sum(e["event_type"] == "run.delivery" for e in events),
        "subagent_count": sum(e["event_type"] == "subagent.start" for e in events),
        "end": run.bridge._streams[record.run_id].ended,
        "completion_hooks": run.completed.await_count,
        "replacement_admitted": replacement_admitted,
    }


async def reap(run):
    if not run.worker.done():
        run.worker.cancel()
    await asyncio.gather(run.worker, return_exceptions=True)
    for task in run.cleanup_tasks:
        task.cancel()
    await asyncio.gather(*run.cleanup_tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["receipt", "subagent_flush", "thread_status", "terminal_status", "journal_close", "end"])
async def test_cancellation_preserves_terminal_lifecycle(monkeypatch, stage):
    entered, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gate():
        entered.set()
        await release.wait()

    class GatedEventStore(MemoryRunEventStore):
        async def put_if_absent(self, **kwargs):
            if stage == "receipt" and kwargs.get("event_type") == "run.delivery":
                await gate()
            return await super().put_if_absent(**kwargs)

        async def put_batch(self, items):
            if stage == "subagent_flush" and any(i.get("event_type") == "subagent.start" for i in items):
                await gate()
            return await super().put_batch(items)

    async def update_status(thread_id, status):
        if stage == "thread_status" and status != "running":
            await gate()

    class GatedRunStore(MemoryRunStore):
        async def update_status(self, run_id, status, **kwargs):
            if stage == "terminal_status" and status not in ("pending", "running"):
                await gate()
            return await super().update_status(run_id, status, **kwargs)

    class GatedBridge(MemoryStreamBridge):
        async def publish_end(self, run_id):
            if stage == "end":
                await gate()
            await super().publish_end(run_id)

    original_close = RunJournal.close

    async def gated_close(journal, **kwargs):
        if stage == "journal_close":
            await gate()
        await original_close(journal, **kwargs)
        closed.set()

    monkeypatch.setattr(RunJournal, "close", gated_close)

    run = await start_run(monkeypatch, event_store=GatedEventStore(), thread_store=SimpleNamespace(update_status=update_status), run_store=GatedRunStore(), bridge=GatedBridge())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        run.worker.cancel("verification cancellation")
        await asyncio.sleep(0)
        for _ in range(3):
            run.worker.cancel("repeated finalization cancellation")
            await asyncio.sleep(0)
        assert not run.worker.done()
        assert not run.cleanup_tasks
        release.set()
        done, _ = await asyncio.wait({run.worker}, timeout=5)
        assert done, "worker failed to settle after the operation was released"
        with pytest.raises(asyncio.CancelledError, match="verification cancellation"):
            await run.worker
        assert closed.is_set(), "worker exited before journal cleanup finished"
        state = await snapshot(run)
        assert state["cancelled"], state
        assert state["end"], state
        assert state["receipt_count"] == 1, state
        assert state["subagent_count"] == 1, state
        assert state["stored_status"] == state["local_status"], state
        assert not state["terminal_commit_pending"], state
        assert not state["finalizing"], state
        assert state["completion_hooks"] == 1, state
        assert state["replacement_admitted"], state
    finally:
        release.set()
        await reap(run)


@pytest.mark.asyncio
async def test_cancel_is_preserved_when_guarded_flush_fails(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original_flush = RunJournal.flush
    first_flush = True

    async def failing_flush(journal):
        nonlocal first_flush
        if first_flush:
            first_flush = False
            entered.set()
            await release.wait()
            raise OSError("injected finalization flush failure")
        return await original_flush(journal)

    monkeypatch.setattr(RunJournal, "flush", failing_flush)
    run = await start_run(monkeypatch, event_store=MemoryRunEventStore())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        run.worker.cancel("original host cancellation")
        await asyncio.sleep(0)
        release.set()
        done, _ = await asyncio.wait({run.worker}, timeout=5)
        assert done
        state = await snapshot(run)
        assert state["cancelled"], state
        assert state["end"], state
    finally:
        release.set()
        await reap(run)


@pytest.mark.asyncio
async def test_failed_finalizer_preserves_host_cancellation_as_primary():
    entered, release = asyncio.Event(), asyncio.Event()
    failure = OSError("finalizer failed during cancellation drain")

    async def finalize():
        entered.set()
        await release.wait()
        raise failure

    finalizer = asyncio.create_task(finalize())
    host = asyncio.create_task(worker_module._drain_run_finalization(finalizer))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        host.cancel("first host cancellation")
        await asyncio.sleep(0)
        host.cancel("second host cancellation")
        await asyncio.sleep(0)
        assert not finalizer.done()
        release.set()
        with pytest.raises(asyncio.CancelledError, match="first host cancellation") as caught:
            await host
        assert caught.value.__cause__ is failure
        assert finalizer.done()
        assert finalizer.exception() is failure
    finally:
        release.set()
        await asyncio.gather(host, finalizer, return_exceptions=True)


@pytest.mark.asyncio
async def test_finalizer_cancellation_is_not_mistaken_for_host_cancellation():
    async def finalize():
        raise asyncio.CancelledError("finalizer interrupted")

    finalizer = asyncio.create_task(finalize())
    with pytest.raises(asyncio.CancelledError):
        await worker_module._drain_run_finalization(finalizer)
    assert asyncio.current_task().cancelling() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["thread_status", "journal_close", "end"])
async def test_shutdown_drains_terminal_worker_after_durable_commit(monkeypatch, stage):
    entered, release, shutdown_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gate():
        entered.set()
        await release.wait()

    async def update_status(thread_id, status):
        if stage == "thread_status" and status != "running":
            await gate()

    original_close = RunJournal.close

    async def close(journal, **kwargs):
        if stage == "journal_close":
            await gate()
        await original_close(journal, **kwargs)

    class GatedBridge(MemoryStreamBridge):
        async def publish_end(self, run_id):
            if stage == "end":
                await gate()
            await super().publish_end(run_id)

    monkeypatch.setattr(RunJournal, "close", close)
    run = await start_run(monkeypatch, event_store=MemoryRunEventStore(), thread_store=SimpleNamespace(update_status=update_status), bridge=GatedBridge())
    shutdown = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await run.run_store.get(run.record.run_id))["status"] == "success"
        assert not run.record.terminal_commit_pending
        original_stop = run.manager.stop_heartbeat

        async def stop_heartbeat(**kwargs):
            await original_stop(**kwargs)
            shutdown_entered.set()

        monkeypatch.setattr(run.manager, "stop_heartbeat", stop_heartbeat)
        # A short drain budget is allowed to expire, but must not cancel or
        # retire the still-owned finalizer. A subsequent drain can finish it.
        await run.manager.shutdown(timeout=0.01)
        assert not run.worker.done()
        shutdown_entered.clear()
        shutdown = asyncio.create_task(run.manager.shutdown(timeout=5))
        await asyncio.wait_for(shutdown_entered.wait(), 5)
        await asyncio.sleep(0)
        assert not shutdown.done(), "shutdown skipped a committed run still finalizing"
        assert not run.cleanup_tasks
        release.set()
        await asyncio.wait_for(shutdown, 5)
        assert run.worker.done()
        assert not run.worker.cancelled()
        state = await snapshot(run)
        assert state["end"] and state["completion_hooks"] == 1, state
        assert state["stored_status"] == "success", state
    finally:
        release.set()
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        await reap(run)


@pytest.mark.asyncio
async def test_earlier_cancellation_does_not_leave_completion_hook_blocked(monkeypatch):
    receipt_entered, release_receipt, hook_stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class GatedEventStore(MemoryRunEventStore):
        async def put_if_absent(self, **kwargs):
            if kwargs.get("event_type") == "run.delivery":
                receipt_entered.set()
                await release_receipt.wait()
            return await super().put_if_absent(**kwargs)

    async def completion_hook(record):
        try:
            await asyncio.Event().wait()
        finally:
            hook_stopped.set()

    run = await start_run(monkeypatch, event_store=GatedEventStore())
    run.completed.side_effect = completion_hook
    try:
        await asyncio.wait_for(receipt_entered.wait(), 5)
        run.worker.cancel("cancellation before the completion hook")
        await asyncio.sleep(0)
        release_receipt.set()
        done, _ = await asyncio.wait({run.worker}, timeout=5)
        assert done, "an earlier deferred interruption left the completion hook blocked"
        with pytest.raises(asyncio.CancelledError, match="cancellation before the completion hook"):
            await run.worker
        assert hook_stopped.is_set()
        assert run.bridge._streams[run.record.run_id].ended
    finally:
        release_receipt.set()
        await reap(run)
