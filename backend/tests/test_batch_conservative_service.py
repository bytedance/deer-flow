"""Dispatch intent must commit before a native child can have effects."""

import asyncio
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents import batch_service as service_module
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.batch_service import SubagentBatchService


class Status(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self):
        return self is not Status.RUNNING


@pytest.fixture
def execution(monkeypatch):
    monkeypatch.setattr(service_module, "SubagentStatus", Status)
    repository = SimpleNamespace(
        renew_item_lease=AsyncMock(return_value={"valid": True, "cancel_requested": False}),
        mark_item_dispatch_started=AsyncMock(return_value=True),
        mark_item_running=AsyncMock(return_value=True),
        mark_item_outcome_unknown=AsyncMock(return_value=True),
        finalize_item=AsyncMock(return_value=True),
        requeue_item_after_admission_failure=AsyncMock(return_value=True),
    )
    result = SimpleNamespace(status=service_module.SubagentStatus.COMPLETED, result="done", error=None, stop_reason=None, token_usage_records=None)
    executor = SimpleNamespace(execute_async=Mock(return_value="execution-1"))
    monkeypatch.setattr(service_module, "SubagentExecutor", lambda **_kwargs: executor)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: result)
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_args, **_kwargs: "test-model")
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    # The stored policy, not the new worker's configuration, governs old batches.
    service = SubagentBatchService(repository=repository, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=SimpleNamespace())
    monkeypatch.setattr(service, "_release_execution", lambda _execution_id: None)
    item = {
        "id": "item-1",
        "item_key": "write",
        "prompt": "Write once",
        "batch": {
            "id": "batch-1",
            "thread_id": "thread-1",
            "user_id": "owner",
            "run_id": "run-1",
            "recovery_policy": "conservative",
            "execution_spec": {"subagent_config": {"name": "general-purpose", "description": "Test", "system_prompt": "Work carefully."}},
        },
    }
    return service, repository, executor, result, item


@pytest.mark.asyncio
async def test_conservative_launch_waits_for_committed_dispatch_intent(execution):
    service, repository, executor, _result, item = execution
    entered, release = asyncio.Event(), asyncio.Event()

    async def commit(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return True

    repository.mark_item_dispatch_started.side_effect = commit
    task = asyncio.create_task(service._execute_item(item, lease_owner="claim-1"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        executor.execute_async.assert_not_called()
    finally:
        release.set()
        await asyncio.wait_for(task, 2)
    executor.execute_async.assert_called_once()
    repository.finalize_item.assert_awaited_once()
    assert repository.finalize_item.call_args.kwargs["succeeded"] is True


@pytest.mark.asyncio
async def test_rejected_dispatch_intent_never_launches(execution):
    service, repository, executor, _result, item = execution
    repository.mark_item_dispatch_started.return_value = False
    await service._execute_item(item, lease_owner="claim-1")
    executor.execute_async.assert_not_called()
    repository.finalize_item.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dispatch_commit", "launch", "missing_execution", "result_commit", "timeout"])
async def test_uncertain_dispatch_never_enters_ordinary_retry(execution, monkeypatch, failure):
    service, repository, executor, result, item = execution
    if failure == "dispatch_commit":
        repository.mark_item_dispatch_started.side_effect = OSError("commit acknowledgement lost")
    elif failure == "launch":
        executor.execute_async.side_effect = RuntimeError("launch acknowledgement lost")
    elif failure == "missing_execution":
        monkeypatch.setattr(service_module, "get_background_task_result", lambda _execution_id: None)
    elif failure == "result_commit":
        repository.finalize_item.side_effect = OSError("result acknowledgement lost")
    else:
        result.status = service_module.SubagentStatus.TIMED_OUT
        result.error = "execution timed out"
    await service._execute_item(item, lease_owner="claim-1")
    repository.mark_item_outcome_unknown.assert_awaited_once()
    repository.requeue_item_after_admission_failure.assert_not_awaited()
    # A lost success acknowledgement may already have committed. The repository
    # must reject unknown over a saved result, and the service must never issue
    # a second finalization that changes success into a retryable failure.
    assert repository.finalize_item.await_count == (1 if failure == "result_commit" else 0)


@pytest.mark.asyncio
async def test_proven_admission_failure_can_requeue(execution):
    service, repository, _executor, result, item = execution
    result.status = service_module.SubagentStatus.FAILED
    result.admission_failure = True
    await service._execute_item(item, lease_owner="claim-1")
    repository.requeue_item_after_admission_failure.assert_awaited_once()
    repository.mark_item_outcome_unknown.assert_not_awaited()
    repository.finalize_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_freezes_host_recovery_policy():
    repository = SimpleNamespace(create_batch=AsyncMock(return_value={"id": "batch-1"}))
    service = SubagentBatchService(repository=repository, config=SubagentBatchesConfig(recovery_policy="conservative"), runtime_config=SubagentRuntimeConfig())
    request = BatchSubmitRequest(
        user_id="owner",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Write",
        subagent_type="general-purpose",
        items=[{"key": "write", "prompt": "Write once"}],
        max_live_items=None,
        max_running_items=None,
        execution_spec={"recovery_policy": "retry"},
    )
    await service.submit(request)
    assert repository.create_batch.call_args.kwargs["recovery_policy"] == "conservative"
