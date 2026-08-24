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
                        "execution_spec": _request().execution_spec,
                    },
                }
            ]

        async def mark_item_running(self, *_args, **_kwargs):
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
