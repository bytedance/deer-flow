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
async def test_input_required_is_persisted_and_paused_until_future_resume(tmp_path):
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
        error=None,
        input_required={"prompt": "Approve deployment?"},
        next_poll_at=None,
        polled_at=now,
    )
    assert applied is True

    stored = await repo.get("task-3", user_id="user-1")
    assert stored is not None
    assert stored["input_required"] == {"prompt": "Approve deployment?"}
    assert stored["notification_status"] == "pending"
    assert stored["next_poll_at"] is None


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
        error=None,
        input_required=None,
        next_poll_at=now + timedelta(seconds=5),
        polled_at=now,
    )
    assert applied is True

    stored = await repo.get("task-6", user_id="user-1")
    assert stored is not None
    assert stored["consecutive_poll_error_count"] == 0
