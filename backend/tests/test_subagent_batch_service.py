import asyncio
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents import batch_service as service_module
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.batch_service import SubagentBatchService
from deerflow.subagents.capacity import SubagentExecutionCapacity


class FakeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {FakeStatus.COMPLETED, FakeStatus.FAILED}


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
        },
    }
    values.update(overrides)
    return BatchSubmitRequest(**values)


@pytest.mark.asyncio
async def test_stop_waits_for_cancelled_background_executions_to_become_terminal(monkeypatch) -> None:
    requested: list[str] = []
    cleaned: list[str] = []
    result = SimpleNamespace(
        status=FakeStatus.RUNNING,
        completed_at=None,
        execution_done_event=asyncio.Event(),
    )
    repository = SimpleNamespace()
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    async def pending_item() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(pending_item())
    service._executions["item-1"] = task
    service._execution_ids["item-1"] = "execution-1"
    service._item_batches["item-1"] = "batch-1"
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        requested.append,
    )
    monkeypatch.setattr(
        service_module,
        "cleanup_background_task",
        cleaned.append,
    )
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )

    stop_task = asyncio.create_task(service.stop())
    while not requested:
        await asyncio.sleep(0)

    assert requested == ["execution-1"]
    assert not stop_task.done()
    assert cleaned == []
    result.status = FakeStatus.COMPLETED
    result.completed_at = service_module.datetime.now(service_module.UTC)
    await asyncio.sleep(0)
    assert not stop_task.done()
    result.execution_done_event.set()
    await asyncio.wait_for(stop_task, timeout=1)

    assert cleaned == ["execution-1"]
    assert task.cancelled()
    assert service._executions == {}
    assert service._execution_ids == {}
    assert service._item_batches == {}


@pytest.mark.asyncio
async def test_stop_defers_poller_fatal_until_executions_are_cleaned(monkeypatch) -> None:
    class PollerFatal(BaseException):
        pass

    execution_done = asyncio.Event()
    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        completed_at=service_module.datetime.now(service_module.UTC),
        execution_done_event=execution_done,
    )
    cleaned: list[str] = []
    cancellation_requested = asyncio.Event()
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    async def fail_poller() -> None:
        raise PollerFatal("poller aborted")

    async def pending_item() -> None:
        await asyncio.Event().wait()

    poller = asyncio.create_task(fail_poller())
    item_task = asyncio.create_task(pending_item())
    await asyncio.sleep(0)
    service._poller = poller
    service._executions["item-1"] = item_task
    service._execution_ids["item-1"] = "execution-1"
    service._item_batches["item-1"] = "batch-1"

    def request_cancel(execution_id: str) -> None:
        assert execution_id == "execution-1"
        cancellation_requested.set()

    monkeypatch.setattr(service_module, "request_cancel_background_task", request_cancel)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)

    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(cancellation_requested.wait(), timeout=1)
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert cleaned == []

    execution_done.set()
    with pytest.raises(PollerFatal, match="poller aborted"):
        await asyncio.wait_for(stop_task, timeout=1)

    assert cleaned == ["execution-1"]
    assert item_task.cancelled()
    assert service._executions == {}
    assert service._execution_ids == {}
    assert service._item_batches == {}


@pytest.mark.asyncio
async def test_stop_waits_for_real_item_background_teardown(monkeypatch) -> None:
    result = SimpleNamespace(
        status=FakeStatus.RUNNING,
        result=None,
        error=None,
        stop_reason=None,
        token_usage_records=None,
        completed_at=None,
        execution_done_event=asyncio.Event(),
    )
    execution_started = asyncio.Event()
    cancel_requested = asyncio.Event()
    cleaned: list[str] = []

    class Repository:
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
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            execution_started.set()
            return "execution-1"

    def request_cancel(execution_id: str) -> None:
        assert execution_id == "execution-1"
        result.status = FakeStatus.FAILED
        result.completed_at = service_module.datetime.now(service_module.UTC)
        cancel_requested.set()

    repository = Repository()
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "request_cancel_background_task", request_cancel)
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(poll_interval_seconds=0.1),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.start()
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(cancel_requested.wait(), timeout=1)
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert not result.execution_done_event.is_set()

    result.execution_done_event.set()
    await asyncio.wait_for(stop_task, timeout=1)

    assert cleaned.count("execution-1") >= 1
    assert service._executions == {}
    assert service._execution_ids == {}
    assert service._item_batches == {}


@pytest.mark.asyncio
async def test_stop_does_not_start_items_from_a_late_cancelled_claim(monkeypatch) -> None:
    claim_started = asyncio.Event()
    execution_started = False
    requeued: list[tuple[str, dict]] = []

    class Repository:
        async def claim_items(self, **_kwargs):
            claim_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
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

        async def requeue_item_after_admission_failure(self, item_id, **kwargs):
            requeued.append((item_id, kwargs))
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            nonlocal execution_started
            execution_started = True
            return f"execution-{task_id}"

    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.start()
    await asyncio.wait_for(claim_started.wait(), timeout=1)
    await asyncio.wait_for(service.stop(), timeout=1)

    assert execution_started is False
    assert len(requeued) == 1
    assert requeued[0][0] == "item-1"
    assert requeued[0][1]["lease_owner"].startswith(f"{service._lease_owner}:")
    assert requeued[0][1]["error"] == "Worker stopped before execution admission"
    assert service._executions == {}
    assert service._execution_ids == {}


@pytest.mark.asyncio
async def test_reclaimed_local_item_is_fenced_until_stale_execution_drains(
    monkeypatch,
) -> None:
    requeued: list[tuple[str, dict]] = []
    cancellation_seen = asyncio.Event()
    release_teardown = asyncio.Event()
    cancellation_requests: list[str] = []

    class Repository:
        async def claim_items(self, **kwargs):
            return [{"id": "item-1", "_lease_owner": kwargs["lease_owner"]}]

        async def requeue_item_after_admission_failure(self, item_id, **kwargs):
            requeued.append((item_id, kwargs))
            return True

    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=2),
    )

    async def stale_execution() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release_teardown.wait()

    existing_execution = asyncio.create_task(stale_execution())
    await asyncio.sleep(0)
    service._executions["item-1"] = existing_execution
    service._execution_ids["item-1"] = "execution-1"
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        cancellation_requests.append,
    )

    run_once = asyncio.create_task(
        service.run_once(now=service_module.datetime.now(service_module.UTC)),
    )
    try:
        await asyncio.wait_for(run_once, timeout=1)
        await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
        await asyncio.sleep(0)
        assert requeued == []
        assert len(service._claim_recoveries) == 1
        recovery = next(iter(service._claim_recoveries))
        assert not recovery.done()
        release_teardown.set()
        await asyncio.wait_for(recovery, timeout=1)
    finally:
        release_teardown.set()
        if not existing_execution.done():
            existing_execution.cancel()
        await asyncio.gather(existing_execution, return_exceptions=True)

    assert cancellation_requests == ["execution-1"]
    assert len(requeued) == 1
    assert requeued[0][0] == "item-1"
    assert requeued[0][1]["lease_owner"].startswith(f"{service._lease_owner}:")
    assert requeued[0][1]["lease_owner"] != service._lease_owner
    assert requeued[0][1]["error"] == "Worker drained a stale local execution before readmission"


@pytest.mark.asyncio
async def test_stop_retry_keeps_waiting_for_captured_background_execution(monkeypatch) -> None:
    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        completed_at=service_module.datetime.now(service_module.UTC),
        execution_done_event=asyncio.Event(),
    )
    cleaned: list[str] = []
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    service._execution_ids["item-1"] = "execution-1"
    monkeypatch.setattr(service_module, "request_cancel_background_task", lambda _execution_id: None)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)

    first_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not first_stop.done()
    first_stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_stop

    assert service._shutdown_execution_ids == {"execution-1"}

    second_stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not second_stop.done()
    result.execution_done_event.set()
    await asyncio.wait_for(second_stop, timeout=1)

    assert cleaned == ["execution-1"]
    assert service._shutdown_execution_ids == set()


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
async def test_execute_item_marks_real_running_then_persists_terminal_result(monkeypatch) -> None:
    result = SimpleNamespace(
        status=FakeStatus.RUNNING,
        result=None,
        error=None,
        stop_reason=None,
        token_usage_records=None,
    )

    class Repository:
        def __init__(self) -> None:
            self.claim_owner = None
            self.running_owner = None
            self.marked_running = False
            self.finalized = None

        async def claim_items(self, **kwargs):
            self.claim_owner = kwargs["lease_owner"]
            return [
                {
                    "id": "item-1",
                    "_lease_owner": self.claim_owner,
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

        async def mark_item_running(self, *_args, **kwargs):
            self.running_owner = kwargs["lease_owner"]
            self.marked_running = True
            result.status = FakeStatus.COMPLETED
            result.result = "done"
            return True

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
    monkeypatch.setattr(service_module.socket, "gethostname", lambda: "h" * 255)
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
        execution_capacity=execution_capacity,
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.gather(*list(service._executions.values()))

    assert repository.marked_running is True
    assert repository.claim_owner is not None
    assert repository.claim_owner.startswith(f"{service._lease_owner}:")
    assert repository.claim_owner != service._lease_owner
    assert len(repository.claim_owner) == 128
    assert repository.running_owner == repository.claim_owner
    assert repository.finalized is not None
    assert repository.finalized["lease_owner"] == repository.claim_owner
    assert repository.finalized["succeeded"] is True
    assert repository.finalized["result"] == "done"
    assert executor_kwargs["execution_capacity"] is execution_capacity


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

        async def mark_item_running(self, *_args, **_kwargs):
            return True

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
            raise AssertionError("short completion must not wait for lease renewal")

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

        async def mark_item_running(self, *_args, **_kwargs):
            return True

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
async def test_mark_running_failure_does_not_start_native_execution(
    monkeypatch,
) -> None:
    supervisor_failed = asyncio.Event()
    finalized = asyncio.Event()
    execution_started = False

    class Repository:
        async def mark_item_running(self, *_args, **_kwargs):
            supervisor_failed.set()
            raise RuntimeError("repository unavailable")

        async def finalize_item(self, *_args, **_kwargs):
            finalized.set()
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            nonlocal execution_started
            execution_started = True
            assert task_id == "item-1"
            return "execution-1"

    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    item = {
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

    execution = asyncio.create_task(service._execute_item(item))
    await asyncio.wait_for(supervisor_failed.wait(), timeout=1)
    await asyncio.wait_for(execution, timeout=1)

    assert finalized.is_set()
    assert execution_started is False


@pytest.mark.asyncio
async def test_terminal_result_keeps_lease_until_execution_teardown_finishes(
    monkeypatch,
) -> None:
    result = SimpleNamespace(
        status=FakeStatus.COMPLETED,
        result="done",
        error=None,
        stop_reason=None,
        token_usage_records=None,
        execution_done_event=asyncio.Event(),
    )
    finalized = asyncio.Event()
    lease_renewed = asyncio.Event()

    class Repository:
        async def mark_item_running(self, *_args, **_kwargs):
            return True

        async def renew_item_lease(self, *_args, **_kwargs):
            lease_renewed.set()
            return {"valid": True, "cancel_requested": False}

        async def finalize_item(self, *_args, **_kwargs):
            finalized.set()
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            return "execution-1"

    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(
            poll_interval_seconds=0.1,
            lease_seconds=10,
        ),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    item = {
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

    execution = asyncio.create_task(service._execute_item(item))
    await asyncio.wait_for(lease_renewed.wait(), timeout=2)

    assert not finalized.is_set()
    assert not execution.done()

    result.execution_done_event.set()
    await asyncio.wait_for(execution, timeout=1)

    assert finalized.is_set()


@pytest.mark.asyncio
async def test_detached_mark_running_fatal_is_raised_without_starting_execution(
    monkeypatch,
) -> None:
    class ItemFatal(BaseException):
        pass

    execution_started = False

    class Repository:
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
            raise ItemFatal("item aborted")

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            nonlocal execution_started
            execution_started = True
            assert task_id == "item-1"
            return "execution-1"

    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        service_module,
        "resolve_subagent_model_name",
        lambda *_args, **_kwargs: "model-a",
    )
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(lease_seconds=10),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    while service._executions:
        await asyncio.sleep(0)

    assert execution_started is False
    assert service._execution_ids == {}
    assert service._item_batches == {}
    with pytest.raises(ItemFatal, match="item aborted"):
        await service.stop()


@pytest.mark.asyncio
async def test_batch_stop_propagates_original_execution_fatal_without_future_read(
    monkeypatch,
) -> None:
    class ExecutionFatal(BaseException):
        pass

    fatal = ExecutionFatal("original batch execution fatal")
    execution_done = asyncio.Event()
    result = SimpleNamespace(
        status=FakeStatus.RUNNING,
        result=None,
        error=None,
        stop_reason=None,
        token_usage_records=None,
        completed_at=None,
        execution_done_event=execution_done,
        get_fatal_error=lambda: fatal,
    )
    running = asyncio.Event()
    cleaned: list[str] = []

    class Repository:
        def __init__(self) -> None:
            self.claimed = False
            self.finalized = False

        async def claim_items(self, **_kwargs):
            if self.claimed:
                return []
            self.claimed = True
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
            running.set()
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
    monkeypatch.setattr(
        service_module,
        "resolve_subagent_model_name",
        lambda *_args, **_kwargs: "model-a",
    )
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        lambda _execution_id: None,
    )
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(poll_interval_seconds=0.1),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await service.start()
    await asyncio.wait_for(running.wait(), timeout=1)
    result.status = FakeStatus.FAILED
    result.error = str(fatal)
    result.completed_at = service_module.datetime.now(service_module.UTC)
    execution_done.set()
    while service._executions:
        await asyncio.sleep(0)

    with pytest.raises(ExecutionFatal) as raised:
        await service.stop()

    assert raised.value is fatal
    assert repository.finalized is False
    assert cleaned == ["execution-1"]


@pytest.mark.asyncio
async def test_terminal_persistence_retry_preserves_success_semantics(
    monkeypatch,
) -> None:
    result = SimpleNamespace(
        status=FakeStatus.COMPLETED,
        result="completed work",
        error=None,
        stop_reason=None,
        token_usage_records=None,
    )
    finalize_calls: list[dict] = []

    class Repository:
        async def mark_item_running(self, *_args, **_kwargs):
            return True

        async def finalize_item(self, *_args, **kwargs):
            finalize_calls.append(kwargs)
            if len(finalize_calls) == 1:
                raise RuntimeError("commit outcome unknown")
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            assert task_id == "item-1"
            return "execution-1"

    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    item = {
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

    await service._execute_item(item)

    assert len(finalize_calls) == 2
    assert all(call["succeeded"] is True for call in finalize_calls)
    assert all(call["result"] == "completed work" for call in finalize_calls)


@pytest.mark.asyncio
async def test_teardown_lease_renewal_error_requests_cancellation_immediately(
    monkeypatch,
) -> None:
    execution_done = asyncio.Event()
    cancellation_requests: list[str] = []
    result = SimpleNamespace(execution_done_event=execution_done)

    class Repository:
        async def renew_item_lease(self, *_args, **_kwargs):
            raise RuntimeError("lease store unavailable")

    def request_cancel(execution_id: str) -> None:
        cancellation_requests.append(execution_id)
        execution_done.set()

    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        request_cancel,
    )
    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(lease_seconds=30),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    await asyncio.wait_for(
        service._wait_for_execution_teardown(
            item_id="item-1",
            execution_id="execution-1",
            lease_owner=service._lease_owner,
        ),
        timeout=1,
    )

    assert cancellation_requests == ["execution-1"]


@pytest.mark.asyncio
async def test_late_claim_compensation_waits_for_all_items_and_logs_each_error(
    caplog,
) -> None:
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    compensation_calls: list[str] = []
    items = [
        {"id": "item-1"},
        {"id": "item-2"},
    ]

    class Repository:
        async def claim_items(self, **_kwargs):
            return items

        async def requeue_item_after_admission_failure(self, item_id, **_kwargs):
            compensation_calls.append(item_id)
            if item_id == "item-1":
                await second_started.wait()
                raise RuntimeError("first compensation failed")
            second_started.set()
            await release_second.wait()
            raise RuntimeError("second compensation failed")

    service = SubagentBatchService(
        repository=Repository(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=2),
    )
    service._stop.set()
    caplog.set_level("ERROR")

    run = asyncio.create_task(
        service.run_once(now=service_module.datetime.now(service_module.UTC)),
    )
    await asyncio.wait_for(second_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert not run.done()
    release_second.set()
    await asyncio.wait_for(run, timeout=1)

    assert sorted(compensation_calls) == ["item-1", "item-2"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("item_id=item-1" in message for message in messages)
    assert any("item_id=item-2" in message for message in messages)


@pytest.mark.asyncio
async def test_stop_external_cancellation_preserves_pending_fatal_and_cleanup(
    monkeypatch,
) -> None:
    class PendingFatal(BaseException):
        pass

    execution_done = asyncio.Event()
    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        completed_at=service_module.datetime.now(service_module.UTC),
        execution_done_event=execution_done,
    )
    requested: list[str] = []
    cleaned: list[str] = []
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    async def pending_item() -> None:
        await asyncio.Event().wait()

    item_task = asyncio.create_task(pending_item())
    service._executions["item-1"] = item_task
    service._execution_ids["item-1"] = "execution-1"
    service._item_batches["item-1"] = "batch-1"
    service._record_fatal(PendingFatal("fatal before shutdown"))
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        requested.append,
    )
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)

    stop_task = asyncio.create_task(service.stop())
    while not requested:
        await asyncio.sleep(0)
    stop_task.cancel()
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert cleaned == []

    execution_done.set()
    with pytest.raises(PendingFatal, match="fatal before shutdown"):
        await asyncio.wait_for(stop_task, timeout=1)

    assert item_task.cancelled()
    assert cleaned == ["execution-1"]
    assert service._executions == {}
    assert service._execution_ids == {}
    assert service._item_batches == {}


@pytest.mark.asyncio
async def test_stop_wait_for_timeout_propagates_item_fatal_from_forced_cleanup_cancel() -> None:
    class ItemFatal(BaseException):
        pass

    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    first_cancel_handled = asyncio.Event()

    async def fail_on_forced_cleanup_cancel() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            first_cancel_handled.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert service._first_fatal is None
            raise ItemFatal("item failed during forced cleanup cancellation")

    item_task = asyncio.create_task(fail_on_forced_cleanup_cancel())
    service._executions["item-1"] = item_task
    item_task.add_done_callback(
        lambda completed: service._execution_done("item-1", completed),
    )

    with pytest.raises(
        ItemFatal,
        match="item failed during forced cleanup cancellation",
    ):
        await asyncio.wait_for(service.stop(), timeout=0.1)

    assert first_cancel_handled.is_set()
    assert item_task.done()
    assert service._first_fatal is None


@pytest.mark.asyncio
async def test_stop_external_timeout_preserves_pending_fatal_and_cleanup(
    monkeypatch,
) -> None:
    class PendingFatal(BaseException):
        pass

    execution_done = asyncio.Event()
    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        completed_at=service_module.datetime.now(service_module.UTC),
        execution_done_event=execution_done,
    )
    cleaned: list[str] = []
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    service._execution_ids["item-1"] = "execution-1"
    service._record_fatal(PendingFatal("fatal before timeout"))
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        lambda _execution_id: None,
    )
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )
    monkeypatch.setattr(service_module, "cleanup_background_task", cleaned.append)

    async def finish_teardown() -> None:
        await asyncio.sleep(0.02)
        execution_done.set()

    teardown = asyncio.create_task(finish_teardown())
    with pytest.raises(PendingFatal, match="fatal before timeout"):
        async with asyncio.timeout(0.01):
            await service.stop()
    await teardown

    assert cleaned == ["execution-1"]
    assert service._shutdown_execution_ids == set()


@pytest.mark.asyncio
async def test_stop_pending_fatal_does_not_defeat_external_shutdown_deadline(
    monkeypatch,
) -> None:
    class PendingFatal(BaseException):
        pass

    result = SimpleNamespace(
        status=FakeStatus.FAILED,
        completed_at=service_module.datetime.now(service_module.UTC),
        execution_done_event=asyncio.Event(),
    )
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    service._execution_ids["item-1"] = "execution-1"
    service._record_fatal(PendingFatal("fatal before stuck teardown"))
    monkeypatch.setattr(
        service_module,
        "request_cancel_background_task",
        lambda _execution_id: None,
    )
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _execution_id: result,
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(PendingFatal, match="fatal before stuck teardown"):
        async with asyncio.timeout(0.01):
            await service.stop()

    assert loop.time() - started < 0.5


@pytest.mark.asyncio
async def test_stop_external_cancel_has_hard_drain_limit_for_cancellation_resistant_item(
    caplog,
) -> None:
    class LateItemFatal(BaseException):
        pass

    first_cancel_caught = asyncio.Event()
    release_teardown = asyncio.Event()
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )

    async def cancellation_resistant_item() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            first_cancel_caught.set()
        while not release_teardown.is_set():
            try:
                await release_teardown.wait()
            except asyncio.CancelledError:
                pass
        raise LateItemFatal("item teardown failed after detached cleanup")

    item_task = asyncio.create_task(cancellation_resistant_item())
    service._executions["item-1"] = item_task
    item_task.add_done_callback(
        lambda completed: service._execution_done("item-1", completed),
    )
    caplog.set_level("CRITICAL")

    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(first_cancel_caught.wait(), timeout=1)
    stop_task.cancel()
    hard_limit = asyncio.create_task(asyncio.sleep(0.5))
    done, _pending = await asyncio.wait(
        {stop_task, hard_limit},
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        assert stop_task in done
        with pytest.raises(asyncio.CancelledError):
            await stop_task
        assert not item_task.done()
        assert any("resisted cancellation past the drain deadline" in record.getMessage() for record in caplog.records)
    finally:
        release_teardown.set()
        item_results = await asyncio.wait_for(
            asyncio.gather(item_task, return_exceptions=True),
            timeout=1,
        )
        assert isinstance(item_results[0], LateItemFatal)
        hard_limit.cancel()
        await asyncio.gather(hard_limit, return_exceptions=True)

    assert isinstance(service._first_fatal, LateItemFatal)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_source", ["detached", "poller"])
async def test_detached_and_poller_fatals_share_first_fatal_wins(
    first_source,
) -> None:
    class DetachedFatal(BaseException):
        pass

    class PollerFatal(BaseException):
        pass

    async def raise_fatal(exc: BaseException) -> None:
        raise exc

    detached = asyncio.create_task(raise_fatal(DetachedFatal("detached first")))
    poller = asyncio.create_task(raise_fatal(PollerFatal("poller first")))
    await asyncio.wait({detached, poller})

    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    callbacks = {
        "detached": lambda: service._execution_done("item-1", detached),
        "poller": lambda: service._poller_done(poller),
    }
    callbacks[first_source]()
    callbacks["poller" if first_source == "detached" else "detached"]()

    expected = DetachedFatal if first_source == "detached" else PollerFatal
    expected_message = "detached first" if first_source == "detached" else "poller first"
    with pytest.raises(expected, match=expected_message):
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["cancellation-resistant-item", "stuck-fence"])
@pytest.mark.parametrize("with_fatal", [False, True])
async def test_bare_stop_has_total_deadline_and_preserves_fatal_priority(
    monkeypatch,
    blocker,
    with_fatal,
) -> None:
    class ShutdownFatal(BaseException):
        pass

    monkeypatch.setattr(service_module, "_SHUTDOWN_DEADLINE_SECONDS", 0.06)
    service = SubagentBatchService(
        repository=SimpleNamespace(),
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(max_running=1),
    )
    fatal = ShutdownFatal(f"fatal with {blocker}")
    if with_fatal:
        service._record_fatal(fatal)

    release = asyncio.Event()
    item_started = asyncio.Event()
    item_task: asyncio.Task[None] | None = None
    if blocker == "cancellation-resistant-item":

        async def cancellation_resistant_item() -> None:
            item_started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass

        item_task = asyncio.create_task(cancellation_resistant_item())
        service._executions["item-1"] = item_task
        await item_started.wait()
    else:
        stuck_result = SimpleNamespace(
            status=FakeStatus.FAILED,
            completed_at=service_module.datetime.now(service_module.UTC),
            execution_done_event=release,
        )
        service._execution_ids["item-1"] = "execution-1"
        monkeypatch.setattr(
            service_module,
            "request_cancel_background_task",
            lambda _execution_id: None,
        )
        monkeypatch.setattr(
            service_module,
            "get_background_task_result",
            lambda _execution_id: stuck_result,
        )

    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        if with_fatal:
            with pytest.raises(ShutdownFatal) as raised:
                await service.stop()
            assert raised.value is fatal
        else:
            with pytest.raises(TimeoutError):
                await service.stop()
        assert loop.time() - started < 0.2
    finally:
        release.set()
        if item_task is not None:
            await asyncio.wait_for(
                asyncio.gather(item_task, return_exceptions=True),
                timeout=1,
            )
        for _ in range(100):
            detached_cleanup = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and task.get_name() == "subagent-batch-stop-cleanup"]
            if not detached_cleanup:
                break
            await asyncio.sleep(0.01)
        assert not detached_cleanup
