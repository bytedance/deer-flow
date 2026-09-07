import asyncio
import threading
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


def _batch_item() -> dict:
    return {
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


@pytest.mark.asyncio
async def test_bookkeeping_failure_does_not_overlap_unsupervised_retry(monkeypatch) -> None:
    """A mark_item_running failure after dispatch must not abandon a live child.

    The first execution stays running (and may even look business-terminal)
    until teardown is confirmed. Finalize/requeue must not happen while that
    child is still live, and a later scheduler pass must not start a second
    overlapping unsupervised execution.
    """
    cancel_requested = asyncio.Event()
    teardown_complete = threading.Event()
    executions: dict[str, SimpleNamespace] = {}
    execution_seq = 0
    max_live_running = 0
    live_running_at_finalize: list[list[str]] = []
    owned_while_waiting: list[str | None] = []

    class Repository:
        def __init__(self) -> None:
            self.item_status = "queued"
            self.mark_calls = 0
            self.finalized = None
            self.lease_renewals = 0

        async def claim_items(self, **_kwargs):
            if self.item_status != "queued":
                return []
            self.item_status = "leased"
            return [_batch_item()]

        async def mark_item_running(self, *_args, **_kwargs):
            self.mark_calls += 1
            if self.mark_calls == 1:
                raise OSError("single synthetic transient DB write failure at mark_item_running")
            latest = executions[f"execution-{execution_seq}"]
            latest.status = FakeStatus.COMPLETED
            latest.result = "retry-done"
            latest.execution_done_event.set()
            self.item_status = "running"
            return True

        async def renew_item_lease(self, *_args, **_kwargs):
            self.lease_renewals += 1
            return {"valid": True, "cancel_requested": False}

        async def finalize_item(self, *_args, **kwargs):
            live_running_at_finalize.append([eid for eid, row in executions.items() if not row.execution_done_event.is_set()])
            self.finalized = kwargs
            self.item_status = "queued"
            return True

    class Executor:
        def __init__(self, **_kwargs) -> None:
            pass

        def execute_async(self, _prompt, task_id=None):
            nonlocal execution_seq
            assert task_id == "item-1"
            execution_seq += 1
            execution_id = f"execution-{execution_seq}"
            executions[execution_id] = SimpleNamespace(
                status=FakeStatus.RUNNING,
                result=None,
                error=None,
                stop_reason=None,
                token_usage_records=None,
                completed_at=None,
                cancel_requested=False,
                execution_done_event=threading.Event(),
            )
            return execution_id

    def read_result(execution_id):
        nonlocal max_live_running
        result = executions[execution_id]
        if not result.execution_done_event.is_set():
            owned_while_waiting.append(service._execution_ids.get("item-1"))
        live = [eid for eid, row in executions.items() if not row.execution_done_event.is_set()]
        max_live_running = max(max_live_running, len(live))
        if result.cancel_requested and teardown_complete.is_set() and not result.execution_done_event.is_set():
            result.status = FakeStatus.CANCELLED
            result.error = "Cancelled after supervisor bookkeeping failure"
            result.execution_done_event.set()
        return result

    def request_cancel(execution_id):
        row = executions[execution_id]
        row.cancel_requested = True
        # Business-terminal cancellation is not teardown. The child stays
        # live until the test releases execution_done_event.
        row.status = FakeStatus.CANCELLED
        cancel_requested.set()

    repository = Repository()
    monkeypatch.setattr(service_module, "get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "model-a")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "SubagentStatus", FakeStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", read_result)
    monkeypatch.setattr(service_module, "request_cancel_background_task", request_cancel)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _execution_id: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    service = SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(poll_interval_seconds=0.1, lease_seconds=10),
        runtime_config=SubagentRuntimeConfig(max_running=2),
    )

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.wait_for(cancel_requested.wait(), timeout=1)

    assert repository.finalized is None
    assert executions["execution-1"].status is FakeStatus.CANCELLED
    assert not executions["execution-1"].execution_done_event.is_set()
    assert service._execution_ids.get("item-1") == "execution-1"
    assert repository.item_status == "leased"

    teardown_complete.set()
    await asyncio.wait_for(asyncio.gather(*list(service._executions.values())), timeout=1)

    assert repository.finalized is not None
    assert repository.finalized["succeeded"] is False
    assert "mark_item_running" in (repository.finalized["error"] or "")
    assert live_running_at_finalize == [[]]
    assert executions["execution-1"].execution_done_event.is_set()
    assert service._execution_ids == {}
    assert owned_while_waiting
    assert all(owner == "execution-1" for owner in owned_while_waiting)

    await service.run_once(now=service_module.datetime.now(service_module.UTC))
    await asyncio.wait_for(asyncio.gather(*list(service._executions.values())), timeout=1)

    assert execution_seq == 2
    assert executions["execution-1"].status is FakeStatus.CANCELLED
    assert executions["execution-2"].status is FakeStatus.COMPLETED
    assert max_live_running == 1
    assert repository.mark_calls == 2
