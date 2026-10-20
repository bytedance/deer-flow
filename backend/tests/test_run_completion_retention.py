"""Gateway completion wiring for the checkpoint-retention contract.

These tests exercise the production adapter rather than calling the retention
service alone. The important boundary is the worker's existing completion hook:
successful duration writes are retained while the finalizing fence is held,
the scheduler still receives every terminal record, and cleanup failures never
rewrite the run outcome or strand a scheduled occurrence.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway import checkpoint_retention, deps, run_completion
from app.gateway.checkpoint_retention import RetentionReport
from deerflow.runtime import ThreadOperationKind
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import _persist_run_duration


def _record(*, status: RunStatus = RunStatus.success, aborted: bool = False) -> SimpleNamespace:
    abort_event = asyncio.Event()
    if aborted:
        abort_event.set()
    return SimpleNamespace(
        run_id="completion-run",
        thread_id="completion-thread",
        user_id="completion-user",
        status=status,
        abort_event=abort_event,
    )


class _LockProbe:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> None:
        self.events.append("lock-enter")

    async def __aexit__(self, *_exc: object) -> None:
        self.events.append("lock-exit")


class _ReservationProbe:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def reserve_thread_operation(self, *_args: object, **_kwargs: object) -> object:
        events = self.events

        class Reservation:
            async def __aenter__(self) -> None:
                events.append("durable-enter")

            async def __aexit__(self, *_exc: object) -> None:
                events.append("durable-exit")

        return Reservation()


def _report(*deleted: str) -> RetentionReport:
    return RetentionReport(
        thread_id="completion-thread",
        deleted_checkpoint_ids=list(deleted),
    )


@pytest.mark.anyio
async def test_successful_completion_retains_before_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    scheduler = SimpleNamespace(
        handle_run_completion=AsyncMock(side_effect=lambda _record: events.append("scheduler")),
    )
    lock = _LockProbe(events)

    async def retain(*args: object, **kwargs: object) -> RetentionReport:
        assert args[0] is not None
        assert args[1] == "completion-thread"
        assert kwargs["thread_lock"] is lock
        async with kwargs["thread_lock"]:
            events.append("retention")
        return _report("duration-checkpoint")

    monkeypatch.setattr(run_completion, "_checkpoint_thread_lock", lambda _thread_id: lock)
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)

    await run_completion.run_gateway_completion_hooks(
        _record(),
        checkpointer=object(),
        scheduled_service=scheduler,
    )

    assert events == ["lock-enter", "retention", "lock-exit", "scheduler"]
    scheduler.handle_run_completion.assert_awaited_once()


@pytest.mark.anyio
async def test_successful_completion_uses_durable_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    reservation = _ReservationProbe(events)
    lock = _LockProbe(events)

    async def retain(*_args: object, **kwargs: object) -> RetentionReport:
        assert kwargs["thread_lock"] is lock
        async with kwargs["thread_lock"]:
            events.append("retention")
        return _report()

    monkeypatch.setattr(run_completion, "_checkpoint_thread_lock", lambda _thread_id: lock)
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)

    await run_completion.run_gateway_completion_hooks(
        _record(),
        checkpointer=object(),
        run_manager=reservation,
        scheduled_service=None,
    )

    assert events == ["durable-enter", "lock-enter", "retention", "lock-exit", "durable-exit"]


@pytest.mark.anyio
async def test_durable_reservation_conflict_skips_cleanup(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    retain = AsyncMock()
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)
    store = MemoryRunStore()
    peer = RunManager(store=store, worker_id="retention-peer")
    manager = RunManager(store=store, worker_id="retention-completion")
    record = _record()

    # A real peer reservation must raise the public ConflictError through the
    # completion manager's admission path, rather than a generic backend error.
    async with peer.reserve_thread_operation(record.thread_id, kind=ThreadOperationKind.checkpoint_write, user_id=record.user_id):
        with caplog.at_level(logging.DEBUG, logger=run_completion.__name__):
            await run_completion.run_gateway_completion_hooks(
                record,
                checkpointer=object(),
                run_manager=manager,
                scheduled_service=scheduler,
            )

    retain.assert_not_awaited()
    scheduler.handle_run_completion.assert_awaited_once_with(record)
    assert record.status == RunStatus.success
    records = [entry for entry in caplog.records if entry.name == run_completion.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert "Checkpoint retention skipped" in records[0].getMessage()
    assert record.run_id in records[0].getMessage()
    assert record.thread_id in records[0].getMessage()
    assert records[0].exc_info is None


@pytest.mark.anyio
async def test_completion_releases_real_run_manager_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = RunManager(store=MemoryRunStore(), worker_id="retention-hook")
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", AsyncMock(return_value=_report()))

    record = _record()
    await run_completion.run_gateway_completion_hooks(
        record,
        checkpointer=object(),
        run_manager=manager,
        scheduled_service=None,
    )

    assert await manager.has_inflight(record.thread_id) is False


@pytest.mark.anyio
async def test_retention_receives_bounded_completion_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def retain(*args: object, **kwargs: object) -> RetentionReport:
        captured["arg_count"] = len(args)
        captured["lock"] = kwargs["thread_lock"]
        return _report()

    lock = _LockProbe([])
    monkeypatch.setattr(run_completion, "_checkpoint_thread_lock", lambda _thread_id: lock)
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)

    await run_completion.run_gateway_completion_hooks(_record(), checkpointer=object(), scheduled_service=None)

    assert captured["arg_count"] == 2
    assert captured["lock"] is lock


@pytest.mark.anyio
@pytest.mark.parametrize("failure_at", ["reservation", "retention"])
async def test_retention_failure_is_fail_open_for_scheduler(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure_at: str) -> None:
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    failure = RuntimeError("database temporarily unavailable")
    retain = AsyncMock(side_effect=failure)
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)
    manager = None
    if failure_at == "reservation":
        reservation = AsyncMock()
        reservation.__aenter__.side_effect = failure
        manager = SimpleNamespace(reserve_thread_operation=lambda *_args, **_kwargs: reservation)
    record = _record()

    with caplog.at_level(logging.WARNING, logger=run_completion.__name__):
        await run_completion.run_gateway_completion_hooks(record, checkpointer=object(), run_manager=manager, scheduled_service=scheduler)

    scheduler.handle_run_completion.assert_awaited_once_with(record)
    assert record.status == RunStatus.success
    records = [entry for entry in caplog.records if entry.name == run_completion.__name__]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "Checkpoint retention failed after run completion-run" in records[0].getMessage()
    assert records[0].exc_info[1] is failure
    if failure_at == "reservation":
        retain.assert_not_awaited()
    else:
        retain.assert_awaited_once()


@pytest.mark.anyio
async def test_retention_is_skipped_without_a_checkpointer() -> None:
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())

    await run_completion.run_gateway_completion_hooks(_record(), checkpointer=None, scheduled_service=scheduler)

    scheduler.handle_run_completion.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [RunStatus.error, RunStatus.interrupted, RunStatus.timeout])
async def test_non_successful_terminal_records_are_not_retained(status: RunStatus, monkeypatch: pytest.MonkeyPatch) -> None:
    retain = AsyncMock()
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)

    await run_completion.run_gateway_completion_hooks(_record(status=status), checkpointer=object(), scheduled_service=scheduler)

    retain.assert_not_awaited()
    scheduler.handle_run_completion.assert_awaited_once()


@pytest.mark.anyio
async def test_aborted_success_record_is_not_retained() -> None:
    retain = AsyncMock()
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    original = run_completion.enforce_trailing_duration_retention
    run_completion.enforce_trailing_duration_retention = retain
    try:
        await run_completion.run_gateway_completion_hooks(
            _record(status=RunStatus.success, aborted=True),
            checkpointer=object(),
            scheduled_service=scheduler,
        )
    finally:
        run_completion.enforce_trailing_duration_retention = original

    retain.assert_not_awaited()
    scheduler.handle_run_completion.assert_awaited_once()


@pytest.mark.anyio
async def test_scheduler_exception_is_returned_to_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock(side_effect=ValueError("scheduler failure")))
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", AsyncMock(return_value=_report()))

    with pytest.raises(ValueError, match="scheduler failure"):
        await run_completion.run_gateway_completion_hooks(_record(), checkpointer=object(), scheduled_service=scheduler)


def test_get_run_context_installs_gateway_completion_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    run_manager = object()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                extensions=None,
                run_events_config=None,
                checkpoint_channel_mode="full",
                checkpoint_snapshot_frequency=None,
                scheduled_task_service=None,
                agent_runs_host=None,
                run_manager=run_manager,
            ),
        ),
    )
    checkpointer = object()
    adapter = AsyncMock()
    monkeypatch.setattr(deps, "get_checkpointer", lambda _request: checkpointer)
    monkeypatch.setattr(deps, "get_store", lambda _request: None)
    monkeypatch.setattr(deps, "get_run_event_store", lambda _request: None)
    monkeypatch.setattr(deps, "get_thread_store", lambda _request: None)
    monkeypatch.setattr(deps, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(deps, "run_gateway_completion_hooks", adapter)

    context = deps.get_run_context(request)
    assert context.on_run_completed is not None

    record = _record()
    asyncio.run(context.on_run_completed(record))
    adapter.assert_awaited_once_with(record, checkpointer=checkpointer, run_manager=run_manager, scheduled_service=None)


async def _write_initial_checkpoint(checkpointer: InMemorySaver, thread_id: str) -> str:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "messages": [
            HumanMessage(content="Question", id="human-1"),
            AIMessage(content="Answer", id="ai-1"),
        ],
    }
    checkpoint["channel_versions"] = {"messages": 1}
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "writes": {"messages": ["Answer"]}, "parents": {}},
        {"messages": 1},
    )
    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    return latest.config["configurable"]["checkpoint_id"]


@pytest.mark.anyio
async def test_successful_completion_prunes_the_duration_leaf() -> None:
    checkpointer = InMemorySaver()
    thread_id = "completion-retention-thread"
    parent_id = await _write_initial_checkpoint(checkpointer, thread_id)
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="completion-run",
        duration_seconds=3,
    )

    before = [item.config["configurable"]["checkpoint_id"] async for item in checkpointer.alist({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})]
    assert len(before) == 2
    assert parent_id in before

    record = _record()
    record.thread_id = thread_id
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer, scheduled_service=None)

    after = [item.config["configurable"]["checkpoint_id"] async for item in checkpointer.alist({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})]
    assert after == [parent_id]


@pytest.mark.anyio
async def test_completion_retention_preserves_the_resumable_parent() -> None:
    checkpointer = InMemorySaver()
    thread_id = "completion-retention-parent"
    parent_id = await _write_initial_checkpoint(checkpointer, thread_id)
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="completion-run",
        duration_seconds=9,
    )

    record = _record()
    record.thread_id = thread_id
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer, scheduled_service=None)

    resumed = await checkpointer.aget_tuple(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": parent_id}},
    )
    assert resumed is not None
    assert resumed.config["configurable"]["checkpoint_id"] == parent_id


@pytest.mark.anyio
async def test_completion_retention_is_idempotent_after_leaf_was_removed() -> None:
    checkpointer = InMemorySaver()
    thread_id = "completion-retention-idempotent"
    await _write_initial_checkpoint(checkpointer, thread_id)
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="completion-run",
        duration_seconds=1,
    )

    record = _record()
    record.thread_id = thread_id
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer, scheduled_service=None)
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer, scheduled_service=None)

    stats = await checkpoint_retention._thread_storage_stats(checkpointer, thread_id)
    assert stats["checkpoint_rows"] == 1


@pytest.mark.anyio
async def test_delta_cached_saver_is_unwrapped_and_cache_is_purged() -> None:
    inner = InMemorySaver()
    cache = MemoryCheckpointHistoryCache(max_entries=32)
    checkpointer = CachedHistorySaver(inner, cache, key_prefix="completion-test")
    thread_id = "completion-retention-delta"
    parent_id = await _write_initial_checkpoint(inner, thread_id)
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="completion-run",
        duration_seconds=2,
    )
    await checkpointer.aget_delta_channel_history(
        config={"configurable": {"thread_id": thread_id}},
        channels=["messages"],
    )
    assert cache.stats().entries > 0

    record = _record()
    record.thread_id = thread_id
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer)

    remaining = [item.config["configurable"]["checkpoint_id"] async for item in inner.alist({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})]
    assert remaining == [parent_id]
    assert cache.stats().entries == 0


@pytest.mark.anyio
async def test_completion_tail_cleanup_does_not_walk_history() -> None:
    class NoHistoryWalkSaver(InMemorySaver):
        def __init__(self) -> None:
            super().__init__()
            self.alist_calls = 0

        def alist(self, *args: object, **kwargs: object):
            self.alist_calls += 1
            raise AssertionError("completion cleanup must use bounded head reads")

    checkpointer = NoHistoryWalkSaver()
    thread_id = "completion-retention-bounded"
    parent_id = await _write_initial_checkpoint(checkpointer, thread_id)
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="completion-run",
        duration_seconds=2,
    )

    record = _record()
    record.thread_id = thread_id
    await run_completion.run_gateway_completion_hooks(record, checkpointer=checkpointer)

    assert checkpointer.alist_calls == 0
    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    assert latest.config["configurable"]["checkpoint_id"] == parent_id


@pytest.mark.anyio
async def test_scheduler_runs_when_retention_has_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    report = _report()
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", AsyncMock(return_value=report))

    await run_completion.run_gateway_completion_hooks(_record(), checkpointer=object(), scheduled_service=scheduler)

    scheduler.handle_run_completion.assert_awaited_once()


@pytest.mark.anyio
async def test_scheduler_waits_for_retention_to_finish() -> None:
    events: list[str] = []
    retention_started = asyncio.Event()
    release_retention = asyncio.Event()

    async def retain(*_args: object, **_kwargs: object) -> RetentionReport:
        retention_started.set()
        await release_retention.wait()
        events.append("retention-finished")
        return _report()

    async def notify(_record: object) -> None:
        events.append("scheduler")

    scheduler = SimpleNamespace(handle_run_completion=notify)
    original = run_completion.enforce_trailing_duration_retention
    run_completion.enforce_trailing_duration_retention = retain
    try:
        task = asyncio.create_task(
            run_completion.run_gateway_completion_hooks(
                _record(),
                checkpointer=object(),
                scheduled_service=scheduler,
            )
        )
        await retention_started.wait()
        await asyncio.sleep(0)
        assert events == []
        release_retention.set()
        await task
    finally:
        run_completion.enforce_trailing_duration_retention = original

    assert events == ["retention-finished", "scheduler"]


@pytest.mark.anyio
async def test_completion_adapter_waits_for_shared_checkpoint_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    lock = asyncio.Lock()
    await lock.acquire()

    async def retain(*_args: object, **kwargs: object) -> RetentionReport:
        events.append("retention-start")
        async with kwargs["thread_lock"]:
            events.append("retention-lock")
        return _report()

    monkeypatch.setattr(run_completion, "_checkpoint_thread_lock", lambda _thread_id: lock)
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)
    task = asyncio.create_task(
        run_completion.run_gateway_completion_hooks(
            _record(),
            checkpointer=object(),
            scheduled_service=None,
        )
    )
    await asyncio.sleep(0)
    assert events == ["retention-start"]
    assert not task.done()

    lock.release()
    await task
    assert events == ["retention-start", "retention-lock"]


@pytest.mark.anyio
async def test_failed_retention_does_not_change_record_status(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record()
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())

    async def retain(*_args: object, **_kwargs: object) -> RetentionReport:
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retain)
    await run_completion.run_gateway_completion_hooks(record, checkpointer=object(), scheduled_service=scheduler)

    assert record.status is RunStatus.success
    scheduler.handle_run_completion.assert_awaited_once_with(record)


@pytest.mark.anyio
async def test_scheduler_is_optional_for_internal_gateway_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    retention = AsyncMock(return_value=_report())
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retention)

    await run_completion.run_gateway_completion_hooks(_record(), checkpointer=object(), scheduled_service=None)

    retention.assert_awaited_once()


@pytest.mark.anyio
async def test_non_successful_run_still_reaches_scheduler_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    retention = AsyncMock()
    scheduler = SimpleNamespace(handle_run_completion=AsyncMock())
    monkeypatch.setattr(run_completion, "enforce_trailing_duration_retention", retention)

    await run_completion.run_gateway_completion_hooks(
        _record(status=RunStatus.error),
        checkpointer=object(),
        scheduled_service=scheduler,
    )

    retention.assert_not_awaited()
    scheduler.handle_run_completion.assert_awaited_once()
