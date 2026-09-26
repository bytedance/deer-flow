import asyncio
import contextlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import (
    DuplicateMcpRemoteTaskError,
    McpTaskRepository,
    McpTaskThreadMismatchError,
)
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow


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
    thread_incarnation: str | None = None,
) -> dict:
    async with repo._sf() as session:
        if await session.get(ThreadMetaRow, "thread-1") is None:
            session.add(
                ThreadMetaRow(
                    thread_id="thread-1",
                    incarnation=None,
                    user_id=user_id,
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
    return await repo.create(
        task_id=task_id,
        user_id=user_id,
        thread_id="thread-1",
        expected_thread_incarnation=thread_incarnation,
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


@contextlib.asynccontextmanager
async def _pause_claim_mutation(monkeypatch, operation):
    """Pause an old mutation while another session reclaims its row.

    The former SELECT/ORM-flush implementation must pause after its ownership
    read has loaded the old row. The atomic implementation pauses before its
    conditional UPDATE. Both leave the competing claim free to commit using
    the production SQLite engine, without replacing any persistence logic.
    """
    entered = asyncio.Event()
    resume = asyncio.Event()
    original_execute = AsyncSession.execute
    intercepted = False

    async def execute(session, statement, *args, **kwargs):
        nonlocal intercepted
        if asyncio.current_task() is not task or intercepted:
            return await original_execute(session, statement, *args, **kwargs)
        intercepted = True
        if statement.is_select:
            result = await original_execute(session, statement, *args, **kwargs)
        entered.set()
        await resume.wait()
        if statement.is_select:
            return result
        return await original_execute(session, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "execute", execute)
        task = asyncio.create_task(operation)
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            yield task, resume
        finally:
            resume.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["release_claim", "apply_snapshot", "apply_cancel_snapshot"])
async def test_interleaved_reclaim_fences_inflight_poll_and_cancel_mutations(tmp_path, monkeypatch, operation):
    repo = await _make_repo(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    task_id = "interleaved-claim"
    await _create_working_task(repo, task_id=task_id, now=now)
    claim = repo.claim_due_tasks
    if operation == "apply_cancel_snapshot":
        await repo.request_cancel(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=now)
        claim = repo.claim_cancel_requests
    first = await claim(now=now, lease_owner="worker-1", lease_seconds=60, limit=1)
    kwargs = {"lease_owner": "worker-1", "lease_token": first[0]["lease_token"]}
    if operation == "release_claim":
        kwargs.update(next_poll_at=now + timedelta(seconds=30), error="old poll failed")
    else:
        kwargs.update(
            status="cancelled" if operation == "apply_cancel_snapshot" else "completed",
            result={"stale": True},
            result_preview="old result",
            result_truncated=False,
            result_artifact=None,
            error=None,
            input_required=None,
        )
        if operation == "apply_snapshot":
            kwargs.update(next_poll_at=None, polled_at=now)
        else:
            kwargs.update(completed_at=now)

    async with _pause_claim_mutation(monkeypatch, getattr(repo, operation)(task_id, **kwargs)) as (pending, resume):
        # Advance only the claim clock, not the stale operation's completion
        # timestamp: expiry must not reject it before the token fence is tested.
        second = await asyncio.wait_for(claim(now=now + timedelta(seconds=61), lease_owner="worker-1", lease_seconds=60, limit=1), timeout=5)
        assert len(second) == 1
        assert second[0]["lease_token"] != first[0]["lease_token"]
        before = await repo.get(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation=None)
        assert before is not None
        resume.set()
        applied = await asyncio.wait_for(pending, timeout=5)

    # Check the entire row, including scheduling, errors, results and event
    # versions, not just the new lease: stale work must have no side effects.
    assert await repo.get(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation=None) == before
    assert applied is False


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False], ids=["success", "failure"])
async def test_interleaved_reclaim_fences_inflight_notification_completion(tmp_path, monkeypatch, delivered):
    repo = await _make_repo(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    task_id = "interleaved-notification"
    await _create_working_task(repo, task_id=task_id, now=now)
    poll = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    assert await repo.apply_snapshot(
        task_id,
        lease_owner="poller",
        lease_token=poll[0]["lease_token"],
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
    claim_kwargs = {"lease_owner": "notifier", "lease_seconds": 60, "limit": 1, "tracking_degraded_after_errors": 3}
    launch = await repo.claim_notification_work(now=now, **claim_kwargs)
    assert await repo.mark_notification_dispatched(
        task_id,
        lease_owner="notifier",
        notification_lease_token=launch[0]["notification_lease_token"],
        dispatch_version=launch[0]["dispatch_version"],
        run_id="notification-run",
        now=now,
    )
    first = await repo.claim_notification_work(now=now, **claim_kwargs)
    operation = repo.finish_notification_run(
        task_id,
        lease_owner="notifier",
        notification_lease_token=first[0]["notification_lease_token"],
        dispatch_version=first[0]["dispatch_version"],
        delivered=delivered,
        next_notification_at=None if delivered else now + timedelta(seconds=30),
        error=None if delivered else "old notification failed",
        now=now,
    )
    async with _pause_claim_mutation(monkeypatch, operation) as (pending, resume):
        second = await asyncio.wait_for(repo.claim_notification_work(now=now + timedelta(seconds=61), **claim_kwargs), timeout=5)
        assert len(second) == 1
        assert second[0]["notification_lease_token"] != first[0]["notification_lease_token"]
        before = await repo.get(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation=None)
        assert before is not None
        resume.set()
        applied = await asyncio.wait_for(pending, timeout=5)

    assert await repo.get(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation=None) == before
    assert applied is False


@pytest.mark.asyncio
async def test_legacy_task_writer_leaves_thread_incarnation_null(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    async with repo._sf() as session:
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="owned-incarnation",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            McpTaskRow(
                id="legacy-writer",
                user_id="user-1",
                thread_id="thread-1",
                server_name="reports",
                driver_name="fake",
                remote_task_id="remote-legacy-writer",
                task_name="Generate report",
                status="working",
                driver_data={},
                next_poll_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with repo._sf() as session:
        row = await session.get(McpTaskRow, "legacy-writer")
    assert row is not None
    assert row.thread_incarnation is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "thread_owner",
    [
        "user-1",
        None,
    ],
)
async def test_create_atomically_copies_accessible_thread_incarnation(
    tmp_path,
    thread_owner,
):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    incarnation = "matching-incarnation"
    async with repo._sf() as session:
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation=incarnation,
                user_id=thread_owner,
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    task = await _create_working_task(
        repo,
        task_id="new-writer",
        now=now,
        thread_incarnation=incarnation,
    )

    assert "thread_incarnation" not in task
    async with repo._sf() as session:
        row = await session.get(McpTaskRow, "new-writer")
    assert row is not None
    assert row.thread_incarnation == incarnation


@pytest.mark.asyncio
async def test_create_rejects_missing_or_inaccessible_thread(tmp_path):
    repo = await _make_repo(tmp_path)

    with pytest.raises(McpTaskThreadMismatchError):
        await repo.create(
            task_id="missing-thread",
            user_id="user-1",
            thread_id="missing-thread",
            expected_thread_incarnation=None,
            run_id="run-1",
            tool_call_id="call-1",
            server_name="reports",
            driver_name="fake",
            remote_task_id="remote-missing",
            task_name="Generate report",
            status="working",
            result=None,
            result_preview=None,
            result_truncated=False,
            result_artifact=None,
            error=None,
            input_required=None,
            next_poll_at=None,
        )

    async with repo._sf() as session:
        row = await session.get(McpTaskRow, "missing-thread")
    assert row is None


@pytest.mark.asyncio
async def test_create_observes_delete_and_recreate_at_insert_boundary(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    async with repo._sf() as session:
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="old-incarnation",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    engine = get_engine()
    assert engine is not None
    replaced = False
    lock_statement = None

    def replace_thread_before_scope_lock(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal lock_statement, replaced
        if replaced or "UPDATE THREADS_META" not in statement.upper():
            return
        replaced = True
        lock_statement = statement
        with contextlib.closing(sqlite3.connect(tmp_path / "deerflow.db")) as connection:
            with connection:
                connection.execute("DELETE FROM threads_meta WHERE thread_id = ?", ("thread-1",))
                connection.execute(
                    """
                    INSERT INTO threads_meta (
                        thread_id, incarnation, user_id, status, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "thread-1",
                        "replacement-incarnation",
                        "user-1",
                        "idle",
                        "{}",
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )

    event.listen(engine.sync_engine, "before_cursor_execute", replace_thread_before_scope_lock)
    try:
        with pytest.raises(McpTaskThreadMismatchError):
            await _create_working_task(
                repo,
                task_id="racing-task",
                now=now,
                thread_incarnation="old-incarnation",
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", replace_thread_before_scope_lock)

    assert replaced is True
    assert lock_statement is not None
    normalized_lock = " ".join(lock_statement.upper().split())
    assert "UPDATE THREADS_META SET INCARNATION = INCARNATION" in normalized_lock
    assert "INCARNATION IS ?" in normalized_lock
    async with repo._sf() as session:
        row = await session.get(McpTaskRow, "racing-task")
    assert row is None


@pytest.mark.asyncio
async def test_request_cancel_rejects_delete_recreate_before_scope_lock(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    async with repo._sf() as session:
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="old-incarnation",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await _create_working_task(
        repo,
        task_id="old-task",
        now=now,
        thread_incarnation="old-incarnation",
    )

    engine = get_engine()
    assert engine is not None
    replaced = False

    def replace_thread_before_scope_lock(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal replaced
        if replaced or "UPDATE THREADS_META" not in statement.upper():
            return
        replaced = True
        with contextlib.closing(sqlite3.connect(tmp_path / "deerflow.db")) as connection:
            with connection:
                connection.execute("DELETE FROM threads_meta WHERE thread_id = ?", ("thread-1",))
                connection.execute(
                    """
                    INSERT INTO threads_meta (
                        thread_id, incarnation, user_id, status, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "thread-1",
                        "replacement-incarnation",
                        "user-1",
                        "idle",
                        "{}",
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )

    event.listen(engine.sync_engine, "before_cursor_execute", replace_thread_before_scope_lock)
    try:
        result = await repo.request_cancel(
            "old-task",
            user_id="user-1",
            thread_id="thread-1",
            thread_incarnation="old-incarnation",
            requested_at=now,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", replace_thread_before_scope_lock)

    assert replaced is True
    assert result is None
    async with repo._sf() as session:
        task = await session.get(McpTaskRow, "old-task")
    assert task is not None
    assert task.cancel_requested_at is None


@pytest.mark.asyncio
async def test_user_access_is_limited_to_current_thread_incarnation(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="old-task", now=now)

    async with repo._sf() as session:
        old_thread = await session.get(ThreadMetaRow, "thread-1")
        assert old_thread is not None
        await session.delete(old_thread)
        await session.commit()
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="replacement-incarnation",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    assert await repo.list_by_thread("thread-1", user_id="user-1", thread_incarnation=None) == []
    assert await repo.get("old-task", user_id="user-1", thread_id="thread-1", thread_incarnation=None) is None
    assert (
        await repo.request_cancel(
            "old-task",
            user_id="user-1",
            thread_id="thread-1",
            thread_incarnation=None,
            requested_at=now,
        )
        is None
    )


@pytest.mark.asyncio
async def test_pr1_does_not_change_worker_claim_eligibility(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="old-task", now=now)

    async with repo._sf() as session:
        old_thread = await session.get(ThreadMetaRow, "thread-1")
        assert old_thread is not None
        await session.delete(old_thread)
        await session.commit()
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="replacement-incarnation",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    claimed = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )

    assert [task["id"] for task in claimed] == ["old-task"]
    assert claimed[0]["_thread_incarnation"] is None


@pytest.mark.asyncio
async def test_user_access_treats_legacy_null_incarnations_as_equal(tmp_path):
    repo = await _make_repo(tmp_path)
    task = await _create_working_task(repo, task_id="legacy-task", now=datetime.now(UTC))

    assert "thread_incarnation" not in task
    assert "_thread_incarnation" not in task
    assert await repo.get("legacy-task", user_id="user-1", thread_id="thread-1", thread_incarnation=None) is not None


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

    async with repo._sf() as session:
        thread = await session.get(ThreadMetaRow, "thread-1")
        assert thread is not None
        thread.user_id = None
        await session.commit()

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
    claimed = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-new",
        lease_seconds=60,
        limit=10,
    )

    stale_applied = await repo.apply_snapshot(
        "task-2",
        lease_owner="worker-old",
        lease_token=claimed[0]["lease_token"],
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
        lease_token=claimed[0]["lease_token"],
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

    stored = await repo.get("task-2", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
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
    claimed = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )

    applied = await repo.apply_snapshot(
        "task-expired",
        lease_owner="worker-1",
        lease_token=claimed[0]["lease_token"],
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
    stored = await repo.get("task-expired", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["status"] == "working"
    assert stored["result"] is None


@pytest.mark.asyncio
async def test_input_required_is_persisted_and_remains_scheduled_for_slow_polling(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-3", now=now)
    claimed = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )

    applied = await repo.apply_snapshot(
        "task-3",
        lease_owner="worker-1",
        lease_token=claimed[0]["lease_token"],
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

    stored = await repo.get("task-3", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["input_required"] == {"prompt": "Approve deployment?"}
    assert stored["notification_status"] == "pending"
    assert datetime.fromisoformat(stored["next_poll_at"]) == now + timedelta(seconds=60)


@pytest.mark.asyncio
async def test_release_claim_retries_transient_poll_failure(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-4", now=now)
    claimed = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-1",
        lease_seconds=60,
        limit=10,
    )
    retry_at = now + timedelta(seconds=30)

    released = await repo.release_claim(
        "task-4",
        lease_owner="worker-1",
        lease_token=claimed[0]["lease_token"],
        next_poll_at=retry_at,
        error="temporary network failure",
    )
    assert released is True

    stored = await repo.get("task-4", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["status"] == "working"
    assert stored["last_poll_error"] == "temporary network failure"
    assert datetime.fromisoformat(stored["next_poll_at"]) == retry_at
    assert stored["lease_owner"] is None


@pytest.mark.asyncio
async def test_release_claim_after_same_worker_reclaim_cannot_clear_new_claim(tmp_path):
    """A stale release from an older generation must be a no-op once the same
    worker reclaims the task with a fresh per-claim token (token fencing)."""
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-fence", now=now)
    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    old_token = claimed[0]["lease_token"]

    reclaim_at = now + timedelta(seconds=61)  # after the 60s lease expires
    reclaimed = await repo.claim_due_tasks(now=reclaim_at, lease_owner="worker-1", lease_seconds=61, limit=10)
    assert reclaimed
    new_token = reclaimed[0]["lease_token"]
    assert new_token != old_token

    # The stale release (old owner + old token) must not clear the new claim.
    released = await repo.release_claim(
        "task-fence",
        lease_owner="worker-1",
        lease_token=old_token,
        next_poll_at=reclaim_at + timedelta(seconds=30),
        error="stale release",
    )
    assert released is False

    stored = await repo.get("task-fence", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-1"
    assert stored["lease_token"] == new_token
    assert stored["lease_expires_at"] is not None


@pytest.mark.asyncio
async def test_apply_snapshot_after_same_worker_reclaim_cannot_clear_new_claim(tmp_path):
    """A poll snapshot from an older generation must not overwrite a newer claim."""
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-apply-fence", now=now)
    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    old_token = claimed[0]["lease_token"]

    reclaim_at = now + timedelta(seconds=61)
    reclaimed = await repo.claim_due_tasks(now=reclaim_at, lease_owner="worker-1", lease_seconds=61, limit=10)
    new_token = reclaimed[0]["lease_token"]
    assert new_token != old_token

    applied = await repo.apply_snapshot(
        "task-apply-fence",
        lease_owner="worker-1",
        lease_token=old_token,
        status="completed",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=reclaim_at,
    )
    assert applied is False

    stored = await repo.get("task-apply-fence", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-1"
    assert stored["lease_token"] == new_token
    assert stored["status"] == "working"


@pytest.mark.asyncio
async def test_apply_cancel_snapshot_after_same_worker_reclaim_cannot_clear_new_claim(tmp_path):
    """A cancel snapshot from an older generation must not overwrite a newer claim."""
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-cancel-fence", now=now)
    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    old_token = claimed[0]["lease_token"]

    reclaim_at = now + timedelta(seconds=61)
    reclaimed = await repo.claim_due_tasks(now=reclaim_at, lease_owner="worker-1", lease_seconds=61, limit=10)
    new_token = reclaimed[0]["lease_token"]
    assert new_token != old_token

    applied = await repo.apply_cancel_snapshot(
        "task-cancel-fence",
        lease_owner="worker-1",
        lease_token=old_token,
        status="cancelled",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        completed_at=reclaim_at,
    )
    assert applied is False

    stored = await repo.get("task-cancel-fence", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-1"
    assert stored["lease_token"] == new_token
    assert stored["status"] == "working"


@pytest.mark.asyncio
async def test_finish_notification_run_after_reclaim_cannot_clear_new_claim(tmp_path):
    """A stale notification finish must not clear a newer notification lease."""
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-notify-fence", now=now)
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify-fence",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        "task-notify-fence",
        lease_owner="notifier",
        notification_lease_token=first[0]["notification_lease_token"],
        dispatch_version=first[0]["dispatch_version"],
        run_id="notify-run-1",
        now=now,
    )
    reclaimed = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert reclaimed
    new_notify_token = reclaimed[0]["notification_lease_token"]

    finished = await repo.finish_notification_run(
        "task-notify-fence",
        lease_owner="notifier",
        notification_lease_token="stale-notify-token",
        dispatch_version=reclaimed[0]["dispatch_version"],
        delivered=True,
        next_notification_at=None,
        error=None,
        now=now,
    )
    assert finished is False

    stored = await repo.get("task-notify-fence", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["notification_lease_owner"] == "notifier"
    assert stored["notification_lease_token"] == new_notify_token


@pytest.mark.asyncio
async def test_release_poll_claim_after_cancellation_preserves_poll_failure_state(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-cancelled-poll", now=now)
    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    retry_at = now + timedelta(seconds=30)
    await repo.release_claim(
        "task-cancelled-poll",
        lease_owner="worker-1",
        lease_token=claimed[0]["lease_token"],
        next_poll_at=retry_at,
        error="temporary network failure",
    )
    before = await repo.get("task-cancelled-poll", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert before is not None

    reclaimed = await repo.claim_due_tasks(now=retry_at, lease_owner="worker-2", lease_seconds=60, limit=10)
    released = await repo.release_poll_claim_after_cancellation(
        "task-cancelled-poll",
        lease_owner="worker-2",
        lease_token=reclaimed[0]["lease_token"],
    )

    assert released is True
    stored = await repo.get("task-cancelled-poll", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["next_poll_at"] == before["next_poll_at"]
    assert stored["last_poll_error"] == before["last_poll_error"]
    assert stored["consecutive_poll_error_count"] == before["consecutive_poll_error_count"]
    assert stored["poll_attempt_count"] == before["poll_attempt_count"] + 1
    assert stored["lease_owner"] is None
    assert stored["lease_expires_at"] is None


@pytest.mark.asyncio
async def test_release_poll_claim_after_cancellation_requires_current_owner(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-stale-cancel", now=now)
    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-current", lease_seconds=60, limit=10)

    released = await repo.release_poll_claim_after_cancellation(
        "task-stale-cancel",
        lease_owner="worker-stale",
        lease_token=claimed[0]["lease_token"],
    )

    assert released is False
    stored = await repo.get("task-stale-cancel", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-current"
    assert stored["lease_expires_at"] is not None


@pytest.mark.asyncio
async def test_consecutive_poll_error_count_increments_and_resets_on_success(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-6", now=now)

    for expected_errors in (1, 2):
        claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
        await repo.release_claim(
            "task-6",
            lease_owner="worker-1",
            lease_token=claimed[0]["lease_token"],
            next_poll_at=now - timedelta(seconds=1),
            error="temporary network failure",
        )
        stored = await repo.get("task-6", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
        assert stored is not None
        assert stored["consecutive_poll_error_count"] == expected_errors

    claimed = await repo.claim_due_tasks(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    applied = await repo.apply_snapshot(
        "task-6",
        lease_owner="worker-1",
        lease_token=claimed[0]["lease_token"],
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

    stored = await repo.get("task-6", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["consecutive_poll_error_count"] == 0


@pytest.mark.asyncio
async def test_notification_snapshot_is_versioned_and_not_overwritten_in_flight(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-notify", now=now)
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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

    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
    changed = await repo.get("task-notify", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert changed is not None
    assert changed["event_version"] == 2
    assert changed["dispatch_version"] == 1
    assert changed["dispatch_event"]["status"] == "input_required"

    await repo.mark_notification_dispatched(
        "task-notify",
        lease_owner="notifier",
        notification_lease_token=first[0]["notification_lease_token"],
        dispatch_version=1,
        run_id="notify-run-1",
        now=now,
    )
    dispatched_claim = await repo.claim_notification_work(
        now=now,
        lease_owner="notifier",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    await repo.finish_notification_run(
        "task-notify",
        lease_owner="notifier",
        notification_lease_token=dispatched_claim[0]["notification_lease_token"],
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
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-retry-latest",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=first[0]["notification_lease_token"],
        dispatch_version=first[0]["dispatch_version"],
        run_id="notify-run-1",
        now=now,
    )
    dispatched_claim = await repo.claim_notification_work(
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
        notification_lease_token=dispatched_claim[0]["notification_lease_token"],
        dispatch_version=first[0]["dispatch_version"],
        delivered=False,
        next_notification_at=retry_at,
        error="Agent run failed",
        now=now,
    )
    failed = await repo.get("task-retry-latest", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert failed is not None
    assert failed["notification_status"] == "retry"
    assert failed["dispatch_attempt"] == 1
    assert failed["notification_attempt_count"] == 1

    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-retry-latest",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-notify-release",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
    claimed = await repo.claim_notification_work(
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
        notification_lease_token=claimed[0]["notification_lease_token"],
        next_notification_at=retry_at,
        error="run store unavailable",
    )

    stored = await repo.get("task-notify-release", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
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
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-launch-retry",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=first[0]["notification_lease_token"],
        next_notification_at=retry_at,
        error="run store unavailable",
        replace_with_latest=True,
        count_failure=True,
    )

    stored = await repo.get("task-launch-retry", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
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
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dead-letter",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=claimed[0]["notification_lease_token"],
        dispatch_version=claimed[0]["dispatch_version"],
        error="Thread deleted-thread not found",
        count_failure=True,
        now=now,
    )

    stored = await repo.get("task-dead-letter", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
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
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-budget",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=first[0]["notification_lease_token"],
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
        notification_lease_token=claimed[0]["notification_lease_token"],
        dispatch_version=dispatch_version,
        error="Notification delivery stopped after 5 failed attempts",
        count_failure=False,
        now=now,
    )

    stored = await repo.get("task-dispatched-budget", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["notification_status"] == "dead_letter"
    assert stored["notification_run_id"] is None


@pytest.mark.asyncio
async def test_dead_lettering_dispatched_snapshot_preserves_newer_event(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-dispatched-latest", now=now)
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-latest",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=first[0]["notification_lease_token"],
        dispatch_version=dispatch_version,
        run_id="notify-run-1",
        now=now,
    )

    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-dispatched-latest",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        notification_lease_token=claimed[0]["notification_lease_token"],
        dispatch_version=dispatch_version,
        error="old snapshot exhausted its retry budget",
        count_failure=False,
        now=now,
    )

    stored = await repo.get("task-dispatched-latest", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
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
    stale_poll_claim = await repo.claim_due_tasks(now=now, lease_owner="stale-poller", lease_seconds=60, limit=1)

    requested = await repo.request_cancel(
        "task-cancel",
        user_id="user-1",
        thread_id="thread-1",
        thread_incarnation=None,
        requested_at=now,
    )
    assert requested is not None
    assert await repo.claim_due_tasks(now=now, lease_owner="new-poller", lease_seconds=60, limit=1) == []
    assert (
        await repo.apply_snapshot(
            "task-cancel",
            lease_owner="stale-poller",
            lease_token=stale_poll_claim[0]["lease_token"],
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
        thread_incarnation=None,
        requested_at=now + timedelta(seconds=1),
    )
    assert repeated is not None
    assert repeated["lease_owner"] == "canceller"
    assert repeated["cancel_attempt_count"] == 1
    assert await repo.claim_cancel_requests(now=now, lease_owner="other", lease_seconds=60, limit=1) == []
    assert await repo.apply_cancel_snapshot(
        "task-cancel",
        lease_owner="canceller",
        lease_token=claimed[0]["lease_token"],
        status="cancelled",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        completed_at=now,
    )
    stored = await repo.get("task-cancel", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["status"] == "cancelled"
    assert stored["notification_status"] == "pending"


@pytest.mark.asyncio
async def test_late_poll_release_after_same_worker_reclaim_is_fenced(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-late-poll", now=now)

    first = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-same",
        lease_seconds=1,
        limit=10,
    )
    assert [row["id"] for row in first] == ["task-late-poll"]
    first_token = first[0]["lease_token"]
    assert first_token

    reclaimed = await repo.claim_due_tasks(
        now=now + timedelta(seconds=5),
        lease_owner="worker-same",
        lease_seconds=60,
        limit=10,
    )
    assert [row["id"] for row in reclaimed] == ["task-late-poll"]
    assert reclaimed[0]["lease_token"] != first_token

    released = await repo.release_poll_claim_after_cancellation(
        "task-late-poll",
        lease_owner="worker-same",
        lease_token=first_token,
    )
    assert released is False

    stored = await repo.get("task-late-poll", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-same"
    assert stored["lease_token"] == reclaimed[0]["lease_token"]


@pytest.mark.asyncio
async def test_late_cancel_release_after_same_worker_reclaim_is_fenced(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-late-cancel", now=now)
    await repo.request_cancel(
        "task-late-cancel",
        user_id="user-1",
        thread_id="thread-1",
        thread_incarnation=None,
        requested_at=now,
    )

    first = await repo.claim_cancel_requests(
        now=now,
        lease_owner="worker-same",
        lease_seconds=1,
        limit=1,
    )
    assert [row["id"] for row in first] == ["task-late-cancel"]
    first_token = first[0]["lease_token"]
    assert first_token

    reclaimed = await repo.claim_cancel_requests(
        now=now + timedelta(seconds=5),
        lease_owner="worker-same",
        lease_seconds=60,
        limit=1,
    )
    assert [row["id"] for row in reclaimed] == ["task-late-cancel"]
    assert reclaimed[0]["lease_token"] != first_token

    released = await repo.release_cancel_claim(
        "task-late-cancel",
        lease_owner="worker-same",
        lease_token=first_token,
        next_cancel_at=now + timedelta(seconds=30),
        error="cancelled",
    )
    assert released is False

    stored = await repo.get("task-late-cancel", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-same"
    assert stored["lease_token"] == reclaimed[0]["lease_token"]


@pytest.mark.asyncio
async def test_late_notification_release_after_same_worker_reclaim_is_fenced(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-late-notify", now=now)
    poll_claim = await repo.claim_due_tasks(now=now, lease_owner="poller", lease_seconds=60, limit=1)
    await repo.apply_snapshot(
        "task-late-notify",
        lease_owner="poller",
        lease_token=poll_claim[0]["lease_token"],
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
        lease_owner="notifier-same",
        lease_seconds=1,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert [row["id"] for row in first] == ["task-late-notify"]
    first_token = first[0]["notification_lease_token"]
    assert first_token

    reclaimed = await repo.claim_notification_work(
        now=now + timedelta(seconds=5),
        lease_owner="notifier-same",
        lease_seconds=60,
        limit=1,
        tracking_degraded_after_errors=3,
    )
    assert [row["id"] for row in reclaimed] == ["task-late-notify"]
    assert reclaimed[0]["notification_lease_token"] != first_token

    released = await repo.release_notification_lease(
        "task-late-notify",
        lease_owner="notifier-same",
        notification_lease_token=first_token,
        next_notification_at=now + timedelta(seconds=30),
        error="cancelled",
    )
    assert released is False

    stored = await repo.get("task-late-notify", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["notification_lease_owner"] == "notifier-same"
    assert stored["notification_lease_token"] == reclaimed[0]["notification_lease_token"]


@pytest.mark.asyncio
async def test_late_snapshot_apply_after_same_worker_reclaim_is_fenced(tmp_path):
    repo = await _make_repo(tmp_path)
    now = datetime.now(UTC)
    await _create_working_task(repo, task_id="task-late-apply", now=now)

    first = await repo.claim_due_tasks(
        now=now,
        lease_owner="worker-same",
        lease_seconds=1,
        limit=10,
    )
    first_token = first[0]["lease_token"]
    reclaimed = await repo.claim_due_tasks(
        now=now + timedelta(seconds=5),
        lease_owner="worker-same",
        lease_seconds=60,
        limit=10,
    )
    assert [row["id"] for row in reclaimed] == ["task-late-apply"]
    assert reclaimed[0]["lease_token"] != first_token

    applied = await repo.apply_snapshot(
        "task-late-apply",
        lease_owner="worker-same",
        lease_token=first_token,
        status="completed",
        result={"stale": True},
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
        polled_at=now + timedelta(seconds=5),
    )
    assert applied is False

    stored = await repo.get("task-late-apply", user_id="user-1", thread_id="thread-1", thread_incarnation=None)
    assert stored is not None
    assert stored["lease_owner"] == "worker-same"
    assert stored["lease_token"] == reclaimed[0]["lease_token"]
