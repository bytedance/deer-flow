"""Native foreground Scheduler support for trusted execution-only hosts."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from test_scheduled_task_service import DummyRunRepo, DummyTaskRepo

from app.scheduler.service import ScheduledTaskService


@pytest.mark.asyncio
async def test_foreground_scheduler_is_available_without_recovery_or_dispatch():
    task = {"id": "task-one", "user_id": "owner", "thread_id": "thread-one", "status": "enabled", "schedule_type": "once", "schedule_spec": {"run_at": "2026-10-10T00:00:00+00:00"}, "timezone": "UTC"}
    tasks, occurrences, launch = DummyTaskRepo([task]), DummyRunRepo(), AsyncMock()
    service = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, multi_instance=True, dispatch_enabled=False)
    await service.start()
    try:
        assert service.is_available and not service.is_running
        assert occurrences.reconcile_count == 0
        assert tasks.reconciled_stuck_once is None
        await service.run_once(now=datetime.now(UTC))
        assert not tasks.claimed
        result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
        assert result["outcome"] == "queued" and result["run_id"] is None
        assert occurrences.created["status"] == "queued"
        launch.assert_not_awaited()
    finally:
        await service.stop()
    assert not service.is_available


@pytest.mark.asyncio
async def test_default_scheduler_still_starts_native_dispatch_and_recovery():
    service = ScheduledTaskService(task_repo=DummyTaskRepo([]), task_run_repo=DummyRunRepo(), launch_run=AsyncMock(), poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, multi_instance=True)
    await service.start()
    try:
        assert service.is_running and service.is_available
        assert service._task_run_repo.reconcile_count == 1
    finally:
        await service.stop()


def test_only_worker_role_suppresses_scheduler_dispatch():
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost

    assert NativeWorkerHost.scheduler_dispatch_enabled is False
    assert getattr(NativeDispatchHost, "scheduler_dispatch_enabled", True) is True


@pytest.mark.asyncio
async def test_foreground_real_native_tools_create_and_stop_owner_occurrence(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence
    from langchain.tools import ToolRuntime
    from test_scheduler_capability_access import _real_repos, _seed_runs

    from app.gateway import scheduled_task_access as access
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from deerflow.persistence.engine import close_engine
    from deerflow.tools.scheduled_tasks import schedule_task, stop_scheduled_task

    prepare, sf, tasks, occurrences, _, _ = await _real_repos(monkeypatch, tmp_path, source=AUTH_SOURCE_INTERNAL)
    launch = AsyncMock()
    service = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, multi_instance=True, dispatch_enabled=False)
    monkeypatch.setattr(access, "get_scheduled_task_service", lambda request: service)
    await service.start()
    try:
        capability = await prepare()
        runtime = ToolRuntime(state={}, context={"app_config": access.get_config(), "__scheduler_capability": capability, "interaction_mode": "interactive"}, config={}, stream_writer=lambda _: None, tool_call_id="native-create", store=None)
        created = await schedule_task.coroutine(runtime=runtime, action="create", title="Foreground schedule", prompt="Write report", schedule_type="interval", schedule_spec={"every_seconds": 3600}, timezone="UTC")
        task_id = created["task"]["id"]
        stored = await tasks.get(task_id, user_id="alice")
        assert stored["origin_thread_id"] == "origin"
        assert stored["user_id"] == "alice"
        from deerflow.persistence.run.model import RunRow

        await _seed_runs(
            sf,
            occurrence("occurrence-one", task_id, seq=1, status="running", run_id="run-1", thread_id="scheduled-thread"),
            RunRow(run_id="run-1", thread_id="scheduled-thread", user_id="alice", status="running", metadata_json={"scheduled_task_id": task_id, "scheduled_task_run_id": "occurrence-one"}),
        )
        # Rebind through native Gateway admission for an internally authenticated
        # scheduled turn, rather than serializing authority into graph state.
        from test_scheduler_capability_access import _setup

        prepare_stop, _, _, _, _, _, _, request = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled", task=stored)
        monkeypatch.setattr(access, "get_scheduled_task_repo", lambda request: tasks)
        monkeypatch.setattr(access, "get_scheduled_task_run_repo", lambda request: occurrences)
        monkeypatch.setattr(access, "get_scheduled_task_service", lambda request: service)
        request.app.state.scheduled_task_service = service
        stop_capability = await prepare_stop(scheduled_task_runtime={"user_id": "alice", "task_id": task_id, "occurrence_id": "occurrence-one"})
        runtime.context = {"app_config": access.get_config(), "__scheduler_capability": stop_capability, "interaction_mode": "scheduled"}
        result = await stop_scheduled_task.coroutine(runtime=runtime)
        assert result.get("stop_requested") is True, result
        stored_occurrence = (await occurrences.list_by_task(task_id))[0]
        assert stored_occurrence["stop_requested_run_id"] == "run-1"
        assert not service.is_running and service.is_available
        launch.assert_not_awaited()
    finally:
        await service.stop()
        await close_engine()


@pytest.mark.asyncio
async def test_foreground_features_keep_poller_semantics_and_operator_tool_flags():
    from types import SimpleNamespace

    from test_scheduler_tools import _config

    from app.gateway.deps import is_scheduler_available, is_scheduler_running
    from app.gateway.routers.features import _scheduled_tasks_feature

    service = ScheduledTaskService(task_repo=DummyTaskRepo([]), task_run_repo=DummyRunRepo(), launch_run=AsyncMock(), poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=1, dispatch_enabled=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduled_task_service=service, scheduled_task_repo=service._task_repo)))
    assert not is_scheduler_available(request)
    await service.start()
    try:
        assert is_scheduler_available(request) and not is_scheduler_running(request)
        feature = _scheduled_tasks_feature(request, _config())
        assert feature.available and feature.tool_enabled and not feature.running
        assert not _scheduled_tasks_feature(request, _config(enabled=False)).tool_enabled
        assert not _scheduled_tasks_feature(request, _config(tool_enabled=False)).tool_enabled
    finally:
        await service.stop()
    assert not is_scheduler_available(request)
