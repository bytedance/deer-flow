import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

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


class FailingApplyRepository(FakeRepository):
    async def apply_snapshot(self, task_id, **kwargs):
        if task_id == "task-1":
            raise RuntimeError("database unavailable")
        return await super().apply_snapshot(task_id, **kwargs)


class FailingCreateRepository(FakeRepository):
    async def create(self, **kwargs):
        self.created.append(kwargs)
        raise RuntimeError("database unavailable")


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
