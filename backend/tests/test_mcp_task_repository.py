from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import DuplicateMcpRemoteTaskError, McpTaskRepository


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


async def _make_repo(tmp_path) -> McpTaskRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    return McpTaskRepository(session_factory)


async def _create_working_task(
    repo: McpTaskRepository,
    *,
    task_id: str,
    now: datetime,
    user_id: str = "user-1",
    remote_task_id: str | None = None,
) -> dict:
    return await repo.create(
        task_id=task_id,
        user_id=user_id,
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        driver_name="fake",
        remote_task_id=remote_task_id or f"remote-{task_id}",
        task_name="Generate report",
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=now - timedelta(seconds=1),
        driver_data={"status_tool": "status"},
    )


@pytest.mark.asyncio
async def test_remote_task_id_is_unique_per_user_and_server(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(
        repo,
        task_id="task-remote-1",
        now=now,
        remote_task_id="shared-remote-id",
    )

    with pytest.raises(DuplicateMcpRemoteTaskError, match="already tracked"):
        await _create_working_task(
            repo,
            task_id="task-remote-2",
            now=now,
            remote_task_id="shared-remote-id",
        )

    other_user = await _create_working_task(
        repo,
        task_id="task-remote-3",
        now=now,
        user_id="user-2",
        remote_task_id="shared-remote-id",
    )
    assert other_user["remote_task_id"] == "shared-remote-id"


@pytest.mark.asyncio
async def test_other_integrity_errors_are_not_duplicate_remote_tasks(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="shared-local-id", now=now)

    with pytest.raises(IntegrityError):
        await _create_working_task(
            repo,
            task_id="shared-local-id",
            now=now,
            remote_task_id="different-remote-id",
        )


@pytest.mark.asyncio
async def test_claim_due_tasks_skips_live_leases_and_reclaims_expired_ones(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-1", now=now)

    first = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )
    assert [task["id"] for task in first] == ["task-1"]

    while_live = await repo.claim_due_tasks(
        now=now + timedelta(seconds=10),
        lease_owner="worker-2",
        lease_seconds=60,
        limit=10,
    )
    assert while_live == []

    reclaimed = await repo.claim_due_tasks(
        now=now + timedelta(seconds=61),
        lease_owner="worker-2",
        lease_seconds=60,
        limit=10,
    )
    assert [task["id"] for task in reclaimed] == ["task-1"]
    assert reclaimed[0]["lease_owner"] == "worker-2"


@pytest.mark.asyncio
async def test_apply_snapshot_requires_current_lease_owner_and_terminalizes_task(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-2", now=now)
    await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-new",
        lease_seconds=60,
        limit=10,
    )

    stale_applied = await repo.apply_snapshot(
        "task-2",
        lease_owner="worker-old",
        status="failed",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error="stale result",
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    assert stale_applied is False

    applied = await repo.apply_snapshot(
        "task-2",
        lease_owner="worker-new",
        status="completed",
        result={"report": "ready"},
        result_preview=None,
        result_truncated=False,
        result_artifact={"uri": "s3://reports/2.json", "mime_type": "application/json"},
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    assert applied is True

    stored = await repo.get("task-2", user_id="user-1")
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["result"] == {"report": "ready"}
    assert stored["result_artifact"] == {
        "uri": "s3://reports/2.json",
        "mime_type": "application/json",
    }
    assert stored["notification_status"] == "pending"
    assert stored["lease_owner"] is None

    assert (
        await repo.claim_due_tasks(
            now=now + timedelta(hours=1),
            lease_owner="worker-3",
            lease_seconds=60,
            limit=10,
        )
        == []
    )


@pytest.mark.asyncio
async def test_apply_snapshot_rejects_result_after_same_workers_lease_expires(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-expired", now=now)
    await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )

    applied = await repo.apply_snapshot(
        "task-expired",
        lease_owner="worker-1",
        status="completed",
        result={"report": "stale"},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now + timedelta(seconds=61),
    )

    assert applied is False
    stored = await repo.get("task-expired", user_id="user-1")
    assert stored is not None
    assert stored["status"] == "working"
    assert stored["result"] is None


@pytest.mark.asyncio
async def test_input_required_is_persisted_and_remains_scheduled_for_slow_polling(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-3", now=now)
    await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )

    applied = await repo.apply_snapshot(
        "task-3",
        lease_owner="worker-1",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve deployment?"},
        next_poll_at=now + timedelta(seconds=60),
        polled_at=now,
    )
    assert applied is True

    stored = await repo.get("task-3", user_id="user-1")
    assert stored is not None
    assert stored["input_required"] == {"prompt": "Approve deployment?"}
    assert stored["notification_status"] == "pending"
    assert datetime.fromisoformat(stored["next_poll_at"]) == now + timedelta(seconds=60)


@pytest.mark.asyncio
async def test_release_claim_retries_transient_poll_failure(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-4", now=now)
    await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )
    retry_at = now + timedelta(seconds=30)

    released = await repo.release_claim(
        "task-4",
        lease_owner="worker-1",
        next_poll_at=retry_at,
        error="temporary network failure",
    )
    assert released is True

    stored = await repo.get("task-4", user_id="user-1")
    assert stored is not None
    assert stored["status"] == "working"
    assert stored["last_poll_error"] == "temporary network failure"
    assert datetime.fromisoformat(stored["next_poll_at"]) == retry_at
    assert stored["lease_owner"] is None


@pytest.mark.asyncio
async def test_consecutive_poll_error_count_increments_and_resets_on_success(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-6", now=now)

    for expected_errors in (1, 2):
        await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
        await repo.release_claim(
            "task-6",
            lease_owner="worker-1",
            next_poll_at=now - timedelta(seconds=1),
            error="temporary network failure",
        )
        stored = await repo.get("task-6", user_id="user-1")
        assert stored is not None
        assert stored["consecutive_poll_error_count"] == expected_errors

    await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    applied = await repo.apply_snapshot(
        "task-6",
        lease_owner="worker-1",
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=now + timedelta(seconds=5),
        polled_at=now,
    )
    assert applied is True

    stored = await repo.get("task-6", user_id="user-1")
    assert stored is not None
    assert stored["consecutive_poll_error_count"] == 0


@pytest.mark.asyncio
async def test_notification_snapshot_is_versioned_and_not_overwritten_in_flight(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-notify", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify",
        lease_owner="poller",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve?"},
        next_poll_at=now,
        polled_at=now,
    )

    first = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert first[0]["dispatch_version"] == 1
    assert first[0]["dispatch_event"]["input_required"] == {"prompt": "Approve?"}

    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify",
        lease_owner="poller",
        status="completed",
        result={"done": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    changed = await repo.get("task-notify", user_id="user-1")
    assert changed is not None
    assert changed["event_version"] == 2
    assert changed["dispatch_version"] == 1
    assert changed["dispatch_event"]["status"] == "input_required"

    await repo.mark_notification_dispatched(
        "task-notify",
        lease_owner="notifier",
        dispatch_version=1,
        run_id="notify-run-1",
        now=now,
    )
    await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    await repo.finish_notification_run(
        "task-notify",
        lease_owner="notifier",
        dispatch_version=1,
        delivered=True,
        next_notification_at=None,
        error=None,
        now=now,
    )
    second = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert second[0]["dispatch_version"] == 2
    assert second[0]["dispatch_event"]["status"] == "completed"


@pytest.mark.asyncio
async def test_notification_retry_rebuilds_a_newer_event_and_resets_its_budget(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-retry-latest", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-retry-latest",
        lease_owner="poller",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve?"},
        next_poll_at=now,
        polled_at=now,
    )
    first = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    await repo.mark_notification_dispatched(
        "task-retry-latest",
        lease_owner="notifier",
        dispatch_version=first[0]["dispatch_version"],
        run_id="notify-run-1",
        now=now,
    )
    await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    retry_at = now + timedelta(seconds=5)
    await repo.finish_notification_run(
        "task-retry-latest",
        lease_owner="notifier",
        dispatch_version=first[0]["dispatch_version"],
        delivered=False,
        next_notification_at=retry_at,
        error="Agent run failed",
        now=now,
    )
    failed = await repo.get("task-retry-latest", user_id="user-1")
    assert failed is not None
    assert failed["notification_status"] == "retry"
    assert failed["dispatch_attempt"] == 1
    assert failed["notification_attempt_count"] == 1

    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-retry-latest",
        lease_owner="poller",
        status="completed",
        result={"done": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    latest = await repo.claim_notification_work(
        now=retry_at,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )

    assert latest[0]["dispatch_version"] == first[0]["dispatch_version"] + 1
    assert latest[0]["dispatch_event"]["status"] == "completed"
    assert latest[0]["dispatch_attempt"] == 0
    assert latest[0]["notification_attempt_count"] == 0


@pytest.mark.asyncio
async def test_unexpected_notification_failure_releases_lease_without_changing_phase(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-notify-release", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify-release",
        lease_owner="poller",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve?"},
        next_poll_at=now,
        polled_at=now,
    )
    await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    retry_at = now + timedelta(seconds=5)

    assert await repo.release_notification_lease(
        "task-notify-release",
        lease_owner="notifier",
        next_notification_at=retry_at,
        error="run store unavailable",
    )

    stored = await repo.get("task-notify-release", user_id="user-1")
    assert stored is not None
    assert stored["notification_status"] == "claimed"
    assert stored["notification_lease_owner"] is None
    assert stored["notification_error"] == "run store unavailable"
    assert datetime.fromisoformat(stored["next_notification_at"]) == retry_at


@pytest.mark.asyncio
async def test_notification_launch_failure_counts_and_reclaims_latest_snapshot(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-launch-retry", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-launch-retry",
        lease_owner="poller",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve?"},
        next_poll_at=now,
        polled_at=now,
    )
    first = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    retry_at = now + timedelta(seconds=5)

    assert await repo.release_notification_claim(
        "task-launch-retry",
        lease_owner="notifier",
        next_notification_at=retry_at,
        error="run store unavailable",
        replace_with_latest=True,
        count_failure=True,
    )

    stored = await repo.get("task-launch-retry", user_id="user-1")
    assert stored is not None
    assert stored["notification_status"] == "pending"
    assert stored["notification_attempt_count"] == 1
    assert stored["dispatch_version"] == first[0]["dispatch_version"]
    reclaimed = await repo.claim_notification_work(
        now=retry_at,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert reclaimed[0]["notification_attempt_count"] == 1
    assert reclaimed[0]["dispatch_version"] == first[0]["dispatch_version"]
    assert reclaimed[0]["dispatch_event"] == first[0]["dispatch_event"]


@pytest.mark.asyncio
async def test_permanent_notification_failure_is_not_reclaimed(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-dead-letter", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dead-letter",
        lease_owner="poller",
        status="completed",
        result={"done": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    claimed = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )

    assert await repo.dead_letter_notification(
        "task-dead-letter",
        lease_owner="notifier",
        dispatch_version=claimed[0]["dispatch_version"],
        error="Thread deleted-thread not found",
        count_failure=True,
        now=now,
    )

    stored = await repo.get("task-dead-letter", user_id="user-1")
    assert stored is not None
    assert stored["notification_status"] == "dead_letter"
    assert stored["notification_attempt_count"] == 1
    assert stored["notification_error"] == "Thread deleted-thread not found"
    assert (
        await repo.claim_notification_work(
            now=now + timedelta(days=1),
            lease_owner="other",
            lease_seconds=60,
            limit=1,
            tracking_degraded_after_errors=3,
        )
        == []
    )


@pytest.mark.asyncio
async def test_dispatched_notification_can_be_dead_lettered_after_retry_budget(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-dispatched-budget", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-budget",
        lease_owner="poller",
        status="completed",
        result={"done": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    first = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    dispatch_version = first[0]["dispatch_version"]
    assert await repo.mark_notification_dispatched(
        "task-dispatched-budget",
        lease_owner="notifier",
        dispatch_version=dispatch_version,
        run_id="notify-run-1",
        now=now,
    )

    claimed = await repo.claim_notification_work(
        now=now,
        lease_owner="budget-checker",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert claimed[0]["notification_status"] == "dispatched"
    assert await repo.dead_letter_notification(
        "task-dispatched-budget",
        lease_owner="budget-checker",
        dispatch_version=dispatch_version,
        error="Notification delivery stopped after 5 failed attempts",
        count_failure=False,
        now=now,
    )

    stored = await repo.get("task-dispatched-budget", user_id="user-1")
    assert stored is not None
    assert stored["notification_status"] == "dead_letter"
    assert stored["notification_run_id"] is None


@pytest.mark.asyncio
async def test_dead_lettering_dispatched_snapshot_preserves_newer_event(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-dispatched-latest", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-latest",
        lease_owner="poller",
        status="input_required",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required={"prompt": "Approve?"},
        next_poll_at=now,
        polled_at=now,
    )
    first = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    dispatch_version = first[0]["dispatch_version"]
    assert await repo.mark_notification_dispatched(
        "task-dispatched-latest",
        lease_owner="notifier",
        dispatch_version=dispatch_version,
        run_id="notify-run-1",
        now=now,
    )

    await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-latest",
        lease_owner="poller",
        status="completed",
        result={"done": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now,
    )
    claimed = await repo.claim_notification_work(
        now=now,
        lease_owner="budget-checker",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert claimed[0]["dispatch_version"] == dispatch_version
    assert await repo.dead_letter_notification(
        "task-dispatched-latest",
        lease_owner="budget-checker",
        dispatch_version=dispatch_version,
        error="old snapshot exhausted its retry budget",
        count_failure=False,
        now=now,
    )

    stored = await repo.get("task-dispatched-latest", user_id="user-1")
    assert stored is not None
    assert stored["notification_status"] == "pending"
    assert stored["notification_attempt_count"] == 0
    assert stored["notification_error"] is None
    latest = await repo.claim_notification_work(
        now=now,
        lease_owner="latest-notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert latest[0]["dispatch_version"] > dispatch_version
    assert latest[0]["dispatch_event"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancel_request_stops_polling_and_rejects_stale_poll_result(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-cancel", now=now)
    await repo.claim_due_tasks(now=now, lease_owner="stale-poller", lease_seconds=60, limit=1)

    requested = await repo.request_cancel(
        "task-cancel",
        user_id="user-1",
        thread_id="thread-1",
        requested_at=now,
    )
    assert requested is not None
    assert await repo.claim_due_tasks(now=now, lease_owner="new-poller", lease_seconds=60, limit=1) == []
    assert (
        await repo.apply_snapshot(
            "task-cancel",
            lease_owner="stale-poller",
            status="completed",
            result={"stale": True},
            result_preview=None,
            result_truncated=False,
            result_artifact=None,
            error=None,
            input_required=None,
            next_poll_at=None,
            polled_at=now,
        )
        is False
    )

    claimed = await repo.claim_cancel_requests(
        now=now,
        lease_owner="canceller",
        lease_seconds=60,
        limit=1,
    )
    assert [row["id"] for row in claimed] == ["task-cancel"]

    repeated = await repo.request_cancel(
        "task-cancel",
        user_id="user-1",
        thread_id="thread-1",
        requested_at=now + timedelta(seconds=1),
    )
    assert repeated is not None
    assert repeated["lease_owner"] == "canceller"
    assert repeated["cancel_attempt_count"] == 1
    assert await repo.claim_cancel_requests(now=now, lease_owner="other", lease_seconds=60, limit=1) == []
    assert await repo.apply_cancel_snapshot(
        "task-cancel",
        lease_owner="canceller",
        status="cancelled",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        completed_at=now,
    )
    stored = await repo.get("task-cancel", user_id="user-1")
    assert stored is not None
    assert stored["status"] == "cancelled"
    assert stored["notification_status"] == "pending"
