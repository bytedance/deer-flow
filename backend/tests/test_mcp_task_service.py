import asyncio
import gc
import logging
import weakref
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.mcp_tasks.service as service_module
from app.mcp_tasks.errors import PermanentNotificationError
from app.mcp_tasks.service import McpTaskService
from deerflow.mcp.tasks import (
    McpTaskDriverRegistry,
    TaskSnapshot,
    TaskStatus,
    TaskSubmission,
    TaskSubmitRequest,
)
from deerflow.mcp.tasks.ordinary import McpTaskProtocolError
from deerflow.persistence.mcp_tasks import DuplicateMcpRemoteTaskError
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.schemas import RunStatus


class FakeRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.claimed = False
        self.applied = []
        self.released = []
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return {"id": kwargs["task_id"], **kwargs}

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [dict(row) for row in self.rows]

    async def apply_snapshot(self, task_id, **kwargs):
        self.applied.append((task_id, kwargs))
        return True

    async def release_claim(self, task_id, **kwargs):
        self.released.append((task_id, kwargs))
        return True

    async def release_poll_claim_after_cancellation(self, task_id, **kwargs):
        self.released.append((task_id, kwargs))
        return True


class FailingApplyRepository(FakeRepository):
    async def apply_snapshot(self, task_id, **kwargs):
        if task_id == "task-1":
            raise RuntimeError("database unavailable")
        return await super().apply_snapshot(task_id, **kwargs)


class FailingCreateRepository(FakeRepository):
    async def create(self, **kwargs):
        self.created.append(kwargs)
        raise RuntimeError("database unavailable")


class BlockingCreateRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.create_started = asyncio.Event()

    async def create(self, **kwargs):
        self.created.append(kwargs)
        self.create_started.set()
        await asyncio.Event().wait()


class DuplicateCreateRepository(FakeRepository):
    async def create(self, **kwargs):
        self.created.append(kwargs)
        raise DuplicateMcpRemoteTaskError("already tracked")


class FakeDriver:
    def __init__(
        self,
        snapshots=None,
        *,
        submission=None,
        error: Exception | None = None,
        cancel_error: Exception | None = None,
    ):
        self.snapshots = list(snapshots or [])
        self.submission = submission
        self.error = error
        self.cancel_error = cancel_error
        self.status_calls = []
        self.submit_calls = []
        self.cancel_calls = []

    async def submit(self, request):
        self.submit_calls.append(request)
        if self.submission is None:
            raise AssertionError(f"unexpected submit: {request}")
        return self.submission

    async def get_status(self, task):
        self.status_calls.append(task)
        if self.error is not None:
            raise self.error
        return self.snapshots.pop(0)

    async def cancel(self, task):
        self.cancel_calls.append(task)
        if self.cancel_error is not None:
            raise self.cancel_error
        return TaskSnapshot(status=TaskStatus.CANCELLED)


class HangingDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = False

    async def get_status(self, task):
        self.status_calls.append(task)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class BlockingCancelDriver(FakeDriver):
    def __init__(self, *, submission):
        super().__init__(submission=submission)
        self.cancel_started = asyncio.Event()
        self.finish_cancel = asyncio.Event()
        self.cancel_finished = asyncio.Event()
        self.cancel_completed = False
        self.cancel_interrupted = False

    async def cancel(self, task):
        self.cancel_calls.append(task)
        self.cancel_started.set()
        try:
            await self.finish_cancel.wait()
        except asyncio.CancelledError:
            self.cancel_interrupted = True
            self.cancel_finished.set()
            raise
        self.cancel_completed = True
        self.cancel_finished.set()
        return TaskSnapshot(status=TaskStatus.CANCELLED)


def _claimed_row(*, driver_name="fake"):
    return {
        "id": "task-1",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "run_id": "run-1",
        "tool_call_id": "call-1",
        "server_name": "reports",
        "driver_name": driver_name,
        "remote_task_id": "remote-1",
        "task_name": "Generate report",
        "status": "working",
        "driver_data": {"status_tool": "status"},
        "lease_owner": "ignored-by-service-fixture",
        "lease_token": "lease-token-1",
        "notification_lease_token": "notify-lease-token-1",
    }


@pytest.mark.asyncio
async def test_submit_persists_remote_handle_before_returning():
    now = datetime.now(UTC)
    repo = FakeRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED, poll_after_seconds=9),
            driver_data={"status_tool": "status"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        driver_data={"submit_tool": "submit"},
    )

    created = await service.submit(driver_name="fake", request=request, now=now)

    assert created["remote_task_id"] == "remote-1"
    persisted = repo.created[0]
    assert persisted["next_poll_at"] == now + timedelta(seconds=9)
    assert persisted["driver_data"] == {"submit_tool": "submit", "status_tool": "status"}
    assert driver.submit_calls[0].local_task_id == created["id"]


@pytest.mark.asyncio
async def test_submit_cancels_remote_task_when_persistence_fails():
    repo = FailingCreateRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"status_tool": "status", "cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        driver_data={"submit_tool": "submit"},
        local_task_id="task-1",
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.submit(driver_name="fake", request=request)

    assert len(driver.cancel_calls) == 1
    cancelled = driver.cancel_calls[0]
    assert cancelled.local_task_id == "task-1"
    assert cancelled.remote_task_id == "remote-1"
    assert cancelled.driver_data == {
        "submit_tool": "submit",
        "status_tool": "status",
        "cancel_tool": "cancel",
    }


@pytest.mark.asyncio
async def test_submit_cancellation_during_persistence_cancels_remote_task():
    repo = BlockingCreateRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        local_task_id="task-1",
    )

    submit_task = asyncio.create_task(service.submit(driver_name="fake", request=request))
    await repo.create_started.wait()
    submit_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await submit_task

    assert len(driver.cancel_calls) == 1
    cancelled = driver.cancel_calls[0]
    assert cancelled.local_task_id == "task-1"
    assert cancelled.remote_task_id == "remote-1"


@pytest.mark.asyncio
async def test_submit_repeated_cancellation_does_not_interrupt_compensation():
    repo = BlockingCreateRepository()
    driver = BlockingCancelDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        local_task_id="task-1",
    )

    submit_task = asyncio.create_task(service.submit(driver_name="fake", request=request))
    await repo.create_started.wait()
    submit_task.cancel()
    await driver.cancel_started.wait()

    submit_task.cancel()
    driver.finish_cancel.set()

    with pytest.raises(asyncio.CancelledError):
        await submit_task

    assert len(driver.cancel_calls) == 1
    assert driver.cancel_completed
    assert not driver.cancel_interrupted


@pytest.mark.asyncio
async def test_submit_stops_waiting_for_hung_compensation_without_cancelling_it(monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0)
    repo = BlockingCreateRepository()
    driver = BlockingCancelDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        local_task_id="task-1",
    )

    submit_task = asyncio.create_task(service.submit(driver_name="fake", request=request))
    await repo.create_started.wait()
    submit_task.cancel()

    with caplog.at_level(logging.WARNING), pytest.raises(asyncio.CancelledError):
        await submit_task

    assert "cancellation continues in the background" in caplog.text
    await driver.cancel_started.wait()
    assert not driver.cancel_interrupted
    assert not driver.cancel_completed

    driver.finish_cancel.set()
    await driver.cancel_finished.wait()

    assert len(driver.cancel_calls) == 1
    assert driver.cancel_completed
    assert not driver.cancel_interrupted


@pytest.mark.asyncio
async def test_submit_cancellation_preserves_cancelled_error_when_compensation_fails(caplog):
    repo = BlockingCreateRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
        ),
        cancel_error=RuntimeError("cancel unavailable"),
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={},
        local_task_id="task-1",
    )

    submit_task = asyncio.create_task(service.submit(driver_name="fake", request=request))
    await repo.create_started.wait()
    submit_task.cancel()

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await submit_task

    assert len(driver.cancel_calls) == 1
    assert "Failed to cancel untracked MCP task" in caplog.text
    assert "cancel unavailable" in caplog.text


@pytest.mark.asyncio
async def test_submit_cancels_remote_task_when_its_id_exceeds_storage_limit():
    repo = FakeRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="r" * 256,
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    with pytest.raises(McpTaskProtocolError, match="remote_task_id.*255"):
        await service.submit(
            driver_name="fake",
            request=TaskSubmitRequest(
                user_id="user-1",
                thread_id="thread-1",
                run_id="run-1",
                tool_call_id="call-1",
                server_name="reports",
                task_name="Generate report",
                arguments={},
                local_task_id="task-1",
            ),
        )

    assert repo.created == []
    assert len(driver.cancel_calls) == 1
    assert driver.cancel_calls[0].remote_task_id == "r" * 256


@pytest.mark.asyncio
async def test_duplicate_remote_handle_is_rejected_without_cancelling_existing_task():
    repo = DuplicateCreateRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data={"cancel_tool": "cancel"},
        )
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    with pytest.raises(DuplicateMcpRemoteTaskError, match="already tracked"):
        await service.submit(
            driver_name="fake",
            request=TaskSubmitRequest(
                user_id="user-1",
                thread_id="thread-2",
                run_id="run-2",
                tool_call_id="call-2",
                server_name="reports",
                task_name="Generate report",
                arguments={},
            ),
        )

    assert driver.cancel_calls == []


@pytest.mark.asyncio
async def test_cancel_task_persists_request_without_calling_remote():
    record = {**_claimed_row(), "cancel_requested_at": datetime.now(UTC).isoformat()}
    repo = SimpleNamespace(
        request_cancel=AsyncMock(return_value=record),
        claim_cancel_requests=AsyncMock(return_value=[{**record, "cancel_attempt_count": 1}]),
        apply_cancel_snapshot=AsyncMock(return_value=True),
        release_cancel_claim=AsyncMock(return_value=True),
        get=AsyncMock(return_value={**record, "status": "cancelled"}),
    )
    driver = FakeDriver()
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    result = await service.cancel_task(
        task_id="task-1",
        thread_id="thread-1",
        user_id="user-1",
    )

    assert result == record
    assert driver.cancel_calls == []
    repo.claim_cancel_requests.assert_not_awaited()
    repo.apply_cancel_snapshot.assert_not_awaited()
    repo.release_cancel_claim.assert_not_awaited()
    repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_failure_schedules_retry_from_call_completion_time():
    record = {**_claimed_row(), "cancel_attempt_count": 1}
    repo = SimpleNamespace(
        claim_cancel_requests=AsyncMock(return_value=[record]),
        release_cancel_claim=AsyncMock(return_value=True),
        claim_due_tasks=AsyncMock(return_value=[]),
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(cancel_error=RuntimeError("cancel unavailable")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    scan_started_at = datetime(2000, 1, 1, tzinfo=UTC)

    await service.run_once(now=scan_started_at)

    released = repo.release_cancel_claim.await_args.kwargs
    retry_started_at = released["next_cancel_at"] - timedelta(seconds=5)
    assert retry_started_at > scan_started_at


@pytest.mark.asyncio
async def test_cancel_recovery_failures_are_isolated_and_later_phases_continue(caplog):
    records = [
        {**_claimed_row(), "id": "task-broken", "cancel_attempt_count": 1},
        {**_claimed_row(), "id": "task-sibling", "remote_task_id": "remote-2", "cancel_attempt_count": 1},
    ]

    async def release_cancel_claim(task_id, **_kwargs):
        if task_id == "task-broken":
            raise RuntimeError("cancel recovery store unavailable")
        return True

    repo = SimpleNamespace(
        claim_cancel_requests=AsyncMock(return_value=records),
        release_cancel_claim=AsyncMock(side_effect=release_cancel_claim),
        claim_due_tasks=AsyncMock(return_value=[]),
        claim_notification_work=AsyncMock(return_value=[]),
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(cancel_error=RuntimeError("cancel unavailable")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(),
    )

    with caplog.at_level(logging.ERROR):
        await service.run_once(now=datetime.now(UTC))

    assert repo.release_cancel_claim.await_count == 2
    repo.claim_due_tasks.assert_awaited_once()
    repo.claim_notification_work.assert_awaited_once()
    assert "task-broken" in caplog.text
    assert "cancel recovery store unavailable" in caplog.text


@pytest.mark.asyncio
async def test_notification_delivery_waits_for_successful_agent_run():
    repo = SimpleNamespace(
        mark_notification_dispatched=AsyncMock(return_value=True),
        finish_notification_run=AsyncMock(return_value=True),
        release_notification_claim=AsyncMock(return_value=True),
        defer_dispatched_notification=AsyncMock(return_value=True),
    )
    launch = AsyncMock(return_value={"run_id": "notify-run-1"})
    get_run = AsyncMock(return_value=SimpleNamespace(status=RunStatus.running))
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=launch,
        get_run=get_run,
    )
    now = datetime.now(UTC)
    claimed = {
        **_claimed_row(),
        "notification_status": "claimed",
        "dispatch_version": 2,
        "dispatch_attempt": 0,
        "dispatch_event": {"status": "completed"},
    }

    await service._notify_one(claimed, now=now)

    repo.mark_notification_dispatched.assert_awaited_once()
    repo.finish_notification_run.assert_not_awaited()

    get_run.return_value = SimpleNamespace(status=RunStatus.success)
    await service._notify_one(
        {
            **claimed,
            "notification_status": "dispatched",
            "notification_run_id": "notify-run-1",
        },
        now=now,
    )
    repo.finish_notification_run.assert_awaited_once()
    assert repo.finish_notification_run.await_args.kwargs["delivered"] is True


@pytest.mark.asyncio
async def test_missing_dispatched_notification_run_retries_delivery():
    repo = SimpleNamespace(
        finish_notification_run=AsyncMock(return_value=True),
        defer_dispatched_notification=AsyncMock(return_value=True),
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(return_value=None),
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "dispatched",
            "notification_run_id": "missing-run",
            "dispatch_version": 2,
            "notification_attempt_count": 2,
        },
        now=now,
    )

    repo.defer_dispatched_notification.assert_not_awaited()
    repo.finish_notification_run.assert_awaited_once()
    finished = repo.finish_notification_run.await_args.kwargs
    assert finished["delivered"] is False
    assert finished["next_notification_at"] == now + timedelta(seconds=20)
    assert "missing-run" in finished["error"]


@pytest.mark.asyncio
async def test_notification_failures_are_isolated_and_release_their_lease(caplog):
    records = [
        {
            **_claimed_row(),
            "id": "task-broken",
            "notification_status": "dispatched",
            "notification_run_id": "run-broken",
            "dispatch_version": 2,
        },
        {
            **_claimed_row(),
            "id": "task-success",
            "notification_status": "dispatched",
            "notification_run_id": "run-success",
            "dispatch_version": 3,
        },
    ]
    repo = SimpleNamespace(
        claim_notification_work=AsyncMock(return_value=records),
        finish_notification_run=AsyncMock(return_value=True),
        defer_dispatched_notification=AsyncMock(return_value=True),
        release_notification_lease=AsyncMock(return_value=True),
    )
    get_run = AsyncMock(
        side_effect=[
            RuntimeError("run store unavailable"),
            SimpleNamespace(status=RunStatus.success),
        ]
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=get_run,
    )
    now = datetime.now(UTC)

    with caplog.at_level(logging.ERROR):
        await service._run_notifications(now=now)

    repo.finish_notification_run.assert_awaited_once()
    assert repo.finish_notification_run.await_args.args[0] == "task-success"
    repo.release_notification_lease.assert_awaited_once()
    released = repo.release_notification_lease.await_args
    assert released.args[0] == "task-broken"
    assert released.kwargs["next_notification_at"] == now + timedelta(seconds=5)
    assert "run store unavailable" in released.kwargs["error"]
    assert "task-broken" in caplog.text


@pytest.mark.asyncio
async def test_notification_busy_thread_replaces_claim_with_latest_event():
    repo = SimpleNamespace(
        release_notification_claim=AsyncMock(return_value=True),
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=ConflictError("thread busy")),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "claimed",
            "dispatch_version": 2,
            "dispatch_attempt": 0,
            "dispatch_event": {"status": "input_required"},
        },
        now=now,
    )

    released = repo.release_notification_claim.await_args.kwargs
    assert released["replace_with_latest"] is True
    assert released["next_notification_at"] == now + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_notification_launch_failure_backs_off_and_replaces_with_latest_event():
    repo = SimpleNamespace(
        release_notification_claim=AsyncMock(return_value=True),
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        max_poll_backoff_seconds=300,
        launch_notification=AsyncMock(side_effect=RuntimeError("run store unavailable")),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "claimed",
            "dispatch_version": 2,
            "dispatch_attempt": 0,
            "notification_attempt_count": 3,
            "dispatch_event": {"status": "input_required"},
        },
        now=now,
    )

    released = repo.release_notification_claim.await_args.kwargs
    assert released["replace_with_latest"] is True
    assert released["count_failure"] is True
    assert released["next_notification_at"] == now + timedelta(seconds=40)


@pytest.mark.asyncio
async def test_permanently_rejected_notification_is_dead_lettered():
    repo = SimpleNamespace(
        dead_letter_notification=AsyncMock(return_value=True),
        release_notification_claim=AsyncMock(return_value=True),
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=PermanentNotificationError("Thread thread-1 not found")),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "claimed",
            "dispatch_version": 2,
            "dispatch_attempt": 0,
            "notification_attempt_count": 0,
            "dispatch_event": {"status": "completed"},
        },
        now=now,
    )

    repo.dead_letter_notification.assert_awaited_once()
    dead_lettered = repo.dead_letter_notification.await_args.kwargs
    assert dead_lettered["dispatch_version"] == 2
    assert "not found" in dead_lettered["error"]
    assert dead_lettered["count_failure"] is True
    repo.release_notification_claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_retry_budget_dead_letters_before_creating_another_run():
    repo = SimpleNamespace(
        dead_letter_notification=AsyncMock(return_value=True),
    )
    launch_notification = AsyncMock()
    get_run = AsyncMock()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=launch_notification,
        get_run=get_run,
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "retry",
            "notification_error": "Agent run failed",
            "dispatch_version": 2,
            "dispatch_attempt": 5,
            "notification_attempt_count": 5,
            "dispatch_event": {"status": "completed"},
        },
        now=now,
    )

    launch_notification.assert_not_awaited()
    get_run.assert_not_awaited()
    dead_lettered = repo.dead_letter_notification.await_args.kwargs
    assert dead_lettered["dispatch_version"] == 2
    assert dead_lettered["count_failure"] is False
    assert "5 failed attempts" in dead_lettered["error"]


@pytest.mark.asyncio
async def test_dispatched_notification_retry_budget_dead_letters_before_hydrating_run():
    repo = SimpleNamespace(
        dead_letter_notification=AsyncMock(return_value=True),
    )
    get_run = AsyncMock()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=get_run,
    )
    now = datetime.now(UTC)

    await service._notify_one(
        {
            **_claimed_row(),
            "notification_status": "dispatched",
            "notification_run_id": "notify-run-1",
            "notification_error": "run store unavailable",
            "dispatch_version": 2,
            "notification_attempt_count": 5,
        },
        now=now,
    )

    get_run.assert_not_awaited()
    dead_lettered = repo.dead_letter_notification.await_args.kwargs
    assert dead_lettered["dispatch_version"] == 2
    assert dead_lettered["count_failure"] is False
    assert "5 failed attempts" in dead_lettered["error"]


@pytest.mark.asyncio
async def test_submit_preserves_persistence_error_when_compensation_cancel_fails(caplog):
    repo = FailingCreateRepository()
    driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
        ),
        cancel_error=RuntimeError("cancel unavailable"),
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    request = TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="Generate report",
        arguments={"topic": "MCP"},
        local_task_id="task-1",
    )

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="database unavailable"):
        await service.submit(driver_name="fake", request=request)

    assert "Failed to cancel untracked MCP task" in caplog.text
    assert "cancel unavailable" in caplog.text


@pytest.mark.asyncio
async def test_run_once_polls_without_an_llm_and_schedules_next_poll():
    repo = FakeRepository([_claimed_row()])
    driver = FakeDriver([TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=12)])
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    scan_started_at = datetime(2000, 1, 1, tzinfo=UTC)

    await service.run_once(now=scan_started_at)

    assert driver.status_calls[0].remote_task_id == "remote-1"
    _, update = repo.applied[0]
    assert update["status"] == "working"
    assert update["next_poll_at"] == update["polled_at"] + timedelta(seconds=12)
    assert update["polled_at"] > scan_started_at


@pytest.mark.asyncio
async def test_run_once_caps_remote_poll_hint_to_one_day():
    repo = FakeRepository([_claimed_row()])
    driver = FakeDriver([TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=1e20)])
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    _, update = repo.applied[0]
    assert update["next_poll_at"] == update["polled_at"] + timedelta(days=1)


@pytest.mark.asyncio
async def test_run_once_schedules_driver_error_retry_from_poll_completion_time():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(error=RuntimeError("network down")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    scan_started_at = datetime(2000, 1, 1, tzinfo=UTC)

    await service.run_once(now=scan_started_at)

    _, released = repo.released[0]
    retry_started_at = released["next_poll_at"] - timedelta(seconds=5)
    assert retry_started_at > scan_started_at


@pytest.mark.asyncio
async def test_run_once_stops_terminal_tasks_but_keeps_input_required_on_a_slow_poll():
    rows = [_claimed_row(), {**_claimed_row(), "id": "task-2", "remote_task_id": "remote-2"}]
    repo = FakeRepository(rows)
    driver = FakeDriver(
        [
            TaskSnapshot(status=TaskStatus.COMPLETED, result={"report": "ready"}),
            TaskSnapshot(status=TaskStatus.INPUT_REQUIRED, input_required={"prompt": "Approve?"}),
        ]
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    updates = {task_id: update for task_id, update in repo.applied}
    assert updates["task-1"]["status"] == "completed"
    assert updates["task-1"]["next_poll_at"] is None
    assert updates["task-2"]["status"] == "input_required"
    assert updates["task-2"]["input_required"] == {"prompt": "Approve?"}
    assert updates["task-2"]["next_poll_at"] >= updates["task-2"]["polled_at"] + timedelta(seconds=60)


@pytest.mark.asyncio
async def test_run_once_uses_exponential_backoff_and_caps_transient_errors():
    rows = [
        {**_claimed_row(), "id": "task-1", "consecutive_poll_error_count": 0},
        {**_claimed_row(), "id": "task-2", "consecutive_poll_error_count": 4},
    ]
    repo = FakeRepository(rows)
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(error=RuntimeError("network down")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        max_poll_backoff_seconds=30,
    )

    started_at = datetime.now(UTC)
    await service.run_once(now=started_at)
    finished_at = datetime.now(UTC)

    released = {task_id: update for task_id, update in repo.released}
    assert started_at + timedelta(seconds=5) <= released["task-1"]["next_poll_at"] <= finished_at + timedelta(seconds=5)
    assert started_at + timedelta(seconds=30) <= released["task-2"]["next_poll_at"] <= finished_at + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_protocol_error_terminalizes_instead_of_retrying_forever():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(error=McpTaskProtocolError("missing structuredContent")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    assert repo.released == []
    _, applied = repo.applied[0]
    assert applied["status"] == "failed"
    assert applied["error"] == "missing structuredContent"
    assert applied["next_poll_at"] is None


@pytest.mark.asyncio
async def test_protocol_error_message_is_bounded_before_terminal_persistence():
    oversized_error = "e" * 5_000
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register("fake", FakeDriver(error=McpTaskProtocolError(oversized_error)))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    _, applied = repo.applied[0]
    assert applied["status"] == "failed"
    assert applied["error"] == oversized_error[:4_000]


@pytest.mark.asyncio
async def test_persisted_snapshot_errors_are_bounded_on_submit_and_poll():
    oversized_error = "e" * 5_000
    submit_repo = FakeRepository()
    submit_driver = FakeDriver(
        submission=TaskSubmission(
            remote_task_id="remote-1",
            snapshot=TaskSnapshot(status=TaskStatus.FAILED, error=oversized_error),
        )
    )
    submit_registry = McpTaskDriverRegistry()
    submit_registry.register("fake", submit_driver)
    submit_service = McpTaskService(
        repository=submit_repo,
        drivers=submit_registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await submit_service.submit(
        driver_name="fake",
        request=TaskSubmitRequest(
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            tool_call_id="call-1",
            server_name="reports",
            task_name="Generate report",
            arguments={},
        ),
    )

    assert submit_repo.created[0]["error"] == oversized_error[:4_000]

    poll_repo = FakeRepository([_claimed_row()])
    poll_registry = McpTaskDriverRegistry()
    poll_registry.register(
        "fake",
        FakeDriver([TaskSnapshot(status=TaskStatus.FAILED, error=oversized_error)]),
    )
    poll_service = McpTaskService(
        repository=poll_repo,
        drivers=poll_registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await poll_service.run_once(now=datetime.now(UTC))

    _, applied = poll_repo.applied[0]
    assert applied["error"] == oversized_error[:4_000]


@pytest.mark.asyncio
async def test_oversized_input_required_payload_terminalizes_without_persisting_it():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register(
        "fake",
        FakeDriver(
            [
                TaskSnapshot(
                    status=TaskStatus.INPUT_REQUIRED,
                    input_required={"prompt": "x" * 65_536},
                )
            ]
        ),
    )
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    assert repo.released == []
    _, applied = repo.applied[0]
    assert applied["status"] == "failed"
    assert applied["input_required"] is None
    assert "input_required payload exceeds the 65536-byte limit" in applied["error"]
    assert applied["next_poll_at"] is None


@pytest.mark.asyncio
async def test_oversized_result_stores_preview_without_invalid_truncated_json():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register(
        "fake",
        FakeDriver(
            [
                TaskSnapshot(
                    status=TaskStatus.COMPLETED,
                    result={"report": "x" * 200},
                    result_artifact={"uri": "s3://reports/1.json", "mime_type": "application/json"},
                )
            ]
        ),
    )
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        max_result_bytes=64,
        result_preview_max_chars=24,
    )

    await service.run_once(now=datetime.now(UTC))

    _, applied = repo.applied[0]
    assert applied["result"] is None
    assert len(applied["result_preview"]) == 24
    assert applied["result_truncated"] is True
    assert applied["result_artifact"] == {
        "uri": "s3://reports/1.json",
        "mime_type": "application/json",
    }


@pytest.mark.asyncio
async def test_oversized_result_artifact_terminalizes_without_persisting_it():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register(
        "fake",
        FakeDriver(
            [
                TaskSnapshot(
                    status=TaskStatus.COMPLETED,
                    result_artifact={
                        "uri": "https://example.test/" + "x" * 65_536,
                        "mime_type": "application/json",
                    },
                )
            ]
        ),
    )
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    assert repo.released == []
    _, applied = repo.applied[0]
    assert applied["status"] == "failed"
    assert applied["result_artifact"] is None
    assert "result_artifact payload exceeds the 65536-byte limit" in applied["error"]


@pytest.mark.asyncio
async def test_non_json_numeric_result_is_a_permanent_protocol_failure():
    repo = FakeRepository([_claimed_row()])
    registry = McpTaskDriverRegistry()
    registry.register(
        "fake",
        FakeDriver(
            [
                TaskSnapshot(
                    status=TaskStatus.COMPLETED,
                    result={"score": float("nan")},
                )
            ]
        ),
    )
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.run_once(now=datetime.now(UTC))

    assert repo.released == []
    _, applied = repo.applied[0]
    assert applied["status"] == "failed"
    assert "not valid JSON" in applied["error"]


@pytest.mark.asyncio
async def test_run_once_releases_claim_when_driver_is_missing_or_fails():
    rows = [_claimed_row(driver_name="missing"), {**_claimed_row(), "id": "task-2", "remote_task_id": "remote-2", "driver_name": "broken"}]
    repo = FakeRepository(rows)
    registry = McpTaskDriverRegistry()
    registry.register("broken", FakeDriver(error=RuntimeError("network down")))
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    now = datetime.now(UTC)

    await service.run_once(now=now)

    released = {task_id: update for task_id, update in repo.released}
    assert "No MCP task driver registered" in released["task-1"]["error"]
    assert released["task-2"]["error"] == "network down"
    assert released["task-1"]["next_poll_at"] == now + timedelta(seconds=5)
    assert released["task-2"]["next_poll_at"] > now + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_run_once_isolates_unexpected_failure_to_its_claimed_task(caplog):
    rows = [_claimed_row(), {**_claimed_row(), "id": "task-2", "remote_task_id": "remote-2"}]
    repo = FailingApplyRepository(rows)
    driver = FakeDriver(
        [
            TaskSnapshot(status=TaskStatus.COMPLETED, result={"report": "first"}),
            TaskSnapshot(status=TaskStatus.COMPLETED, result={"report": "second"}),
        ]
    )
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    with caplog.at_level(logging.ERROR):
        await service.run_once(now=datetime.now(UTC))

    assert [task_id for task_id, _update in repo.applied] == ["task-2"]
    assert "task_id=task-1" in caplog.text
    assert "database unavailable" in caplog.text


@pytest.mark.asyncio
async def test_start_runs_recovery_poll_immediately_and_stop_is_clean():
    repo = FakeRepository([])
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.start()
    for _ in range(20):
        if repo.claimed:
            break
        await __import__("asyncio").sleep(0)
    await service.stop()

    assert repo.claimed is True


@pytest.mark.asyncio
async def test_stop_cancels_a_hung_driver_poll():
    repo = FakeRepository([_claimed_row()])
    driver = HangingDriver()
    registry = McpTaskDriverRegistry()
    registry.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.start()
    await asyncio.wait_for(driver.started.wait(), timeout=1)
    await asyncio.wait_for(service.stop(), timeout=1)

    assert driver.cancelled is True


@pytest.mark.asyncio
async def test_stop_callers_share_deadline_and_log_one_timeout(monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    clock = [0.0]
    wait_timeouts = []
    wait_started = [asyncio.Event(), asyncio.Event()]
    release_wait = asyncio.Event()

    async def fake_wait(_tasks, *, timeout):
        wait_timeouts.append(timeout)
        wait_started[len(wait_timeouts) - 1].set()
        if len(wait_timeouts) == 1:
            # The second caller arrives 40ms into the first caller's budget.
            clock[0] = 0.04
        await release_wait.wait()
        return set(), set()

    monkeypatch.setattr(service_module.asyncio, "wait", fake_wait)
    monkeypatch.setattr(
        service_module.asyncio,
        "get_running_loop",
        lambda: SimpleNamespace(time=lambda: clock[0]),
    )

    poller_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish = asyncio.Event()
    cancel_count = 0

    async def stubborn_poller():
        nonlocal cancel_count
        poller_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancel_count += 1
            cleanup_started.set()
            await finish.wait()

    service = McpTaskService(
        repository=FakeRepository(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    monkeypatch.setattr(service, "_run_loop", stubborn_poller)

    await service.start()
    await poller_started.wait()
    poller = service._task
    assert poller is not None
    first_stop = second_stop = None

    try:
        with caplog.at_level(logging.WARNING):
            first_stop = asyncio.create_task(service.stop())
            await wait_started[0].wait()
            await cleanup_started.wait()

            second_stop = asyncio.create_task(service.stop())
            await wait_started[1].wait()

            assert wait_timeouts == pytest.approx([0.05, 0.01])
            release_wait.set()
            await asyncio.gather(first_stop, second_stop)

        assert cancel_count == 1
        assert sum("Timed out after" in record.getMessage() for record in caplog.records) == 1
    finally:
        release_wait.set()
        if first_stop is not None and not first_stop.done():
            await first_stop
        if second_stop is not None and not second_stop.done():
            await second_stop
        finish.set()
        await poller


@pytest.mark.asyncio
async def test_poller_done_clears_stop_state_and_ignores_stale_callback(monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    clock = [0.0]
    wait_timeouts = []
    wait_started = [asyncio.Event(), asyncio.Event()]
    release_wait = [asyncio.Event(), asyncio.Event()]

    async def fake_wait(_tasks, *, timeout):
        index = len(wait_timeouts)
        wait_timeouts.append(timeout)
        wait_started[index].set()
        await release_wait[index].wait()
        return set(), set()

    monkeypatch.setattr(service_module.asyncio, "wait", fake_wait)
    monkeypatch.setattr(
        service_module.asyncio,
        "get_running_loop",
        lambda: SimpleNamespace(time=lambda: clock[0]),
    )

    first_started = asyncio.Event()
    first_finish = asyncio.Event()
    second_started = asyncio.Event()
    second_finish = asyncio.Event()

    async def first_poller():
        first_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await first_finish.wait()

    async def second_poller():
        second_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await second_finish.wait()

    pollers = iter((first_poller, second_poller))

    async def run_loop():
        await next(pollers)()

    service = McpTaskService(
        repository=FakeRepository(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    monkeypatch.setattr(service, "_run_loop", run_loop)

    await service.start()
    await first_started.wait()
    first_task = service._task
    assert first_task is not None

    with caplog.at_level(logging.WARNING):
        first_stop = asyncio.create_task(service.stop())
        await wait_started[0].wait()
        release_wait[0].set()
        await first_stop

        assert service._stop_deadline == pytest.approx(0.05)
        assert service._stop_timeout_logged is True

        first_finish.set()
        await first_task
        await asyncio.sleep(0)
        assert service._task is None
        assert service._stopping_task is None
        assert service._stop_deadline is None
        assert service._stop_timeout_logged is False

        clock[0] = 10.0
        await service.start()
        await second_started.wait()
        second_task = service._task
        assert second_task is not None

        second_stop = asyncio.create_task(service.stop())
        await wait_started[1].wait()
        assert wait_timeouts == pytest.approx([0.05, 0.05])

        # A callback from the completed poller must not clear the new episode.
        service._poller_done(first_task)
        assert service._task is second_task
        assert service._stopping_task is second_task
        assert service._stop_deadline == pytest.approx(10.05)
        assert service._stop_timeout_logged is False

        release_wait[1].set()
        await second_stop
        assert service._stop_timeout_logged is True

    second_finish.set()
    await second_task
    await asyncio.sleep(0)

    assert service._task is None
    assert service._stopping_task is None
    assert service._stop_deadline is None
    assert service._stop_timeout_logged is False
    assert sum("Timed out after" in record.getMessage() for record in caplog.records) == 2


@pytest.mark.asyncio
async def test_stop_returns_with_timed_out_poller_and_start_does_not_overlap(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    poller_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish = asyncio.Event()

    async def stubborn_poller():
        poller_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cleanup_started.set()
            try:
                await finish.wait()
            except asyncio.CancelledError:
                # Make a second poller cancellation observable while keeping
                # the test cleanup deterministic.
                return

    service = McpTaskService(
        repository=FakeRepository(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    monkeypatch.setattr(service, "_run_loop", stubborn_poller)

    await service.start()
    await poller_started.wait()
    poller = service._task
    assert poller is not None

    try:
        await asyncio.wait_for(service.stop(), timeout=0.2)
        await cleanup_started.wait()

        assert service._task is poller
        assert not poller.done()

        await service.start()
        assert service._task is poller

        finish.set()
        await asyncio.wait_for(poller, timeout=0.2)
        await asyncio.sleep(0)
        assert service._task is None
    finally:
        finish.set()
        if not poller.done():
            await asyncio.wait_for(poller, timeout=0.2)


@pytest.mark.asyncio
async def test_stop_caller_cancellation_is_bounded_and_does_not_recancel_poller(monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    poller_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish = asyncio.Event()
    cancellation_count = 0

    async def stubborn_poller():
        nonlocal cancellation_count
        poller_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_count += 1
            cleanup_started.set()
        while not finish.is_set():
            try:
                await finish.wait()
            except asyncio.CancelledError:
                cancellation_count += 1

    service = McpTaskService(
        repository=FakeRepository(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    monkeypatch.setattr(service, "_run_loop", stubborn_poller)

    await service.start()
    await poller_started.wait()
    poller = service._task
    assert poller is not None
    caller = asyncio.create_task(service.stop())
    await cleanup_started.wait()

    try:
        caller.cancel()
        await asyncio.sleep(0)
        caller.cancel()

        with caplog.at_level(logging.WARNING):
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(caller), timeout=0.2)

        assert cancellation_count == 1
        assert service._task is poller
        assert not poller.done()
        assert "cleanup continues in the background" in caplog.text

        await service.start()
        assert service._task is poller

        await service.stop()
        assert cancellation_count == 1
        assert service._task is poller

        finish.set()
        await asyncio.wait_for(poller, timeout=0.2)
        await asyncio.sleep(0)
        assert service._task is None
    finally:
        finish.set()
        if not poller.done():
            await asyncio.wait_for(poller, timeout=0.2)
        if not caller.done():
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller


@pytest.mark.asyncio
async def test_finished_poller_failure_is_logged_and_clears_task(monkeypatch, caplog):
    poller_started = asyncio.Event()
    fail = asyncio.Event()

    async def failing_poller():
        poller_started.set()
        await fail.wait()
        raise RuntimeError("poller cleanup failed")

    service = McpTaskService(
        repository=FakeRepository(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    monkeypatch.setattr(service, "_run_loop", failing_poller)

    with caplog.at_level(logging.ERROR):
        await service.start()
        await poller_started.wait()
        poller = service._task
        assert poller is not None
        fail.set()
        await asyncio.wait({poller})
        await asyncio.sleep(0)

    assert service._task is None
    assert "MCP task poller failed" in caplog.text
    assert "poller cleanup failed" in caplog.text


class CancellationBlockingApplyRepo(FakeRepository):
    """``apply_cancel_snapshot`` blocks so the caller can be cancelled mid-flight."""

    def __init__(self, *, release_error: Exception | None = None, block_release: bool = False):
        super().__init__()
        self.apply_started = asyncio.Event()
        self.release_cancel_calls = []
        self.release_error = release_error
        self.block_release = block_release
        self.release_started = asyncio.Event()
        self.finish_release = asyncio.Event()
        self.release_completed = False
        self.release_interrupted = False

    async def apply_cancel_snapshot(self, task_id, **kwargs):
        self.applied.append((task_id, kwargs))
        self.apply_started.set()
        await asyncio.Event().wait()

    async def release_cancel_claim(self, task_id, **kwargs):
        self.release_cancel_calls.append((task_id, kwargs))
        self.release_started.set()
        if self.block_release:
            try:
                await self.finish_release.wait()
            except asyncio.CancelledError:
                self.release_interrupted = True
                raise
        if self.release_error is not None:
            raise self.release_error
        self.release_completed = True
        return True


def test_cancel_one_releases_claim_when_cancelled():
    """A cancel that lands mid-``_cancel_one`` must still release the claim."""
    repo = CancellationBlockingApplyRepo()
    driver = FakeDriver()  # cancel() returns a CANCELLED snapshot
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    record = _claimed_row()

    async def main():
        task = asyncio.create_task(service._cancel_one(record))
        await repo.apply_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert repo.release_cancel_calls
        assert repo.release_cancel_calls[0][0] == record["id"]

    asyncio.run(main())


@pytest.mark.asyncio
async def test_cancel_one_preserves_cancellation_when_release_fails(caplog):
    repo = CancellationBlockingApplyRepo(release_error=RuntimeError("release unavailable"))
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver())
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._cancel_one(_claimed_row()))
    await repo.apply_started.wait()
    task.cancel()

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await task

    assert repo.release_cancel_calls
    assert "release unavailable" in caplog.text


@pytest.mark.asyncio
async def test_cancel_one_repeated_cancellation_does_not_interrupt_release():
    repo = CancellationBlockingApplyRepo(block_release=True)
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver())
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._cancel_one(_claimed_row()))
    await repo.apply_started.wait()
    task.cancel()
    await repo.release_started.wait()
    task.cancel()
    repo.finish_release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.release_completed is True
    assert repo.release_interrupted is False


@pytest.mark.asyncio
async def test_cancel_one_failure_release_retries_after_caller_cancellation():
    repo = CancellationBlockingApplyRepo(block_release=True)
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(cancel_error=RuntimeError("remote unavailable")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._cancel_one(_claimed_row()))
    await repo.release_started.wait()
    task.cancel()
    repo.finish_release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.release_completed is True
    assert repo.release_interrupted is True
    assert len(repo.release_cancel_calls) == 2


class CancelAfterClaimRepository(FakeRepository):
    def __init__(self, *, phase: str):
        super().__init__()
        self.phase = phase
        self.caller_task = None
        self.cancel_releases = []
        self.notification_claim_releases = []
        self.notification_lease_releases = []

    def _cancel_caller(self):
        task = self.caller_task
        assert task is not None
        task.cancel()

    async def claim_cancel_requests(self, **_kwargs):
        if self.phase != "cancel":
            return []
        self._cancel_caller()
        return [_claimed_row()]

    async def claim_due_tasks(self, **_kwargs):
        if self.phase != "poll":
            return []
        self._cancel_caller()
        return [_claimed_row()]

    async def claim_notification_work(self, **_kwargs):
        if not self.phase.startswith("notification_"):
            return []
        status = self.phase.removeprefix("notification_")
        self._cancel_caller()
        return [
            {
                **_claimed_row(),
                "notification_status": status,
                "notification_run_id": "notify-run-1" if status == "dispatched" else None,
                "dispatch_version": 2,
                "dispatch_attempt": 0,
                "dispatch_event": {"status": "completed"},
            }
        ]

    async def release_cancel_claim(self, task_id, **kwargs):
        self.cancel_releases.append((task_id, kwargs))
        return True

    async def release_notification_claim(self, task_id, **kwargs):
        self.notification_claim_releases.append((task_id, kwargs))
        return True

    async def release_notification_lease(self, task_id, **kwargs):
        self.notification_lease_releases.append((task_id, kwargs))
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "released_attr"),
    [
        ("poll", "released"),
        ("cancel", "cancel_releases"),
        ("notification_claimed", "notification_claim_releases"),
        ("notification_dispatched", "notification_lease_releases"),
    ],
)
async def test_cancellation_immediately_after_claim_releases_every_record(phase, released_attr):
    repo = CancelAfterClaimRepository(phase=phase)
    repo.caller_task = asyncio.current_task()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver())
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.run_once(now=datetime.now(UTC))

    assert [task_id for task_id, _kwargs in getattr(repo, released_attr)] == ["task-1"]


class DurableClaimHandoffRepository(CancelAfterClaimRepository):
    def __init__(self, *, phase: str):
        super().__init__(phase=phase)
        self.claim_committed = asyncio.Event()
        self.allow_claim_return = asyncio.Event()
        self.claim_cancelled = False

    async def _return_after_commit(self, records):
        self.claim_committed.set()
        try:
            await self.allow_claim_return.wait()
        except asyncio.CancelledError:
            self.claim_cancelled = True
            raise
        return records

    async def claim_cancel_requests(self, **_kwargs):
        if self.phase != "cancel":
            return []
        return await self._return_after_commit([_claimed_row()])

    async def claim_due_tasks(self, **_kwargs):
        if self.phase != "poll":
            return []
        return await self._return_after_commit([_claimed_row()])

    async def claim_notification_work(self, **_kwargs):
        if not self.phase.startswith("notification_"):
            return []
        status = self.phase.removeprefix("notification_")
        return await self._return_after_commit(
            [
                {
                    **_claimed_row(),
                    "notification_status": status,
                    "notification_run_id": "notify-run-1" if status == "dispatched" else None,
                    "dispatch_version": 2,
                    "dispatch_attempt": 0,
                    "dispatch_event": {"status": "completed"},
                }
            ]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "released_attr"),
    [
        ("poll", "released"),
        ("cancel", "cancel_releases"),
        ("notification_claimed", "notification_claim_releases"),
        ("notification_dispatched", "notification_lease_releases"),
    ],
)
async def test_cancellation_during_durable_claim_handoff_drains_and_releases(phase, released_attr):
    repo = DurableClaimHandoffRepository(phase=phase)
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(),
    )

    task = asyncio.create_task(service.run_once(now=datetime.now(UTC)))
    await repo.claim_committed.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    repo.allow_claim_return.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.claim_cancelled is False
    assert [task_id for task_id, _kwargs in getattr(repo, released_attr)] == ["task-1"]


class NotificationFallbackCancellationRepo(FakeRepository):
    def __init__(self):
        super().__init__()
        self.release_started = asyncio.Event()
        self.finish_release = asyncio.Event()
        self.release_calls = []
        self.release_interrupted = False
        self.release_completed = False

    async def claim_cancel_requests(self, **_kwargs):
        return []

    async def claim_due_tasks(self, **_kwargs):
        return []

    async def claim_notification_work(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [
            {
                **_claimed_row(),
                "notification_status": "dispatched",
                "notification_run_id": "notify-run-1",
                "dispatch_version": 2,
            }
        ]

    async def release_notification_lease(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        self.release_started.set()
        try:
            await self.finish_release.wait()
        except asyncio.CancelledError:
            self.release_interrupted = True
            raise
        self.release_completed = True
        return True


@pytest.mark.asyncio
async def test_notification_batch_fallback_release_survives_caller_cancellation():
    repo = NotificationFallbackCancellationRepo()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(side_effect=RuntimeError("run store unavailable")),
    )

    task = asyncio.create_task(service._run_notifications(now=datetime.now(UTC)))
    await repo.release_started.wait()
    task.cancel()
    repo.finish_release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.release_interrupted is False
    assert repo.release_completed is True
    assert len(repo.release_calls) == 1


class NotificationPersistenceRepo:
    def __init__(self, *, release_error: BaseException | None = None):
        self.claimed = False
        self.mark_started = asyncio.Event()
        self.release_finished = asyncio.Event()
        self.release_calls = []
        self.release_error = release_error

    async def claim_due_tasks(self, **_kwargs):
        return []

    async def claim_notification_work(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [
            {
                **_claimed_row(),
                "notification_status": "claimed",
                "dispatch_version": 2,
                "dispatch_attempt": 0,
                "dispatch_event": {"status": "completed"},
            }
        ]

    async def mark_notification_dispatched(self, *_args, **_kwargs):
        self.mark_started.set()
        await asyncio.Event().wait()

    async def release_notification_claim(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        if self.release_error is not None:
            self.release_finished.set()
            raise self.release_error
        return True

    async def release_notification_lease(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        if self.release_error is not None:
            self.release_finished.set()
            raise self.release_error
        return True


@pytest.mark.asyncio
async def test_stop_releases_notification_claim_during_dispatched_persistence():
    repo = NotificationPersistenceRepo()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )

    await service.start()
    await asyncio.wait_for(repo.mark_started.wait(), timeout=1)
    await asyncio.wait_for(service.stop(), timeout=1)

    assert repo.release_calls
    assert {task_id for task_id, _kwargs in repo.release_calls} == {"task-1"}


@pytest.mark.asyncio
async def test_notification_cancellation_preserves_cancelled_error_when_release_fails(caplog):
    repo = NotificationPersistenceRepo(release_error=RuntimeError("notification release unavailable"))
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=AsyncMock(return_value=SimpleNamespace(assistant_id="lead_agent")),
    )
    record = (await repo.claim_notification_work())[0]

    task = asyncio.create_task(service._notify_one(record, now=datetime.now(UTC)))
    await repo.mark_started.wait()
    task.cancel()

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await task

    assert repo.release_calls
    assert "notification release unavailable" in caplog.text


class NotificationFailureReleaseRepo(NotificationPersistenceRepo):
    async def claim_notification_work(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [
            {
                **_claimed_row(),
                "notification_status": "dispatched",
                "notification_run_id": "notify-run-1",
                "dispatch_version": 2,
            }
        ]


@pytest.mark.asyncio
async def test_notification_failure_release_self_cancellation_does_not_kill_poller(caplog):
    repo = NotificationFailureReleaseRepo(release_error=asyncio.CancelledError("notification release cancelled itself"))
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=AsyncMock(side_effect=RuntimeError("run store unavailable")),
    )

    try:
        with caplog.at_level(logging.ERROR):
            await service.start()
            await repo.release_finished.wait()
            async with asyncio.timeout(1):
                while not any("MCP task batch release failed" in record.message for record in caplog.records):
                    await asyncio.sleep(0)

        assert service._task is not None
        assert not service._task.done()
        assert [task_id for task_id, _kwargs in repo.release_calls] == ["task-1"]
        release_logs = [record for record in caplog.records if "MCP task batch release failed" in record.message]
        assert len(release_logs) == 1
        assert "release notification failure" in release_logs[0].message
        assert "task_id=task-1" in release_logs[0].message
    finally:
        await service.stop()


class SameTickNotificationFailureReleaseRepo(NotificationFailureReleaseRepo):
    def __init__(self):
        super().__init__(release_error=asyncio.CancelledError("notification release cancelled itself"))
        self.caller_task = None

    async def release_notification_lease(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        assert self.caller_task is not None
        self.caller_task.cancel("same tick notification cancellation")
        self.release_finished.set()
        raise asyncio.CancelledError("notification release cancelled itself")


@pytest.mark.asyncio
async def test_notification_failure_release_same_tick_outer_cancellation_wins(caplog):
    repo = SameTickNotificationFailureReleaseRepo()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=AsyncMock(side_effect=RuntimeError("run store unavailable")),
    )
    caller = asyncio.create_task(service._run_notifications(now=datetime.now(UTC)))
    repo.caller_task = caller

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError) as caught:
        await caller

    assert caught.value.args == ("same tick notification cancellation",)
    assert repo.release_finished.is_set()
    assert [task_id for task_id, _kwargs in repo.release_calls] == ["task-1"]


@pytest.mark.asyncio
async def test_notification_cancellation_during_source_run_lookup_releases_claim():
    lookup_started = asyncio.Event()

    async def get_run(*_args, **_kwargs):
        lookup_started.set()
        await asyncio.Event().wait()

    repo = SimpleNamespace(release_notification_claim=AsyncMock(return_value=True))
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(return_value={"run_id": "notify-run-1"}),
        get_run=get_run,
    )
    record = {
        **_claimed_row(),
        "notification_status": "claimed",
        "dispatch_version": 2,
        "dispatch_attempt": 0,
        "dispatch_event": {"status": "completed"},
    }

    task = asyncio.create_task(service._notify_one(record, now=datetime.now(UTC)))
    await lookup_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    repo.release_notification_claim.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatched_notification_cancellation_preserves_phase_when_releasing_lease():
    lookup_started = asyncio.Event()

    async def get_run(*_args, **_kwargs):
        lookup_started.set()
        await asyncio.Event().wait()

    repo = SimpleNamespace(
        release_notification_claim=AsyncMock(return_value=True),
        release_notification_lease=AsyncMock(return_value=True),
    )
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=get_run,
    )
    record = {
        **_claimed_row(),
        "notification_status": "dispatched",
        "notification_run_id": "notify-run-1",
        "dispatch_version": 2,
    }

    task = asyncio.create_task(service._notify_one(record, now=datetime.now(UTC)))
    await lookup_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    repo.release_notification_lease.assert_awaited_once()
    repo.release_notification_claim.assert_not_awaited()


class PollPersistenceRepo(FakeRepository):
    def __init__(self, *, release_error: Exception | None = None):
        super().__init__([_claimed_row()])
        self.apply_started = asyncio.Event()
        self.release_error = release_error
        self.cancelled_releases = []

    async def apply_snapshot(self, task_id, **kwargs):
        self.applied.append((task_id, kwargs))
        self.apply_started.set()
        await asyncio.Event().wait()

    async def release_claim(self, task_id, **kwargs):
        self.released.append((task_id, kwargs))
        if self.release_error is not None:
            raise self.release_error
        return True

    async def release_poll_claim_after_cancellation(self, task_id, **kwargs):
        self.cancelled_releases.append((task_id, kwargs))
        if self.release_error is not None:
            raise self.release_error
        return True


@pytest.mark.asyncio
async def test_stop_releases_poll_claim_during_snapshot_persistence():
    repo = PollPersistenceRepo()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(snapshots=[TaskSnapshot(status=TaskStatus.WORKING)]))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=60,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service.start()
    await asyncio.wait_for(repo.apply_started.wait(), timeout=1)
    await asyncio.wait_for(service.stop(), timeout=1)

    assert repo.cancelled_releases
    assert {task_id for task_id, _kwargs in repo.cancelled_releases} == {"task-1"}
    assert repo.released == []


@pytest.mark.asyncio
async def test_poll_cancellation_releases_only_the_current_poll_lease():
    repo = PollPersistenceRepo()
    driver = HangingDriver()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._poll_one(_claimed_row(), now=datetime.now(UTC)))
    await driver.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert repo.cancelled_releases == [("task-1", {"lease_owner": service._lease_owner, "lease_token": "lease-token-1"})]
    assert repo.released == []


@pytest.mark.asyncio
async def test_poll_cancellation_preserves_cancelled_error_when_release_fails(caplog):
    repo = PollPersistenceRepo(release_error=RuntimeError("poll release unavailable"))
    driver = HangingDriver()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._poll_one(_claimed_row(), now=datetime.now(UTC)))
    await driver.started.wait()
    task.cancel()

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await task

    assert repo.cancelled_releases
    assert repo.released == []
    assert "poll release unavailable" in caplog.text


async def _wait_for_compensation_tasks_to_clear(service: McpTaskService) -> None:
    async with asyncio.timeout(1):
        while service._compensation_tasks:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_settled_cancellation_compensation_can_stop_without_losing_release():
    release_started = asyncio.Event()
    release_gate = asyncio.Event()

    async def release():
        release_started.set()
        await release_gate.wait()

    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(
        service._drain_cancellation_compensation(
            release(),
            action="release late claim",
            task_id="task-1",
            settle=True,
        )
    )
    await release_started.wait()
    caller.cancel("service shutdown")

    try:
        await asyncio.sleep(0)
        assert caller.done()
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        assert caught.value.args == ("service shutdown",)
        assert len(service._compensation_tasks) == 1

        release_gate.set()
        await _wait_for_compensation_tasks_to_clear(service)
    finally:
        release_gate.set()
        if not caller.done():
            await caller
        await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
async def test_cancelled_hung_claim_returns_then_releases_delayed_result(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    claim_started = asyncio.Event()
    claim_gate = asyncio.Event()
    release_calls = []

    async def claim():
        claim_started.set()
        await claim_gate.wait()
        return [_claimed_row()]

    async def release(record, *, settle=False):
        assert settle is True
        release_calls.append(record["id"])

    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(
        service._claim_with_cancellation_release(
            claim,
            phase="probe",
            action="probe claim",
            release=release,
        )
    )
    await claim_started.wait()
    caller.cancel()

    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(caller), timeout=0.2)

        assert release_calls == []
        assert len(service._compensation_tasks) == 1

        claim_gate.set()
        await _wait_for_compensation_tasks_to_clear(service)

        assert release_calls == ["task-1"]
        assert not service._compensation_tasks
    finally:
        claim_gate.set()
        if not caller.done():
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(caller, timeout=0.2)
        await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
async def test_single_flight_claim_releases_late_uncancelled_claim(phase, monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)

    class BlockingClaimRepository:
        def __init__(self):
            self.claim_calls = {"poll": 0, "cancel": 0, "notification": 0}
            self.claim_started = asyncio.Event()
            self.claim_gate = asyncio.Event()
            self.released: list[tuple[str, str, dict]] = []

        async def _claim(self, claim_phase):
            self.claim_calls[claim_phase] += 1
            self.claim_started.set()
            await self.claim_gate.wait()
            return [{**_claimed_row(), "notification_status": "pending"}]

        async def claim_due_tasks(self, **_kwargs):
            return await self._claim("poll")

        async def claim_cancel_requests(self, **_kwargs):
            return await self._claim("cancel")

        async def claim_notification_work(self, **_kwargs):
            return await self._claim("notification")

        async def release_poll_claim_after_cancellation(self, task_id, **kwargs):
            self.released.append(("poll", task_id, kwargs))
            return True

        async def release_cancel_claim(self, task_id, **kwargs):
            self.released.append(("cancel", task_id, kwargs))
            return True

        async def release_notification_claim(self, task_id, **kwargs):
            self.released.append(("notification", task_id, kwargs))
            return True

    repo = BlockingClaimRepository()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    claim_factories = {
        "poll": lambda: repo.claim_due_tasks(),
        "cancel": lambda: repo.claim_cancel_requests(),
        "notification": lambda: repo.claim_notification_work(),
    }
    releases = {
        "poll": service._release_poll_after_cancellation,
        "cancel": service._release_cancel_after_cancellation,
        "notification": service._release_notification_after_cancellation,
    }

    async def claim_once():
        return await service._claim_with_cancellation_release(
            claim_factories[phase],
            phase=phase,
            action=f"{phase} claim",
            release=releases[phase],
        )

    try:
        assert await claim_once() == []
        await repo.claim_started.wait()
        assert await claim_once() == []
        assert await claim_once() == []
        assert repo.claim_calls[phase] == 1
        assert list(service._claim_owners) == [phase]

        repo.claim_gate.set()
        async with asyncio.timeout(0.2):
            while service._claim_owners:
                await asyncio.sleep(0)

        assert [(released_phase, task_id) for released_phase, task_id, _ in repo.released] == [(phase, "task-1")]
        assert repo.released[0][2]["lease_owner"] == service._lease_owner
        token_key = "notification_lease_token" if phase == "notification" else "lease_token"
        assert repo.released[0][2][token_key] == ("notify-lease-token-1" if phase == "notification" else "lease-token-1")

        claimed = await claim_once()
        assert [record["id"] for record in claimed] == ["task-1"]
        assert repo.claim_calls[phase] == 2
        assert not service._claim_owners
    finally:
        repo.claim_gate.set()
        owners = tuple(getattr(service, "_claim_owners", {}).values())
        handoffs = [owner.handoff_task for owner in owners if owner.handoff_task is not None]
        if handoffs:
            await asyncio.gather(*handoffs, return_exceptions=True)


@pytest.mark.asyncio
async def test_single_flight_claim_skip_logs_unresolved_owner(caplog):
    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    claim_task = asyncio.get_running_loop().create_future()
    service._claim_owners["poll"] = service_module._ClaimOwner(claim_task=claim_task)

    try:
        with caplog.at_level(logging.WARNING):
            result = await service._claim_with_cancellation_release(
                lambda: pytest.fail("an unresolved owner must suppress a new claim"),
                phase="poll",
                action="poll claim",
                release=AsyncMock(),
            )

        assert result == []
        assert "previous claim/handoff is still unresolved" in caplog.text
    finally:
        claim_task.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
async def test_single_flight_claim_keeps_owner_until_late_release_settles(phase, monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)

    class BlockingClaimAndReleaseRepository:
        def __init__(self):
            self.claim_calls = {"poll": 0, "cancel": 0, "notification": 0}
            self.claim_started = asyncio.Event()
            self.claim_gate = asyncio.Event()
            self.release_started = asyncio.Event()
            self.release_gate = asyncio.Event()

        async def _claim(self, claim_phase):
            self.claim_calls[claim_phase] += 1
            self.claim_started.set()
            await self.claim_gate.wait()
            return [{**_claimed_row(), "notification_status": "pending"}]

        async def claim_due_tasks(self, **_kwargs):
            return await self._claim("poll")

        async def claim_cancel_requests(self, **_kwargs):
            return await self._claim("cancel")

        async def claim_notification_work(self, **_kwargs):
            return await self._claim("notification")

        async def _release(self):
            self.release_started.set()
            await self.release_gate.wait()
            return True

        async def release_poll_claim_after_cancellation(self, _task_id, **_kwargs):
            return await self._release()

        async def release_cancel_claim(self, _task_id, **_kwargs):
            return await self._release()

        async def release_notification_claim(self, _task_id, **_kwargs):
            return await self._release()

    repo = BlockingClaimAndReleaseRepository()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    claim_factories = {
        "poll": lambda: repo.claim_due_tasks(),
        "cancel": lambda: repo.claim_cancel_requests(),
        "notification": lambda: repo.claim_notification_work(),
    }
    releases = {
        "poll": service._release_poll_after_cancellation,
        "cancel": service._release_cancel_after_cancellation,
        "notification": service._release_notification_after_cancellation,
    }

    async def claim_once():
        return await service._claim_with_cancellation_release(
            claim_factories[phase],
            phase=phase,
            action=f"{phase} claim",
            release=releases[phase],
        )

    try:
        assert await claim_once() == []
        await repo.claim_started.wait()

        repo.claim_gate.set()
        await repo.release_started.wait()
        await asyncio.sleep(0.02)

        assert list(service._claim_owners) == [phase]
        assert await claim_once() == []
        assert repo.claim_calls[phase] == 1

        repo.release_gate.set()
        async with asyncio.timeout(0.2):
            while service._claim_owners:
                await asyncio.sleep(0)

        claimed = await claim_once()
        assert [record["id"] for record in claimed] == ["task-1"]
        assert repo.claim_calls[phase] == 2
    finally:
        repo.claim_gate.set()
        repo.release_gate.set()
        owners = tuple(getattr(service, "_claim_owners", {}).values())
        handoffs = [owner.handoff_task for owner in owners if owner.handoff_task is not None]
        if handoffs:
            await asyncio.gather(*handoffs, return_exceptions=True)
        await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
async def test_routine_cancel_release_preserves_existing_diagnostic():
    release = AsyncMock(return_value=True)
    service = McpTaskService(
        repository=SimpleNamespace(release_cancel_claim=release),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service._release_cancel_after_cancellation(
        {
            "id": "task-1",
            "lease_token": "lease-1",
            "last_cancel_error": "remote cancellation failed",
        }
    )

    assert release.await_args.kwargs["error"] == "remote cancellation failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_status", ["pending", "dispatched"])
async def test_routine_notification_release_preserves_existing_diagnostic(notification_status):
    release_claim = AsyncMock(return_value=True)
    release_lease = AsyncMock(return_value=True)
    service = McpTaskService(
        repository=SimpleNamespace(
            release_notification_claim=release_claim,
            release_notification_lease=release_lease,
        ),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    await service._release_notification_after_cancellation(
        {
            "id": "task-1",
            "notification_lease_token": "notify-lease-1",
            "notification_status": notification_status,
            "notification_error": "notification launch failed",
        }
    )

    release = release_lease if notification_status == "dispatched" else release_claim
    assert release.await_args.kwargs["error"] == "notification launch failed"
    assert release.await_args.kwargs.get("count_failure", False) is False


@pytest.mark.asyncio
async def test_batch_release_starts_sibling_when_first_release_hangs():
    first_release_gate = asyncio.Event()
    second_release_completed = asyncio.Event()
    release_calls = []

    async def release(record):
        release_calls.append(record["id"])
        if record["id"] == "first":
            await first_release_gate.wait()
        else:
            second_release_completed.set()

    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    batch = asyncio.create_task(
        service._release_claimed_records(
            [
                {**_claimed_row(), "id": "first"},
                {**_claimed_row(), "id": "second"},
            ],
            release=release,
        )
    )

    try:
        await asyncio.wait_for(second_release_completed.wait(), timeout=0.2)
        assert release_calls == ["first", "second"]
    finally:
        first_release_gate.set()
        await asyncio.wait_for(batch, timeout=0.2)


@pytest.mark.asyncio
async def test_batch_release_logs_cancelled_record_and_finishes_sibling(caplog):
    sibling_completed = asyncio.Event()
    release_calls = []

    async def release(record):
        release_calls.append(record["id"])
        if record["id"] == "cancelled":
            raise asyncio.CancelledError("release cancelled")
        sibling_completed.set()

    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    with caplog.at_level(logging.ERROR):
        await service._release_claimed_records(
            [
                {**_claimed_row(), "id": "cancelled"},
                {**_claimed_row(), "id": "sibling"},
            ],
            release=release,
        )

    assert sibling_completed.is_set()
    assert release_calls.count("cancelled") == 1
    assert release_calls.count("sibling") == 1
    cancellations = [record for record in caplog.records if "MCP task claim release was cancelled" in record.getMessage()]
    assert len(cancellations) == 1
    assert "task_id=cancelled" in cancellations[0].getMessage()


@pytest.mark.asyncio
async def test_duplicate_compensation_registration_logs_failure_once(caplog):
    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    compensation = asyncio.get_running_loop().create_future()

    with caplog.at_level(logging.ERROR):
        service._track_compensation_task(compensation, action="release poll claim", task_id="task-1")
        service._track_compensation_task(compensation, action="release poll claim", task_id="task-1")
        assert service._compensation_tasks == {compensation}

        compensation.set_exception(RuntimeError("release remained unavailable"))
        await _wait_for_compensation_tasks_to_clear(service)

    failures = [record for record in caplog.records if "MCP task cancellation operation failed" in record.getMessage()]
    assert len(failures) == 1
    assert "release remained unavailable" in failures[0].getMessage()


@pytest.mark.asyncio
async def test_hung_cancellation_compensation_transfers_to_background(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    release_started = asyncio.Event()
    release_gate = asyncio.Event()
    release_calls = []

    async def release_poll_claim_after_cancellation(task_id, **_kwargs):
        release_calls.append(task_id)
        release_started.set()
        await release_gate.wait()
        return True

    driver = HangingDriver()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=SimpleNamespace(release_poll_claim_after_cancellation=release_poll_claim_after_cancellation),
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._poll_one(_claimed_row(), now=datetime.now(UTC)))
    await driver.started.wait()
    task.cancel()
    await release_started.wait()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)

    assert release_calls == ["task-1"]
    assert len(service._compensation_tasks) == 1

    release_gate.set()
    await _wait_for_compensation_tasks_to_clear(service)

    assert not service._compensation_tasks


@pytest.mark.asyncio
async def test_background_compensation_failure_is_consumed(monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    release_started = asyncio.Event()
    release_gate = asyncio.Event()
    release_calls = []

    async def release_poll_claim_after_cancellation(task_id, **_kwargs):
        release_calls.append(task_id)
        release_started.set()
        await release_gate.wait()
        raise RuntimeError("release remained unavailable")

    driver = HangingDriver()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=SimpleNamespace(release_poll_claim_after_cancellation=release_poll_claim_after_cancellation),
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    task = asyncio.create_task(service._poll_one(_claimed_row(), now=datetime.now(UTC)))
    await driver.started.wait()
    task.cancel()
    await release_started.wait()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)

    assert release_calls == ["task-1"]
    assert len(service._compensation_tasks) == 1

    with caplog.at_level(logging.ERROR):
        release_gate.set()
        await _wait_for_compensation_tasks_to_clear(service)

    failures = [record for record in caplog.records if "MCP task cancellation operation failed" in record.getMessage()]
    assert len(failures) == 1
    assert "release remained unavailable" in failures[0].getMessage()
    assert not service._compensation_tasks


class BatchCancellationRepository(FakeRepository):
    def __init__(self, rows, *, phase="cancel"):
        super().__init__(rows)
        self.phase = phase
        self.cancel_releases = []
        self.caller_task = None

    async def claim_due_tasks(self, **_kwargs):
        if self.phase != "poll":
            return []
        return [dict(row) for row in self.rows]

    async def claim_cancel_requests(self, **_kwargs):
        if self.phase != "cancel":
            return []
        return [dict(row) for row in self.rows]

    async def release_cancel_claim(self, task_id, **kwargs):
        self.cancel_releases.append((task_id, kwargs))
        return True


class OuterCancellingDriver(FakeDriver):
    def __init__(self, *, caller_task, phase):
        super().__init__()
        self.caller_task = caller_task
        self.phase = phase
        self.started = []

    async def _run(self, task):
        self.started.append(task.local_task_id)
        if task.local_task_id != "task-1":
            raise AssertionError("task-2 should be released by the batch fallback")
        self.caller_task.cancel()
        await asyncio.Event().wait()

    async def get_status(self, task):
        return await self._run(task)

    async def cancel(self, task):
        return await self._run(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_batch_outer_cancellation_releases_started_and_never_started_once(phase):
    rows = [
        _claimed_row(),
        {**_claimed_row(), "id": "task-2", "remote_task_id": "remote-2"},
    ]
    repo = BatchCancellationRepository(rows, phase=phase)
    drivers = McpTaskDriverRegistry()
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(service.run_once(now=datetime.now(UTC)) if phase == "poll" else service._run_cancellations(now=datetime.now(UTC)))
    repo.caller_task = caller
    driver = OuterCancellingDriver(caller_task=caller, phase=phase)
    drivers.register("fake", driver)

    with pytest.raises(asyncio.CancelledError):
        await caller

    released = repo.released if phase == "poll" else repo.cancel_releases
    assert sorted(task_id for task_id, _kwargs in released) == ["task-1", "task-2"]
    assert driver.started == ["task-1"]


class SelfCancellingDriver(FakeDriver):
    async def get_status(self, task):
        raise asyncio.CancelledError("child poll cancelled itself")

    async def cancel(self, task):
        raise asyncio.CancelledError("child cancel cancelled itself")


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_batch_child_self_cancellation_releases_once(phase):
    repo = BatchCancellationRepository([_claimed_row()], phase=phase)
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", SelfCancellingDriver())
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    if phase == "poll":
        await service.run_once(now=datetime.now(UTC))
        assert [task_id for task_id, _kwargs in repo.released] == ["task-1"]
    else:
        await service._run_cancellations(now=datetime.now(UTC))
        assert [task_id for task_id, _kwargs in repo.cancel_releases] == ["task-1"]


@pytest.mark.asyncio
async def test_batch_outer_cancellation_logs_unexpected_child_failure_once(caplog):
    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    rows = [
        _claimed_row(),
        {**_claimed_row(), "id": "task-2", "remote_task_id": "remote-2"},
    ]
    child_started = {row["id"]: asyncio.Event() for row in rows}
    release_finished = {row["id"]: asyncio.Event() for row in rows}
    release_calls = []

    async def operation(record):
        child_started[record["id"]].set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise RuntimeError(f"child failed during cancellation handoff ({record['id']})")

    async def release(record):
        release_calls.append(record["id"])
        release_finished[record["id"]].set()

    caller = asyncio.create_task(
        service._run_claimed_batch(
            rows,
            operation=operation,
            release=release,
            action="poll",
        )
    )
    await asyncio.gather(*(event.wait() for event in child_started.values()))
    caller.cancel("outer cancellation")

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await caller

    failures = [record for record in caplog.records if "Unexpected MCP task poll failure" in record.getMessage()]
    assert len(failures) == len(rows)
    for row in rows:
        task_id = row["id"]
        assert release_finished[task_id].is_set()
        assert release_calls.count(task_id) == 1
        matching_failures = [failure for failure in failures if f"task_id={task_id}" in failure.getMessage()]
        assert len(matching_failures) == 1
        assert f"child failed during cancellation handoff ({task_id})" in caplog.text


class SelfCancellingNotificationRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.notification_releases = []

    async def claim_notification_work(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [
            {
                **_claimed_row(),
                "notification_status": "claimed",
                "dispatch_version": 1,
                "dispatch_attempt": 0,
                "dispatch_event": {"status": "completed"},
            }
        ]

    async def release_notification_claim(self, task_id, **kwargs):
        self.notification_releases.append((task_id, kwargs))
        return True


@pytest.mark.asyncio
async def test_notification_child_self_cancellation_releases_once():
    repo = SelfCancellingNotificationRepository()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=asyncio.CancelledError("child notification cancelled itself")),
        get_run=AsyncMock(return_value=None),
    )

    await service._run_notifications(now=datetime.now(UTC))

    assert [task_id for task_id, _kwargs in repo.notification_releases] == ["task-1"]


class BatchNotificationRepository(FakeRepository):
    def __init__(self, rows):
        super().__init__(rows)
        self.notification_releases = []

    async def claim_notification_work(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [dict(row) for row in self.rows]

    async def release_notification_claim(self, task_id, **kwargs):
        self.notification_releases.append((task_id, kwargs))
        return True


@pytest.mark.asyncio
async def test_notification_outer_cancellation_releases_started_and_never_started_once():
    rows = [
        {
            **_claimed_row(),
            "notification_status": "claimed",
            "dispatch_version": 1,
            "dispatch_attempt": 0,
            "dispatch_event": {"status": "completed"},
        },
        {
            **_claimed_row(),
            "id": "task-2",
            "remote_task_id": "remote-2",
            "notification_status": "claimed",
            "dispatch_version": 1,
            "dispatch_attempt": 0,
            "dispatch_event": {"status": "completed"},
        },
    ]
    repo = BatchNotificationRepository(rows)
    caller = None
    release_gate = asyncio.Event()
    launch_calls = []

    async def launch_notification(**kwargs):
        launch_calls.append(kwargs["task_id"])
        if kwargs["task_id"] != "task-1":
            raise AssertionError("task-2 should be released by the batch fallback")
        caller.cancel()
        await release_gate.wait()
        return {"run_id": "notify-run-1"}

    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=launch_notification,
        get_run=AsyncMock(return_value=None),
    )
    caller = asyncio.create_task(service._run_notifications(now=datetime.now(UTC)))

    with pytest.raises(asyncio.CancelledError):
        await caller

    assert sorted(task_id for task_id, _kwargs in repo.notification_releases) == ["task-1", "task-2"]
    assert launch_calls == ["task-1"]
    release_gate.set()


class SuppressingBatchDriver(FakeDriver):
    def __init__(self, *, release_gate):
        super().__init__()
        self.release_gate = release_gate
        self.started = asyncio.Event()
        self.swallowed = asyncio.Event()

    async def _run(self, task):
        if task.local_task_id == "task-1":
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.swallowed.set()
                await self.release_gate.wait()
        if task.local_task_id == "task-1":
            return TaskSnapshot(status=TaskStatus.WORKING)
        return TaskSnapshot(status=TaskStatus.WORKING)

    async def get_status(self, task):
        return await self._run(task)

    async def cancel(self, task):
        return await self._run(task)


def _batch_probe_rows(*, notification=False, count=2):
    rows = []
    for index in range(count):
        row = {
            **_claimed_row(),
            "id": f"task-{index + 1}",
            "remote_task_id": f"remote-{index + 1}",
        }
        if notification:
            row.update(
                notification_status="claimed",
                dispatch_version=1,
                dispatch_attempt=0,
                dispatch_event={"status": "completed"},
            )
        rows.append(row)
    return rows


async def _run_batch_probe(service, phase):
    now = datetime.now(UTC)
    if phase == "poll":
        await service.run_once(now=now)
    elif phase == "cancel":
        await service._run_cancellations(now=now)
    else:
        await service._run_notifications(now=now)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
async def test_outer_cancel_returns_before_suppressing_child_and_releases_all_once(phase, monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    release_gate = asyncio.Event()
    driver = SuppressingBatchDriver(release_gate=release_gate)

    if phase == "notification":
        repo = BatchNotificationRepository(_batch_probe_rows(notification=True))

        async def launch_notification(**kwargs):
            if kwargs["task_id"] == "task-1":
                driver.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    driver.swallowed.set()
                    await release_gate.wait()
            return {"run_id": f"notify-{kwargs['task_id']}"}

        service = McpTaskService(
            repository=repo,
            drivers=McpTaskDriverRegistry(),
            poll_interval_seconds=5,
            lease_seconds=120,
            max_concurrent_polls=3,
            launch_notification=launch_notification,
            get_run=AsyncMock(return_value=None),
        )
    else:
        repo = BatchCancellationRepository(_batch_probe_rows(), phase=phase)
        drivers = McpTaskDriverRegistry()
        drivers.register("fake", driver)
        service = McpTaskService(
            repository=repo,
            drivers=drivers,
            poll_interval_seconds=5,
            lease_seconds=120,
            max_concurrent_polls=3,
        )

    caller = asyncio.create_task(_run_batch_probe(service, phase))
    await driver.started.wait()
    caller.cancel("first cancellation")
    timed_out = False
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(caller, timeout=0.2)
        assert caught.value.args == ("first cancellation",)
    except TimeoutError:
        timed_out = True

    assert timed_out is False
    assert driver.swallowed.is_set()
    if phase == "poll":
        released = repo.released
    elif phase == "cancel":
        released = repo.cancel_releases
    else:
        released = repo.notification_releases
    assert sorted(task_id for task_id, _kwargs in released) == ["task-1", "task-2"]
    assert len(service._compensation_tasks) == 1

    release_gate.set()
    await _wait_for_compensation_tasks_to_clear(service)
    assert len(released) == 2


@pytest.mark.asyncio
async def test_started_child_swallowing_cancel_then_returning_still_releases_once(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    release_gate = asyncio.Event()
    driver = SuppressingBatchDriver(release_gate=release_gate)
    repo = BatchCancellationRepository([_claimed_row()], phase="poll")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    caller = asyncio.create_task(service.run_once(now=datetime.now(UTC)))
    await driver.started.wait()
    caller.cancel("first cancellation")
    await driver.swallowed.wait()
    assert repo.released == []
    release_gate.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await caller
    assert caught.value.args == ("first cancellation",)
    assert [task_id for task_id, _kwargs in repo.released] == ["task-1"]
    await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
async def test_repeated_batch_cancel_preserves_first_cancel_args(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    release_gate = asyncio.Event()
    driver = SuppressingBatchDriver(release_gate=release_gate)
    repo = BatchCancellationRepository([_claimed_row()], phase="poll")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    caller = asyncio.create_task(service.run_once(now=datetime.now(UTC)))
    await driver.started.wait()
    caller.cancel("first cancellation")
    await driver.swallowed.wait()
    caller.cancel("second cancellation")

    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(caller, timeout=0.2)
        assert caught.value.args == ("first cancellation",)
    finally:
        release_gate.set()
        if not caller.done():
            with pytest.raises(asyncio.CancelledError):
                await caller


@pytest.mark.asyncio
async def test_batch_outer_cancel_releases_duplicate_ids_by_position(monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    release_gate = asyncio.Event()
    driver = SuppressingBatchDriver(release_gate=release_gate)
    rows = [_claimed_row(), _claimed_row()]
    repo = BatchCancellationRepository(rows, phase="poll")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    caller = asyncio.create_task(service.run_once(now=datetime.now(UTC)))
    await driver.started.wait()
    caller.cancel("first cancellation")
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(caller, timeout=0.2)

    assert [task_id for task_id, _kwargs in repo.released] == ["task-1", "task-1"]
    release_gate.set()
    await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
async def test_batch_completion_cancel_race_releases_once_for_100_rounds():
    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    release_calls = []

    async def operation(_record):
        await asyncio.sleep(0)
        return None

    async def release(record):
        release_calls.append(record["position"])

    for position in range(100):
        caller = asyncio.create_task(
            service._run_claimed_batch(
                [{"id": "duplicate", "position": position}],
                operation=operation,
                release=release,
                action="race",
            )
        )
        await asyncio.sleep(0)
        caller.cancel("race cancellation")
        with pytest.raises(asyncio.CancelledError):
            await caller

    assert sorted(release_calls) == list(range(100))


class OrdinaryReleaseBatchRepository:
    def __init__(self, *, phase, outcome):
        self.phase = phase
        self.outcome = outcome
        self.release_started = asyncio.Event()
        self.release_gate = asyncio.Event()
        self.release_calls = []
        self.release_interrupted = False
        self.release_completed = False
        self.release_finished = asyncio.Event()
        self.caller_task = None

    def _records(self, phase):
        if self.phase != phase:
            return []
        record = _claimed_row()
        if phase == "notification":
            record.update(
                notification_status="claimed",
                dispatch_version=1,
                dispatch_attempt=0,
                dispatch_event={"status": "completed"},
            )
        return [record]

    async def claim_due_tasks(self, **_kwargs):
        return self._records("poll")

    async def claim_cancel_requests(self, **_kwargs):
        return self._records("cancel")

    async def claim_notification_work(self, **_kwargs):
        return self._records("notification")

    async def _release(self, task_id, **_kwargs):
        self.release_calls.append(task_id)
        self.release_started.set()
        if self.outcome in {"same_tick", "same_tick_self_cancel"}:
            assert self.caller_task is not None
            self.caller_task.cancel("same tick cancellation")
            if self.outcome == "same_tick_self_cancel":
                self.release_finished.set()
                raise asyncio.CancelledError("ordinary release cancelled itself")
            self.release_completed = True
            return True
        try:
            await self.release_gate.wait()
        except asyncio.CancelledError:
            self.release_interrupted = True
            raise
        if self.outcome == "failure":
            raise RuntimeError("ordinary release unavailable")
        if self.outcome == "self_cancel":
            self.release_finished.set()
            raise asyncio.CancelledError("ordinary release cancelled itself")
        self.release_completed = True
        return True

    async def release_claim(self, task_id, **kwargs):
        return await self._release(task_id, **kwargs)

    async def release_cancel_claim(self, task_id, **kwargs):
        return await self._release(task_id, **kwargs)

    async def release_notification_claim(self, task_id, **kwargs):
        return await self._release(task_id, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
@pytest.mark.parametrize("outcome", ["success", "failure", "self_cancel"])
async def test_ordinary_batch_release_is_handed_off_without_duplication(phase, outcome, monkeypatch, caplog):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    repo = OrdinaryReleaseBatchRepository(phase=phase, outcome=outcome)
    drivers = McpTaskDriverRegistry()
    if phase == "poll":
        drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    elif phase == "cancel":
        drivers.register("fake", FakeDriver(cancel_error=RuntimeError("cancel failed")))

    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=ConflictError("thread busy")),
        get_run=AsyncMock(return_value=None),
    )
    caller = asyncio.create_task(_run_batch_probe(service, phase))
    await repo.release_started.wait()
    caller.cancel("first cancellation")

    try:
        with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(caller, timeout=0.2)
        assert caught.value.args == ("first cancellation",)
        assert repo.release_interrupted is False
        assert repo.release_calls == ["task-1"]
        assert len(service._compensation_tasks) == 1

        repo.release_gate.set()
        await _wait_for_compensation_tasks_to_clear(service)

        assert repo.release_calls == ["task-1"]
        if outcome == "success":
            assert repo.release_completed is True
        else:
            assert repo.release_completed is False
            if outcome == "failure":
                assert "ordinary release unavailable" in caplog.text
            else:
                assert "MCP task batch release failed" in caplog.text
        assert not service._compensation_tasks
    finally:
        repo.release_gate.set()
        if not caller.done():
            with pytest.raises(asyncio.CancelledError):
                await caller
        await _wait_for_compensation_tasks_to_clear(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
async def test_ordinary_batch_release_timeout_has_service_owned_strong_root(phase, monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    repo = OrdinaryReleaseBatchRepository(phase=phase, outcome="success")
    drivers = McpTaskDriverRegistry()
    if phase == "poll":
        drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    elif phase == "cancel":
        drivers.register("fake", FakeDriver(cancel_error=RuntimeError("cancel failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=ConflictError("thread busy")),
        get_run=AsyncMock(return_value=None),
    )
    caller = asyncio.create_task(_run_batch_probe(service, phase))
    await repo.release_started.wait()
    await caller

    assert len(service._compensation_tasks) == 1
    release_task = next(iter(service._compensation_tasks))
    release_ref = weakref.ref(release_task)

    del release_task
    del caller
    gc.collect()
    assert release_ref() is not None

    repo.release_gate.set()
    await _wait_for_compensation_tasks_to_clear(service)
    await asyncio.sleep(0)
    assert not service._compensation_tasks


@pytest.mark.asyncio
async def test_ordinary_batch_release_completion_same_tick_is_terminal(monkeypatch):
    repo = OrdinaryReleaseBatchRepository(phase="poll", outcome="same_tick")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(_run_batch_probe(service, "poll"))
    repo.caller_task = caller

    with pytest.raises(asyncio.CancelledError) as caught:
        await caller

    assert caught.value.args == ("same tick cancellation",)
    assert repo.release_calls == ["task-1"]
    assert repo.release_completed is True
    assert not service._compensation_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel", "notification"])
async def test_repeated_outer_cancellation_keeps_one_ordinary_release(phase, monkeypatch):
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01)
    repo = OrdinaryReleaseBatchRepository(phase=phase, outcome="success")
    drivers = McpTaskDriverRegistry()
    if phase == "poll":
        drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    elif phase == "cancel":
        drivers.register("fake", FakeDriver(cancel_error=RuntimeError("cancel failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(side_effect=ConflictError("thread busy")),
        get_run=AsyncMock(return_value=None),
    )
    caller = asyncio.create_task(_run_batch_probe(service, phase))
    await repo.release_started.wait()
    caller.cancel("first cancellation")

    async with asyncio.timeout(0.2):
        while len(service._compensation_tasks) != 1:
            await asyncio.sleep(0)
    caller.cancel("second cancellation")

    with pytest.raises(asyncio.CancelledError) as caught:
        await caller
    assert caught.value.args == ("first cancellation",)
    assert repo.release_calls == ["task-1"]
    assert repo.release_interrupted is False

    repo.release_gate.set()
    await _wait_for_compensation_tasks_to_clear(service)
    assert repo.release_completed is True


@pytest.mark.asyncio
async def test_inner_ordinary_release_cancellation_does_not_kill_poller(caplog):
    repo = OrdinaryReleaseBatchRepository(phase="poll", outcome="self_cancel")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )

    try:
        with caplog.at_level(logging.ERROR):
            await service.start()
            await repo.release_started.wait()
            repo.release_gate.set()
            await repo.release_finished.wait()
            await asyncio.sleep(0)

        assert service._task is not None
        assert not service._task.done()
        assert repo.release_calls == ["task-1"]
        release_logs = [record for record in caplog.records if "MCP task batch release failed" in record.message]
        assert len(release_logs) == 1
        assert "release poll retry" in release_logs[0].message
        assert "task_id=task-1" in release_logs[0].message
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_terminal_ordinary_release_cancellation_is_consumed_once(caplog):
    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    state = service_module._BatchRecordState(_claimed_row())
    task = asyncio.get_running_loop().create_future()
    task.set_exception(asyncio.CancelledError("ordinary release cancelled itself"))
    state.ordinary_release_task = task
    token = service_module._current_batch_record.set(state)
    try:
        with caplog.at_level(logging.ERROR):
            await service._release_ordinary_batch_record(
                state.record,
                release=AsyncMock(),
                action="release poll retry",
            )
    finally:
        service_module._current_batch_record.reset(token)

    assert state.ordinary_release_terminal is True
    release_logs = [record for record in caplog.records if "MCP task batch release failed" in record.message]
    assert len(release_logs) == 1
    assert "release poll retry" in release_logs[0].message
    assert "task_id=task-1" in release_logs[0].message


@pytest.mark.asyncio
async def test_same_tick_outer_cancellation_wins_over_inner_ordinary_release(caplog):
    repo = OrdinaryReleaseBatchRepository(phase="poll", outcome="same_tick_self_cancel")
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(_run_batch_probe(service, "poll"))
    repo.caller_task = caller

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError) as caught:
        await caller

    assert caught.value.args == ("same tick cancellation",)
    assert repo.release_calls == ["task-1"]
    assert repo.release_finished.is_set()
    assert not service._compensation_tasks


class SelfCancellingClaimRepository:
    def __init__(self):
        self.claim_started = asyncio.Event()
        self.claim_calls = 0
        self.release_calls = []

    async def claim_due_tasks(self, **_kwargs):
        self.claim_calls += 1
        self.claim_started.set()
        raise asyncio.CancelledError("poll claim cancelled itself")

    async def release_claim(self, task_id, **kwargs):
        self.release_calls.append((task_id, kwargs))
        return True


@pytest.mark.asyncio
async def test_inner_claim_cancellation_does_not_kill_poller_or_handoff(caplog):
    repo = SelfCancellingClaimRepository()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    handoff = AsyncMock()
    service._finish_cancelled_claim_handoff = handoff

    try:
        with caplog.at_level(logging.ERROR):
            await service.start()
            await repo.claim_started.wait()
            async with asyncio.timeout(1):
                while not any("MCP task claim operation failed" in record.message for record in caplog.records):
                    await asyncio.sleep(0)

        assert service._task is not None
        assert not service._task.done()
        assert repo.claim_calls == 1
        assert repo.release_calls == []
        handoff.assert_not_awaited()
        claim_logs = [record for record in caplog.records if "MCP task claim operation failed" in record.message]
        assert len(claim_logs) == 1
        assert "poll claim" in claim_logs[0].message
        assert "task_id=batch" in claim_logs[0].message
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_same_tick_outer_claim_cancellation_wins_and_preserves_args():
    caller = None

    async def claim():
        assert caller is not None
        caller.cancel("same tick claim cancellation")
        raise asyncio.CancelledError("claim cancelled itself")

    service = McpTaskService(
        repository=SimpleNamespace(),
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    caller = asyncio.create_task(
        service._claim_with_cancellation_release(
            claim,
            phase="poll",
            action="poll claim",
            release=AsyncMock(),
        )
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        await caller

    assert caught.value.args == ("same tick claim cancellation",)
    assert not service._compensation_tasks


@pytest.mark.asyncio
async def test_poll_retry_release_hang_does_not_block_run_once(monkeypatch):
    import app.mcp_tasks.service as service_module

    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01, raising=False)

    class HangingReleaseRepo(FakeRepository):
        def __init__(self):
            super().__init__([_claimed_row()])
            self.release_started = asyncio.Event()
            self.finish_release = asyncio.Event()
            self.release_calls = 0

        async def release_claim(self, task_id, **kwargs):
            self.release_calls += 1
            self.release_started.set()
            await self.finish_release.wait()
            return True

    repo = HangingReleaseRepo()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    try:
        await asyncio.wait_for(service.run_once(now=datetime.now(UTC)), timeout=0.2)
    finally:
        repo.finish_release.set()
        await asyncio.sleep(0)

    assert repo.release_calls == 1


@pytest.mark.asyncio
async def test_notification_failure_release_hang_does_not_block(monkeypatch):
    import app.mcp_tasks.service as service_module

    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01, raising=False)

    class HangingNotificationReleaseRepo:
        def __init__(self, records):
            self.records = list(records)
            self.release_started = asyncio.Event()
            self.finish_release = asyncio.Event()
            self.release_calls = 0

        async def claim_notification_work(self, **_kwargs):
            return list(self.records)

        async def release_notification_lease(self, task_id, **kwargs):
            self.release_calls += 1
            self.release_started.set()
            await self.finish_release.wait()
            return True

    record = {
        **_claimed_row(),
        "notification_status": "dispatched",
        "notification_run_id": "run-broken",
        "dispatch_version": 3,
    }
    repo = HangingNotificationReleaseRepo([record])
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(side_effect=RuntimeError("run store unavailable")),
    )
    try:
        await asyncio.wait_for(service._run_notifications(now=datetime.now(UTC)), timeout=0.2)
    finally:
        repo.finish_release.set()
        await asyncio.sleep(0)

    assert repo.release_calls == 1


@pytest.mark.asyncio
async def test_claim_hang_does_not_block_run_once(monkeypatch):
    import app.mcp_tasks.service as service_module

    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01, raising=False)

    class HangingClaimRepo(FakeRepository):
        def __init__(self):
            super().__init__()
            self.claim_started = asyncio.Event()
            self.finish_claim = asyncio.Event()

        async def claim_due_tasks(self, **_kwargs):
            self.claim_started.set()
            await self.finish_claim.wait()
            return []

    repo = HangingClaimRepo()
    service = McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    try:
        await asyncio.wait_for(service.run_once(now=datetime.now(UTC)), timeout=0.2)
    finally:
        repo.finish_claim.set()
        await asyncio.sleep(0)

    assert repo.claim_started.is_set()


class FailingReleaseRepository(FakeRepository):
    def __init__(self):
        super().__init__([_claimed_row()])
        self.release_called = False

    async def release_claim(self, task_id, **kwargs):
        self.release_called = True
        raise RuntimeError("release db down")


def test_failing_release_does_not_leak_unretrieved_shield_exception(tmp_path):
    import os
    import subprocess
    import sys
    import textwrap

    backend_dir = os.path.dirname(os.path.dirname(__file__))
    probe = textwrap.dedent(
        """
        import asyncio, gc
        from datetime import UTC, datetime
        from app.mcp_tasks.service import McpTaskService
        from deerflow.mcp.tasks import McpTaskDriverRegistry

        class Repo:
            def __init__(self):
                self.row = {
                    "id": "task-1", "user_id": "u", "thread_id": "t", "run_id": None,
                    "tool_call_id": "c", "server_name": "s", "driver_name": "fake",
                    "remote_task_id": "r", "task_name": "n", "status": "working",
                    "driver_data": {}, "lease_owner": "o", "lease_token": "tok-1",
                    "consecutive_poll_error_count": 0,
                }
                self.claimed = False

            async def claim_due_tasks(self, **_kw):
                if self.claimed:
                    return []
                self.claimed = True
                return [dict(self.row)]

            async def release_claim(self, task_id, **kw):
                raise RuntimeError("release db down")

        class Driver:
            async def get_status(self, task):
                raise RuntimeError("poll down")

        async def scenario():
            repo = Repo()
            drivers = McpTaskDriverRegistry()
            drivers.register("fake", Driver())
            service = McpTaskService(
                repository=repo, drivers=drivers,
                poll_interval_seconds=5, lease_seconds=120, max_concurrent_polls=3,
            )
            await service.run_once(now=datetime.now(UTC))
            del service, repo, drivers
            for _ in range(20):
                gc.collect()
                await asyncio.sleep(0)

        captured = []
        loop = asyncio.new_event_loop()
        try:
            loop.set_exception_handler(lambda _loop, context: captured.append(context.get("message", "")))
            loop.run_until_complete(scenario())
        finally:
            loop.close()
        if any("Future exception was never retrieved" in message for message in captured):
            print("UNRETRIEVED")
        """
    )
    env = {**os.environ, "PYTHONPATH": backend_dir}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=backend_dir,
        env=env,
    )
    assert "UNRETRIEVED" not in result.stdout, result.stderr


@pytest.mark.asyncio
async def test_poll_release_hang_without_batch_is_bounded(monkeypatch):
    import app.mcp_tasks.service as service_module

    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.01, raising=False)

    class HangingReleaseRepo(FakeRepository):
        def __init__(self):
            super().__init__([_claimed_row()])
            self.release_started = asyncio.Event()
            self.finish_release = asyncio.Event()

        async def release_claim(self, task_id, **kwargs):
            self.release_started.set()
            await self.finish_release.wait()
            return True

    repo = HangingReleaseRepo()
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", FakeDriver(error=RuntimeError("poll failed")))
    service = McpTaskService(
        repository=repo,
        drivers=drivers,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_polls=3,
    )
    try:
        # Direct single-record path (no batch context) must still be bounded.
        await asyncio.wait_for(
            service._poll_one(_claimed_row(), now=datetime.now(UTC)),
            timeout=0.2,
        )
    finally:
        repo.finish_release.set()
        await asyncio.sleep(0)

    assert repo.release_started.is_set()
