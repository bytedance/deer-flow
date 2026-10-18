import asyncio
import logging
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.mcp_scope import THREAD_INCARNATION_CONTEXT_KEY
from deerflow.subagents import batch_service as service_module
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.batch_service import SubagentBatchService
from deerflow.subagents.capacity import SubagentExecutionCapacity

_MISSING = object()


class FakeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {FakeStatus.COMPLETED, FakeStatus.FAILED, FakeStatus.CANCELLED}


def _request(**overrides) -> BatchSubmitRequest:
    values = {
        "user_id": "user-1",
        "thread_id": "thread-1",
        "run_id": "run-1",
        "tool_call_id": "call-1",
        "submission_key": "run-1:call-1",
        "title": "Records",
        "subagent_type": "general-purpose",
        "items": [{"key": "record-1", "prompt": "Process record 1"}],
        "max_live_items": None,
        "max_running_items": None,
        "execution_spec": {
            "subagent_config": {
                "name": "general-purpose",
                "description": "General purpose",
                "system_prompt": "Work carefully.",
            },
            "parent_model": "model-a",
            "knowledge_scope": {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["dataset-1"],
            },
        },
    }
    values.update(overrides)
    return BatchSubmitRequest(**values)


@pytest.mark.asyncio
async def test_submit_keeps_batch_running_limit_separate_from_one_process_capacity() -> None:
    repository = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "batch-1"}))
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(max_running_items_per_batch=32),
        runtime_config=SubagentRuntimeConfig(max_running=3),
    )

    result = await service.submit(_request(max_live_items=20, max_running_items=10))

    assert result == {"id": "batch-1"}
    assert repository.create_batch.await_args.kwargs["max_running_items"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"max_running_items": 0}, "max_running_items must be between 1 and 64"),
        ({"max_live_items": 1, "max_running_items": 0}, "max_running_items must be between 1 and 64"),
        ({"max_live_items": 0}, "max_live_items must be between 1 and 1000"),
    ],
)
async def test_submit_reports_an_explicit_zero_limit_by_name(overrides: dict[str, int], expected: str) -> None:
    repository = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "batch-1"}))
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )

    with pytest.raises(ValueError, match=expected):
        await service.submit(_request(**overrides))

    repository.create_batch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "live", "running"),
    [
        ({}, 100, 3),
        ({"max_live_items": 40}, 40, 3),
        ({"max_live_items": 40, "max_running_items": 5}, 40, 5),
    ],
)
async def test_submit_defaults_only_the_limits_the_caller_omitted(overrides: dict[str, int], live: int, running: int) -> None:
    repository = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "batch-1"}))
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )

    await service.submit(_request(**overrides))

    kwargs = repository.create_batch.await_args.kwargs
    assert (kwargs["max_live_items"], kwargs["max_running_items"]) == (live, running)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("thread_incarnation", "expected_present"),
    [
        ("incarnation-1", True),
        (None, True),
        (_MISSING, False),
    ],
)
async def test_execute_item_marks_real_running_then_persists_terminal_result(
    monkeypatch,
    thread_incarnation,
    expected_present,
) -> None:
    result = SimpleNamespace(
        status=FakeStatus.RUNNING,
        result=None,
        error=None,
        stop_reason=None,
        token_usage_records=None,
    )

    execution_spec = dict(_request().execution_spec)
    if thread_incarnation is not _MISSING:
        execution_spec[THREAD_INCARNATION_CONTEXT_KEY] = thread_incarnation

    class Repository:
        def __init__(self) -> None:
            self.marked_running = False
            self.finalized = None

        async def claim_items(self, **_kwargs):
            return [
                {
                    "id": "item-1",
                    "item_key": "record-1",
                    "prompt": "Process record 1",
                    "batch": {
                        "id": "batch-1",
                        "thread_id": "thread-1",
                        "user_id": "user-1",
                        "run_id": "run-1",
                        "execution_spec": execution_spec,
                    },
                }
            ]

        async def mark_item_running(self, *_args, **_kwargs):
            self.marked_running = True
            result.status = FakeStatus.COMPLETED
            result.result = "done"
            return True

        async def renew_item_lease(self, *_args, **_kwargs):
            return {"valid": True, "cancel_requested": False}

        async def finalize_item(self, *_args, **kwargs):
            self.finalized = kwargs
            return True

    execution_capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1))
    executor_kwargs = {}

    class Executor:
        def __init__(self, **kwargs) -> None:
            executor_kwargs.update(kwargs)

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            return "execution-1"

    repository = Repository()
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
        execution_capacity=execution_capacity,
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.gather(*list(service._executions.values()))

    assert repository.marked_running is True
    assert repository.finalized is not None
    assert repository.finalized["succeeded"] is True
    assert repository.finalized["result"] == "done"
    assert executor_kwargs["execution_capacity"] is execution_capacity
    assert executor_kwargs["knowledge_scope"] == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-1"],
    }
    assert (THREAD_INCARNATION_CONTEXT_KEY in executor_kwargs) is expected_present
    if expected_present:
        assert executor_kwargs[THREAD_INCARNATION_CONTEXT_KEY] is thread_incarnation


@pytest.mark.asyncio
async def test_execute_item_polls_completion_without_waiting_for_lease_renewal(monkeypatch) -> None:
    result = SimpleNamespace(
        status=FakeStatus.PENDING,
        result=None,
        error=None,
        stop_reason=None,
        token_usage_records=None,
    )
    reads = 0

    class Repository:
        def __init__(self) -> None:
            self.finalized = None

        async def claim_items(self, **_kwargs):
            return [
                {
                    "id": "item-1",
                    "item_key": "record-1",
                    "prompt": "Process record 1",
                    "batch": {
                        "id": "batch-1",
                        "thread_id": "thread-1",
                        "user_id": "user-1",
                        "run_id": "run-1",
                        "execution_spec": _request().execution_spec,
                    },
                }
            ]

        async def mark_item_running(self, *_args, **_kwargs):
            raise AssertionError("a task that completes between polls need not expose running")

        async def renew_item_lease(self, *_args, **_kwargs):
            # Renew before assembly and revalidate before dispatch; neither
            # heartbeat nor polling should delay a task completing between polls.
            self.renews = getattr(self, "renews", 0) + 1
            return {"valid": True, "cancel_requested": False}

        async def finalize_item(self, *_args, **kwargs):
            self.finalized = kwargs
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            return "execution-1"

    def read_result(_execution_id):
        nonlocal reads
        reads += 1
        if reads > 1:
            result.status = FakeStatus.COMPLETED
            result.result = "fast result"
        return result

    repository = Repository()
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", read_result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(poll_interval_seconds=0.1, lease_seconds=120),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.wait_for(
        asyncio.gather(*list(service._executions.values())),
        timeout=1,
    )

    assert repository.finalized is not None
    assert repository.finalized["result"] == "fast result"
    assert repository.renews == 2


class _Registry:
    """Executor registry double with the real cleanup and cancellation timing."""

    def __init__(self) -> None:
        self.results: dict[str, SimpleNamespace] = {}
        self.cancelled: list[str] = []
        self.forced: list[str] = []

    def get(self, execution_id):
        return self.results.get(execution_id)

    def cleanup(self, execution_id) -> None:
        # The real cleanup_background_task keeps entries that are not terminal.
        result = self.results.get(execution_id)
        if result is not None and result.status.is_terminal:
            del self.results[execution_id]

    def force(self, execution_id) -> None:
        self.forced.append(execution_id)
        self.results.pop(execution_id, None)

    def cancel(self, execution_id) -> None:
        self.cancelled.append(execution_id)
        result = self.results.get(execution_id)
        if result is not None:
            # The executor turns a cancelled run terminal on its own loop,
            # after the caller has already left its finally block.
            asyncio.get_running_loop().call_later(0.05, setattr, result, "status", FakeStatus.CANCELLED)


def _install_registry(monkeypatch, registry: _Registry) -> None:
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", registry.get)
    monkeypatch.setattr(service_module, "cleanup_background_task", registry.cleanup)
    monkeypatch.setattr(service_module, "force_cleanup_background_task", registry.force)
    monkeypatch.setattr(service_module, "request_cancel_background_task", registry.cancel)
    monkeypatch.setattr(service_module, "run_on_isolated_subagent_loop", asyncio.ensure_future)


def _running_item_service(monkeypatch, registry: _Registry, *, mark_item_running) -> tuple[SubagentBatchService, SimpleNamespace]:
    registry.results["execution-1"] = SimpleNamespace(status=FakeStatus.RUNNING, result=None, error=None, stop_reason=None, token_usage_records=None)
    finalized = SimpleNamespace(kwargs=None)

    class Repository:
        async def claim_items(self, **_kwargs):
            return [
                {
                    "id": "item-1",
                    "item_key": "record-1",
                    "prompt": "Process record 1",
                    "batch": {"id": "batch-1", "thread_id": "thread-1", "user_id": "user-1", "run_id": "run-1", "execution_spec": _request().execution_spec},
                }
            ]

        async def renew_item_lease(self, *_args, **_kwargs):
            return {"valid": True, "cancel_requested": False}

        async def mark_item_running(self, *_args, **_kwargs):
            return await mark_item_running()

        async def finalize_item(self, *_args, **kwargs):
            finalized.kwargs = kwargs
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            return "execution-1"

    _install_registry(monkeypatch, registry)
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(poll_interval_seconds=0.1, lease_seconds=120),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    return service, finalized


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=timeout)


@pytest.mark.asyncio
async def test_stopped_item_releases_its_execution_once_it_turns_terminal(monkeypatch) -> None:
    # stop() cancels the item task while its subagent is still running, so the
    # finally-block cleanup alone saw a live entry, kept it, and nothing ever
    # removed the SubagentResult (with its whole transcript) afterwards.
    registry = _Registry()
    running = asyncio.Event()

    async def mark_item_running():
        running.set()
        return True

    service, finalized = _running_item_service(monkeypatch, registry, mark_item_running=mark_item_running)
    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.wait_for(running.wait(), timeout=1)

    await asyncio.wait_for(service.stop(), timeout=1)

    assert "execution-1" in registry.cancelled
    await _wait_until(lambda: "execution-1" not in registry.results)
    assert registry.forced == []
    assert finalized.kwargs is None


@pytest.mark.asyncio
async def test_item_error_cancels_and_releases_an_unfinished_execution(monkeypatch) -> None:
    # A repository error while polling fails the durable item; the subagent
    # must not keep running unsupervised, nor stay in the registry.
    registry = _Registry()

    async def mark_item_running():
        raise RuntimeError("database is locked")

    service, finalized = _running_item_service(monkeypatch, registry, mark_item_running=mark_item_running)
    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.wait_for(asyncio.gather(*list(service._executions.values())), timeout=1)

    assert finalized.kwargs is not None and finalized.kwargs["succeeded"] is False
    assert registry.cancelled == ["execution-1"]
    await _wait_until(lambda: "execution-1" not in registry.results)
    assert registry.forced == []


@pytest.mark.asyncio
async def test_release_removes_an_execution_that_never_turns_terminal(monkeypatch) -> None:
    # Cancellation is cooperative; a run that ignores it must not keep its
    # entry, or this poll, alive forever.
    registry = _Registry()
    registry.results["execution-1"] = SimpleNamespace(status=FakeStatus.RUNNING)
    _install_registry(monkeypatch, registry)

    await asyncio.wait_for(service_module._release_when_terminal("execution-1", poll_seconds=0.01, max_wait_seconds=0.05), timeout=1)

    assert registry.forced == ["execution-1"]
    assert registry.results == {}


@pytest.mark.asyncio
async def test_release_survives_an_unavailable_subagent_loop(monkeypatch) -> None:
    # Runs in a finally block: failing to schedule must not replace the
    # in-flight CancelledError, and must not strand an unawaited coroutine.
    registry = _Registry()
    registry.results["execution-1"] = SimpleNamespace(status=FakeStatus.RUNNING)
    _install_registry(monkeypatch, registry)
    submitted = []

    def unavailable(coro):
        submitted.append(coro)
        raise RuntimeError("Isolated subagent event loop shutdown is still pending")

    monkeypatch.setattr(service_module, "run_on_isolated_subagent_loop", unavailable)
    service = SubagentBatchService(repository=SimpleNamespace(), config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig())

    service._release_execution("execution-1")

    assert registry.cancelled == ["execution-1"]
    assert len(submitted) == 1 and submitted[0].cr_frame is None


@pytest.mark.asyncio
async def test_executor_admission_failure_requeues_instead_of_finalizing(monkeypatch) -> None:
    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        result=None,
        error="Process-wide subagent capacity is full",
        stop_reason=None,
        token_usage_records=None,
        admission_failure=True,
    )

    class Repository:
        def __init__(self) -> None:
            self.requeued = None
            self.finalized = False

        async def claim_items(self, **_kwargs):
            return [
                {
                    "id": "item-1",
                    "item_key": "record-1",
                    "prompt": "Process record 1",
                    "batch": {
                        "id": "batch-1",
                        "thread_id": "thread-1",
                        "user_id": "user-1",
                        "run_id": "run-1",
                        "execution_spec": _request().execution_spec,
                    },
                }
            ]

        async def renew_item_lease(self, *_args, **_kwargs):
            return {"valid": True, "cancel_requested": False}

        async def requeue_item_after_admission_failure(self, item_id, **kwargs):
            self.requeued = (item_id, kwargs)
            return True

        async def finalize_item(self, *_args, **_kwargs):
            self.finalized = True
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            return "execution-1"

    repository = Repository()
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.gather(*list(service._executions.values()))

    assert repository.requeued is not None
    assert repository.requeued[0] == "item-1"
    assert repository.finalized is False


@pytest.mark.asyncio
async def test_cancel_during_tool_assembly_skips_launch(monkeypatch, tmp_path) -> None:
    """A batch cancelled while tool assembly is blocked must not launch.

    Regression (review of 249dba82): ``_execute_item()`` called
    ``executor.execute_async()`` unconditionally after assembly, so
    ``cancel_batch()`` landing while assembly was blocked in the worker thread
    terminalized the durable item but could not stop the not-yet-started
    execution, and the orphaned launch still invoked the model.
    """
    import threading
    from datetime import UTC, datetime

    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.subagent_batches import SubagentBatchRepository

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        repository = SubagentBatchRepository(get_session_factory())
        await repository.create_batch(
            batch_id="batch-1",
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            tool_call_id="call-1",
            submission_key="run-1:call-1",
            title="Cancelled during assembly",
            subagent_type="general-purpose",
            items=[{"key": "record-1", "prompt": "Process record 1"}],
            max_live_items=2,
            max_running_items=1,
            max_attempts=2,
            execution_spec={
                "subagent_config": {
                    "name": "general-purpose",
                    "description": "test",
                    "system_prompt": "sys",
                },
            },
        )
        service = SubagentBatchService(
            repository=repository,
            config=SubagentBatchesConfig(lease_seconds=60),
            runtime_config=SubagentRuntimeConfig(max_running=3),
            app_config=SimpleNamespace(),
        )
        claimed = await repository.claim_items(
            now=datetime.now(UTC),
            lease_owner="assembly-claim",
            lease_seconds=60,
            limit=10,
        )
        assert len(claimed) == 1
        item = claimed[0]
        assert item["batch"]["id"] == "batch-1"

        assembly_started = threading.Event()
        assembly_release = threading.Event()

        def _blocking_assembly(**_kwargs):
            # Real blocking wait in the assembly-pool worker: parks assembly
            # until the test has cancelled the batch.
            assembly_started.set()
            assembly_release.wait(timeout=15)
            return []

        monkeypatch.setattr("deerflow.tools.get_available_tools", _blocking_assembly)
        monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
        monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_a, **_k: "test-model")
        monkeypatch.setattr(service_module, "request_cancel_background_task", lambda _execution_id: None)

        launched: list[str] = []

        class _Executor:
            def __init__(self, **_kwargs) -> None:
                pass

            def execute_async(self, _prompt, task_id=None):
                launched.append(task_id or "generated")
                return task_id or "generated"

        monkeypatch.setattr(service_module, "SubagentExecutor", _Executor)
        monkeypatch.setattr(
            service_module,
            "get_background_task_result",
            lambda _execution_id: SimpleNamespace(
                status=FakeStatus.COMPLETED,
                result="done",
                error=None,
                stop_reason=None,
                token_usage_records=[],
            ),
        )

        item_task = asyncio.create_task(service._execute_item(item, lease_owner="assembly-claim"))
        assert await asyncio.to_thread(assembly_started.wait, 15)

        cancelled = await service.cancel_batch(batch_id="batch-1", user_id="user-1")
        assert cancelled is not None

        assembly_release.set()
        await asyncio.wait_for(item_task, timeout=10)

        assert launched == [], "cancelled work must not launch after assembly"
        batch = await repository.get_batch("batch-1", user_id="user-1")
        assert batch is not None
        assert batch["counts"]["cancelled"] == 1
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_start_cannot_replace_poller_while_stop_is_draining(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    poller_entered = asyncio.Event()
    allow_poller_exit = asyncio.Event()

    async def blocking_poller() -> None:
        poller_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await allow_poller_exit.wait()

    monkeypatch.setattr(service, "_run", blocking_poller)
    await service.start()
    original_poller = service._poller
    assert original_poller is not None
    await asyncio.wait_for(poller_entered.wait(), timeout=1)

    stop_task = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    assert service._poller is original_poller
    with pytest.raises(RuntimeError, match="before stop completes"):
        await service.start()
    assert service._poller is original_poller

    allow_poller_exit.set()
    await asyncio.wait_for(stop_task, timeout=1)
    assert original_poller.done()
    assert service._poller is None
    assert not service._stopping

    await service.start()
    restarted_poller = service._poller
    assert restarted_poller is not None
    assert restarted_poller is not original_poller
    await asyncio.wait_for(service.stop(), timeout=1)
    assert restarted_poller.done()
    assert service._poller is None


@pytest.mark.asyncio
async def test_restarted_batch_stop_cancels_and_drains_owned_work(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    poller_entered = asyncio.Event()
    item_entered = asyncio.Event()
    requested: list[str] = []
    owned_tasks: list[asyncio.Task[None]] = []

    async def poller() -> None:
        poller_entered.set()
        await asyncio.Future()

    async def item_work() -> None:
        item_entered.set()
        await asyncio.Future()

    monkeypatch.setattr(service, "_run", poller)
    monkeypatch.setattr(service_module, "request_cancel_background_task", requested.append)

    try:
        await service.start()
        first_poller = service._poller
        assert first_poller is not None
        owned_tasks.append(first_poller)
        await asyncio.wait_for(poller_entered.wait(), timeout=1)
        await asyncio.wait_for(service.stop(), timeout=1)
        first_cleanup = service._stop_cleanup_task
        assert first_poller.done()

        poller_entered.clear()
        await service.start()
        restarted_poller = service._poller
        assert restarted_poller is not None
        assert restarted_poller is not first_poller
        owned_tasks.append(restarted_poller)
        await asyncio.wait_for(poller_entered.wait(), timeout=1)

        item_task = asyncio.create_task(item_work())
        owned_tasks.append(item_task)
        service._executions["item-2"] = item_task
        service._execution_ids["item-2"] = "execution-2"
        service._item_batches["item-2"] = "batch-2"
        await asyncio.wait_for(item_entered.wait(), timeout=1)

        await asyncio.wait_for(service.stop(), timeout=1)
        assert requested == ["execution-2"]
        assert restarted_poller.done()
        assert item_task.done()
        assert service._poller is None
        assert service._executions == {}
        assert service._execution_ids == {}
        assert service._item_batches == {}
        assert service._stop.is_set()
        assert not service._stopping
        second_cleanup = service._stop_cleanup_task
        assert second_cleanup is not None
        assert second_cleanup is not first_cleanup
        assert second_cleanup.done()

        await asyncio.wait_for(service.stop(), timeout=1)
        assert service._stop_cleanup_task is second_cleanup
        assert requested == ["execution-2"]
    finally:
        for task in owned_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*owned_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_batch_stops_share_one_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    poller_entered = asyncio.Event()
    poller_cancelled = asyncio.Event()
    release_poller = asyncio.Event()
    drain_calls = 0

    async def reluctant_poller() -> None:
        poller_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            poller_cancelled.set()
            await release_poller.wait()

    original_drain = service._drain_stop

    async def counted_drain(poller, tasks) -> None:
        nonlocal drain_calls
        drain_calls += 1
        await original_drain(poller, tasks)

    monkeypatch.setattr(service, "_run", reluctant_poller)
    monkeypatch.setattr(service, "_drain_stop", counted_drain)
    await service.start()
    await asyncio.wait_for(poller_entered.wait(), timeout=1)

    first_stop = asyncio.create_task(service.stop())
    await asyncio.wait_for(poller_cancelled.wait(), timeout=1)
    cleanup_task = service._stop_cleanup_task
    second_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)

    assert cleanup_task is not None
    assert service._stop_cleanup_task is cleanup_task
    assert service._stop_drains == 1
    assert drain_calls == 1
    assert not first_stop.done()
    assert not second_stop.done()

    release_poller.set()
    await asyncio.wait_for(asyncio.gather(first_stop, second_stop), timeout=1)
    assert service._stop_cleanup_task is cleanup_task
    assert cleanup_task.done()
    assert service._stop_drains == 0
    assert not service._stopping
    assert drain_calls == 1


@pytest.mark.asyncio
async def test_cancelled_batch_stop_allows_successful_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    poller_entered = asyncio.Event()
    release_poller = asyncio.Event()

    async def reluctant_poller() -> None:
        poller_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release_poller.wait()

    monkeypatch.setattr(service, "_run", reluctant_poller)
    await service.start()
    original_poller = service._poller
    await asyncio.wait_for(poller_entered.wait(), timeout=1)

    first_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    cleanup_task = service._stop_cleanup_task
    first_stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_stop

    assert cleanup_task is not None
    assert service._stop_cleanup_task is cleanup_task
    assert service._stop_drains == 1
    assert service._stopping
    assert original_poller is not None
    assert not original_poller.done()
    assert not original_poller.cancelled()
    with pytest.raises(RuntimeError, match="before stop completes"):
        await service.start()

    retry_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert service._stop_cleanup_task is cleanup_task
    assert not retry_stop.done()

    release_poller.set()
    await asyncio.wait_for(retry_stop, timeout=1)
    assert original_poller.done()
    assert service._poller is None
    assert service._stop_cleanup_task is cleanup_task
    assert cleanup_task.done()
    assert service._stop_drains == 0
    assert not service._stopping

    await service.start()
    restarted_poller = service._poller
    assert restarted_poller is not None
    assert restarted_poller is not original_poller
    await asyncio.wait_for(service.stop(), timeout=1)
    assert restarted_poller.done()
    assert service._poller is None


@pytest.mark.asyncio
async def test_batch_stop_cleanup_failure_is_reported_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
    )
    poller_entered = asyncio.Event()
    release_poller = asyncio.Event()
    cleanup_error = RuntimeError("stop cleanup failed")

    async def reluctant_poller() -> None:
        poller_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release_poller.wait()

    class FailingClearDict(dict):
        def clear(self) -> None:
            raise cleanup_error

    monkeypatch.setattr(service, "_run", reluctant_poller)
    service._executions = FailingClearDict()
    await service.start()
    await asyncio.wait_for(poller_entered.wait(), timeout=1)
    first_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    first_stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_stop

    cleanup_task = service._stop_cleanup_task
    assert cleanup_task is not None
    release_poller.set()
    with pytest.raises(RuntimeError, match="stop cleanup failed"):
        await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=1)

    assert service._stopping
    with pytest.raises(RuntimeError, match="before stop completes"):
        await service.start()

    with pytest.raises(RuntimeError, match="stop cleanup failed") as raised:
        await service.stop()
    assert raised.value is cleanup_error
    assert service._stop_cleanup_task is cleanup_task


@pytest.mark.asyncio
async def test_release_logs_a_failure_on_the_subagent_loop(monkeypatch, caplog) -> None:
    # The release runs as a concurrent future, which never reports an
    # exception nobody retrieved; a failing release would leak its entry
    # without a trace.
    registry = _Registry()
    registry.results["execution-1"] = SimpleNamespace(status=FakeStatus.RUNNING)
    _install_registry(monkeypatch, registry)
    loop = asyncio.get_running_loop()
    scheduled = []

    def subagent_loop(coro):
        scheduled.append(asyncio.run_coroutine_threadsafe(coro, loop))
        return scheduled[-1]

    def registry_unavailable(_execution_id):
        raise RuntimeError("registry lock poisoned")

    monkeypatch.setattr(service_module, "run_on_isolated_subagent_loop", subagent_loop)
    service = SubagentBatchService(repository=SimpleNamespace(), config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig())

    service._release_execution("execution-1")
    monkeypatch.setattr(service_module, "get_background_task_result", registry_unavailable)
    with caplog.at_level(logging.ERROR, logger=service_module.__name__):
        await _wait_until(lambda: scheduled[0].done() and not service_module._pending_releases)

    failures = [record for record in caplog.records if "execution-1" in record.getMessage()]
    assert len(failures) == 1 and failures[0].levelno == logging.ERROR
    assert str(failures[0].exc_info[1]) == "registry lock poisoned"
