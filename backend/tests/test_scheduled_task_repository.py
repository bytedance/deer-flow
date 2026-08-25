import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run import RunRepository
from deerflow.persistence.scheduled_task_runs import (
    ActiveScheduledRunConflict,
    ScheduledTaskAdmissionRejected,
    ScheduledTaskRunRepository,
)
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict, ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow


@pytest.mark.asyncio
async def test_scheduled_task_repository_create_and_list(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    created = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize this thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="Asia/Shanghai",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )

    assert created["id"] == "task-1"
    listed = await repo.list_by_user("user-1")
    assert [task["id"] for task in listed] == ["task-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_mutable_update_rechecks_active_occurrence_at_commit_boundary(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="task-atomic-patch",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="atomic patch",
            prompt="original prompt",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )

        # Model the router's earlier fast-path check, then admit an occurrence
        # before the actual mutation reaches the repository transaction.
        assert await task_repo.get_active_run_status("task-atomic-patch") is None
        await run_repo.create(
            run_record_id="task-run-atomic-patch",
            task_id="task-atomic-patch",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="manual",
            status="queued",
        )

        with pytest.raises(ActiveScheduledTaskMutationConflict, match="active queued"):
            await task_repo.update(
                "task-atomic-patch",
                user_id="user-1",
                updates={"prompt": "changed after admission"},
                require_mutable=True,
            )

        task = await task_repo.get("task-atomic-patch", user_id="user-1")
        assert task is not None
        assert task["prompt"] == "original prompt"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_atomic_update_and_admission_cannot_both_commit(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)

        for index in range(5):
            task_id = f"task-update-admission-race-{index}"
            task = await task_repo.create(
                task_id=task_id,
                user_id="user-1",
                thread_id="thread-1",
                context_mode="reuse_thread",
                assistant_id="lead_agent",
                title="atomic race",
                prompt="original prompt",
                schedule_type="cron",
                schedule_spec={"cron": "0 9 * * *"},
                timezone="UTC",
                next_run_at=None,
            )

            update_result, admission_result = await asyncio.gather(
                task_repo.update(
                    task_id,
                    user_id="user-1",
                    updates={"prompt": "updated prompt"},
                    require_mutable=True,
                ),
                run_repo.create(
                    run_record_id=f"task-run-update-admission-race-{index}",
                    task_id=task_id,
                    thread_id="thread-1",
                    scheduled_for=datetime.now(UTC),
                    trigger="manual",
                    status="queued",
                    coordinate_with_task=True,
                    expected_task_user_id="user-1",
                    expected_task_status=task["status"],
                    expected_task_updated_at=task["updated_at"],
                ),
                return_exceptions=True,
            )

            successes = sum(not isinstance(result, Exception) for result in (update_result, admission_result))
            assert successes == 1
            assert isinstance(update_result, ActiveScheduledTaskMutationConflict) or isinstance(
                admission_result,
                ScheduledTaskAdmissionRejected,
            )

            current = await task_repo.get(task_id, user_id="user-1")
            assert current is not None
            active = await run_repo.get_active_run(task_id)
            assert (current["prompt"] == "updated prompt") is (active is None)
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_scheduled_task_run_repository_records_history(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    row = await repo.create(
        run_record_id="task-run-1",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="manual",
        status="queued",
    )

    assert row["id"] == "task-run-1"
    history = await repo.list_by_task("task-1")
    assert [entry["id"] for entry in history] == ["task-run-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_mark_stale_active_runs_preserves_queue_and_interrupts_live_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    # The queued and running rows live on different tasks: mark_stale_active_runs
    # is a global sweep (no task filter), and the uq_scheduled_task_run_active
    # partial unique index forbids two active rows on one task_id, so the pair
    # that proves both active statuses get swept must be spread across tasks.
    await repo.create(
        run_record_id="task-run-queued",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="queued",
    )
    await repo.create(
        run_record_id="task-run-running",
        task_id="task-2",
        thread_id="thread-2",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="running",
    )
    # A terminal row on task-1 (outside the index predicate) coexists with the
    # active queued row and must be left untouched by the sweep.
    await repo.create(
        run_record_id="task-run-success",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="success",
    )

    swept = await repo.mark_stale_active_runs(error="interrupted: gateway restarted")
    assert swept == 1

    by_id = {entry["id"]: entry for entry in await repo.list_by_task("task-1")}
    by_id.update({entry["id"]: entry for entry in await repo.list_by_task("task-2")})
    assert by_id["task-run-queued"]["status"] == "queued"
    assert by_id["task-run-running"]["status"] == "interrupted"
    assert by_id["task-run-success"]["status"] == "success"

    await close_engine()


@pytest.mark.asyncio
async def test_lease_aware_recovery_preserves_live_peer_and_reclaims_expired_peer(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf)
        durable_run_repo = RunRepository(sf)
        now = datetime.now(UTC)

        for suffix in ("live", "expired"):
            await task_repo.create(
                task_id=f"task-{suffix}",
                user_id="user-1",
                thread_id=None,
                context_mode="fresh_thread_per_run",
                assistant_id="lead_agent",
                title=suffix,
                prompt="p",
                schedule_type="cron",
                schedule_spec={"cron": "* * * * *"},
                timezone="UTC",
                next_run_at=None,
            )
            await task_run_repo.create(
                run_record_id=f"task-run-{suffix}",
                task_id=f"task-{suffix}",
                thread_id=f"thread-{suffix}",
                scheduled_for=now,
                trigger="scheduled",
                status="running",
            )
            await task_run_repo.update_status(f"task-run-{suffix}", status="running", run_id=f"run-{suffix}")

        await durable_run_repo.put(
            "run-live",
            thread_id="thread-live",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
        )
        await durable_run_repo.put(
            "run-expired",
            thread_id="thread-expired",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-dead",
            lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        )

        reconciled = await task_run_repo.reconcile_active_runs(error="restart", now=now)
        assert reconciled == 1
        assert (await task_run_repo.list_by_task("task-live"))[0]["status"] == "running"
        assert (await task_run_repo.list_by_task("task-expired"))[0]["status"] == "interrupted"
        recovered = await durable_run_repo.get("run-expired", user_id=None)
        assert recovered is not None
        assert recovered["status"] == "error"
        assert recovered["stop_reason"] == "scheduled_task_orphan_recovered"
        with pytest.raises(ActiveScheduledRunConflict):
            await task_run_repo.create(
                run_record_id="task-run-live-duplicate",
                task_id="task-live",
                thread_id="thread-new",
                scheduled_for=now,
                trigger="scheduled",
                status="queued",
            )
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_reconcile_live_launch_repairs_bookkeeping_before_releasing_claim(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        durable_run_repo = RunRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf, run_repository=durable_run_repo)
        now = datetime(2026, 8, 21, 1, 30, tzinfo=UTC)
        launched_at = now + timedelta(seconds=1)

        await task_repo.create(
            task_id="task-live-launch",
            user_id="user-1",
            thread_id="thread-live-launch",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="live launch",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await task_run_repo.create(
            run_record_id="task-run-live-launch",
            task_id="task-live-launch",
            thread_id="thread-live-launch",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        assert (
            await task_run_repo.claim_queued_run(
                "task-run-live-launch",
                lease_owner="pod-launcher",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            )
            is not None
        )
        assert await task_run_repo.requeue_claimed_run(
            "task-run-live-launch",
            lease_owner="pod-launcher",
            error="earlier overlap",
        )
        assert (
            await task_run_repo.claim_queued_run(
                "task-run-live-launch",
                lease_owner="pod-launcher",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            )
            is not None
        )
        await durable_run_repo.put(
            "run-live-launch",
            thread_id="thread-live-launch",
            user_id="user-1",
            status="running",
            metadata={
                "scheduled_task_id": "task-live-launch",
                "scheduled_task_run_id": "task-run-live-launch",
            },
            created_at=launched_at.isoformat(),
            owner_worker_id="pod-launcher",
            lease_expires_at=(now + timedelta(seconds=120)).isoformat(),
        )

        assert await task_run_repo.reconcile_active_runs(error="lease expired", now=now) == 0
        row = (await task_run_repo.list_by_task("task-live-launch"))[0]
        assert row["status"] == "running"
        assert row["run_id"] == "run-live-launch"
        assert row["lease_owner"] is None
        assert row["started_at"] == launched_at.isoformat()
        assert row["error"] is None

        # The original launcher is now fenced because reconciliation released
        # its short claim, but the stable row already contains all bookkeeping.
        assert not await task_run_repo.update_status(
            "task-run-live-launch",
            status="running",
            run_id="run-live-launch",
            started_at=launched_at,
            protect_terminal=True,
            expected_lease_owner="pod-launcher",
        )
        row = (await task_run_repo.list_by_task("task-live-launch"))[0]
        assert row["started_at"] == launched_at.isoformat()
        assert row["error"] is None
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_reconcile_locks_task_before_its_active_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        durable_run_repo = RunRepository(sf)
        now = datetime.now(UTC)

        seed_repo = ScheduledTaskRunRepository(sf)
        # Insert in reverse lexical order: every reconciler must still acquire
        # task/run pairs in one deterministic global order.
        for suffix in ("z", "a"):
            await task_repo.create(
                task_id=f"task-lock-order-{suffix}",
                user_id="user-1",
                thread_id=None,
                context_mode="fresh_thread_per_run",
                assistant_id="lead_agent",
                title="lock order",
                prompt="p",
                schedule_type="cron",
                schedule_spec={"cron": "* * * * *"},
                timezone="UTC",
                next_run_at=None,
            )
            await seed_repo.create(
                run_record_id=f"task-run-lock-order-{suffix}",
                task_id=f"task-lock-order-{suffix}",
                thread_id=f"thread-lock-order-{suffix}",
                scheduled_for=now,
                trigger="scheduled",
                status="queued",
            )
            assert (
                await seed_repo.claim_queued_run(
                    f"task-run-lock-order-{suffix}",
                    lease_owner="pod-a",
                    now=now,
                    lease_seconds=120,
                    global_max_concurrent_runs=3,
                )
                is not None
            )

        lock_order = []

        class RecordingSession:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                await self._session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self._session.__aexit__(*args)

            async def get(self, entity, ident, **kwargs):
                if kwargs.get("with_for_update"):
                    lock_order.append((entity, ident))
                return await self._session.get(entity, ident, **kwargs)

            def __getattr__(self, name):
                return getattr(self._session, name)

        def recording_session_factory():
            return RecordingSession(sf())

        reconcile_repo = ScheduledTaskRunRepository(
            recording_session_factory,
            run_repository=durable_run_repo,
        )

        assert await reconcile_repo.reconcile_active_runs(error="lease expired", now=now) == 0
        assert lock_order == [
            (ScheduledTaskRow, "task-lock-order-a"),
            (ScheduledTaskRunRow, "task-run-lock-order-a"),
            (ScheduledTaskRow, "task-lock-order-z"),
            (ScheduledTaskRunRow, "task-run-lock-order-z"),
        ]
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_lease_aware_recovery_preserves_queued_dispatch_until_lease_expires(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="task-queued",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="queued",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        assert await task_repo.claim_dispatch_lease("task-queued", lease_owner="worker-a", now=now, lease_seconds=120) is not None
        assert await task_repo.claim_dispatch_lease("task-queued", lease_owner="worker-b", now=now, lease_seconds=120) is None
        await task_run_repo.create(
            run_record_id="task-run-queued-live",
            task_id="task-queued",
            thread_id="thread-queued",
            scheduled_for=now,
            trigger="manual",
            status="queued",
        )

        assert await task_run_repo.reconcile_active_runs(error="restart", now=now) == 0
        assert (await task_run_repo.list_by_task("task-queued"))[0]["status"] == "queued"
        assert await task_run_repo.reconcile_active_runs(error="restart", now=now + timedelta(seconds=121)) == 0
        assert (await task_run_repo.list_by_task("task-queued"))[0]["status"] == "queued"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_lease_aware_recovery_uses_parent_last_run_when_row_link_is_missing(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf)
        durable_run_repo = RunRepository(sf)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="task-missing-link",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="missing link",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await task_repo.update("task-missing-link", user_id="user-1", updates={"last_run_id": "run-peer"})
        await task_run_repo.create(
            run_record_id="task-run-missing-link",
            task_id="task-missing-link",
            thread_id="thread-peer",
            scheduled_for=now,
            trigger="scheduled",
            status="running",
        )
        await durable_run_repo.put(
            "run-peer",
            thread_id="thread-peer",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
        )

        assert await task_run_repo.reconcile_active_runs(error="restart", now=now) == 0
        assert (await task_run_repo.list_by_task("task-missing-link"))[0]["status"] == "running"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_status_protect_terminal_keeps_completion_result(tmp_path):
    """The launch-path "running" write must not clobber a terminal status
    already committed by the completion hook (launch/completion race)."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    await repo.create(
        run_record_id="task-run-race",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="queued",
    )
    claimed_at = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)
    claimed = await repo.claim_queued_run(
        "task-run-race",
        lease_owner="worker-a",
        now=claimed_at,
        lease_seconds=120,
        global_max_concurrent_runs=3,
    )
    assert claimed is not None
    # Completion hook wins the race and commits the terminal state first.
    await repo.update_status("task-run-race", status="failed", run_id="run-1", error="boom", finished_at=datetime(2026, 7, 2, 1, 1, tzinfo=UTC))
    # Late launch-path write: completion cleared the launch lease, but the
    # matching run id proves this is the same launch and permits the missing
    # started_at backfill without weakening fencing for another run.
    updated = await repo.update_status(
        "task-run-race",
        status="running",
        run_id="run-1",
        started_at=claimed_at,
        protect_terminal=True,
        expected_lease_owner="worker-a",
    )

    entry = (await repo.list_by_task("task-1"))[0]
    assert updated is True
    assert entry["status"] == "failed"
    assert entry["error"] == "boom"
    assert entry["started_at"] is not None

    stale = await repo.update_status(
        "task-run-race",
        status="running",
        run_id="run-stale",
        started_at=claimed_at - timedelta(minutes=1),
        protect_terminal=True,
        expected_lease_owner="worker-stale",
    )
    assert stale is False
    entry = (await repo.list_by_task("task-1"))[0]
    assert entry["run_id"] == "run-1"
    assert entry["started_at"] == claimed_at.isoformat()

    await close_engine()


@pytest.mark.asyncio
async def test_has_active_runs_sees_all_nonterminal_queue_states(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    assert await repo.has_active_runs("task-1") is False
    await repo.create(
        run_record_id="task-run-active",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="scheduled",
        status="running",
    )
    assert await repo.has_active_runs("task-1") is True
    await repo.update_status("task-run-active", status="launching")
    assert await repo.has_active_runs("task-1") is True
    await repo.update_status("task-run-active", status="success", run_id="run-1")
    assert await repo.has_active_runs("task-1") is False

    await close_engine()


@pytest.mark.asyncio
async def test_cancel_stuck_once_tasks_reconciles_orphaned_running(tmp_path):
    """Launched (lease cleared) once tasks stuck in running are cancelled at
    startup; leased ones are left for expired-lease reclaim."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    for task_id, schedule_type, status in (
        ("task-once-stuck", "once", "running"),
        ("task-once-done", "once", "completed"),
        ("task-cron-running", "cron", "running"),
    ):
        await repo.create(
            task_id=task_id,
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title=task_id,
            prompt="p",
            schedule_type=schedule_type,
            schedule_spec={"run_at": "2026-07-02T01:00:00+00:00"} if schedule_type == "once" else {"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await repo.update(task_id, user_id="user-1", updates={"status": status})
    # A claimed-but-not-launched once task still holds its lease: keep it.
    await repo.create(
        task_id="task-once-leased",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="task-once-leased",
        prompt="p",
        schedule_type="once",
        schedule_spec={"run_at": "2026-07-02T01:00:00+00:00"},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )
    await repo.update("task-once-leased", user_id="user-1", updates={"status": "running", "lease_expires_at": datetime(2026, 7, 2, 1, 2, tzinfo=UTC)})

    cancelled = await repo.cancel_stuck_once_tasks(error="interrupted: gateway restarted")
    assert cancelled == 1

    by_id = {t["id"]: t for t in await repo.list_by_user("user-1")}
    assert by_id["task-once-stuck"]["status"] == "cancelled"
    assert by_id["task-once-stuck"]["last_error"] == "interrupted: gateway restarted"
    assert by_id["task-once-done"]["status"] == "completed"
    assert by_id["task-cron-running"]["status"] == "running"
    assert by_id["task-once-leased"]["status"] == "running"

    await close_engine()


@pytest.mark.asyncio
async def test_lease_aware_once_recovery_keeps_live_peer_and_cancels_dead_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        durable_run_repo = RunRepository(sf)
        now = datetime.now(UTC)
        for suffix in ("live", "dead"):
            await task_repo.create(
                task_id=f"task-once-{suffix}",
                user_id="user-1",
                thread_id=None,
                context_mode="fresh_thread_per_run",
                assistant_id="lead_agent",
                title=suffix,
                prompt="p",
                schedule_type="once",
                schedule_spec={"run_at": (now + timedelta(minutes=5)).isoformat()},
                timezone="UTC",
                next_run_at=None,
            )
            await task_repo.update(
                f"task-once-{suffix}",
                user_id="user-1",
                updates={"status": "running", "last_run_id": f"run-once-{suffix}"},
            )

        await durable_run_repo.put(
            "run-once-live",
            thread_id="thread-live",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
        )
        await durable_run_repo.put(
            "run-once-dead",
            thread_id="thread-dead",
            user_id="user-1",
            status="error",
            owner_worker_id="worker-dead",
            lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        )

        assert await task_repo.reconcile_stuck_once_tasks(error="restart", now=now) == 1
        live = await task_repo.get("task-once-live", user_id="user-1")
        dead = await task_repo.get("task-once-dead", user_id="user-1")
        assert live is not None and live["status"] == "running"
        assert dead is not None and dead["status"] == "cancelled"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_lease_aware_once_recovery_reclaims_expired_dispatch_lease(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        repo = ScheduledTaskRepository(sf)
        now = datetime.now(UTC)
        await repo.create(
            task_id="task-once-expired-lease",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="expired lease",
            prompt="p",
            schedule_type="once",
            schedule_spec={"run_at": now.isoformat()},
            timezone="UTC",
            next_run_at=now,
        )
        await repo.update(
            "task-once-expired-lease",
            user_id="user-1",
            updates={"status": "running", "lease_expires_at": now - timedelta(seconds=60)},
        )

        assert await repo.reconcile_stuck_once_tasks(error="restart", now=now) == 1
        task = await repo.get("task-once-expired-lease", user_id="user-1")
        assert task is not None and task["status"] == "cancelled"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_after_launch_protect_terminal_keeps_hook_result(tmp_path):
    """The launch-path bookkeeping write must not clobber a terminal task
    status committed first by the completion hook (fast-failing run)."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    await repo.create(
        task_id="task-race",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="task-race",
        prompt="p",
        schedule_type="once",
        schedule_spec={"run_at": "2026-07-02T01:00:00+00:00"},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )
    # Completion hook wins the race: task finalized as failed.
    await repo.update("task-race", user_id="user-1", updates={"status": "failed", "last_error": "boom"})
    # Late launch-path write with protection keeps the hook's outcome.
    await repo.update_after_launch(
        "task-race",
        status="running",
        next_run_at=None,
        last_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        last_run_id="run-1",
        last_thread_id="thread-1",
        last_error=None,
        increment_run_count=True,
        protect_terminal=True,
    )

    task = await repo.get("task-race", user_id="user-1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["last_error"] == "boom"
    # Launch bookkeeping still recorded.
    assert task["last_run_id"] == "run-1"
    assert task["run_count"] == 1

    await close_engine()


@pytest.mark.asyncio
async def test_update_after_launch_coerces_serialized_last_run_at(tmp_path):
    """Task rows returned by the repository serialize timestamps as ISO strings."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    await repo.create(
        task_id="task-serialized-timestamp",
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="serialized timestamp",
        prompt="p",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )

    await repo.update_after_launch(
        "task-serialized-timestamp",
        status="enabled",
        next_run_at=datetime(2026, 7, 3, 1, 0, tzinfo=UTC),
        last_run_at="2026-07-02T01:00:00+00:00",
        last_run_id="run-serialized",
        last_thread_id="thread-serialized",
        last_error=None,
        increment_run_count=True,
    )

    task = await repo.get("task-serialized-timestamp", user_id="user-1")
    assert task is not None
    assert task["last_run_at"] == "2026-07-02T01:00:00+00:00"

    await close_engine()


@pytest.mark.asyncio
async def test_list_by_task_paginates(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    for i in range(5):
        await repo.create(
            run_record_id=f"task-run-{i}",
            task_id="task-1",
            thread_id="thread-1",
            scheduled_for=datetime(2026, 7, 2, 1, i, tzinfo=UTC),
            trigger="scheduled",
            status="success",
        )

    assert await repo.count_active_runs() == 0
    page1 = await repo.list_by_task("task-1", limit=2)
    page2 = await repo.list_by_task("task-1", limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {e["id"] for e in page1}.isdisjoint({e["id"] for e in page2})

    await close_engine()


@pytest.mark.asyncio
async def test_list_by_user_and_thread_filters_in_sql(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    for task_id, thread_id in (("task-a", "thread-1"), ("task-b", "thread-2"), ("task-c", "thread-1")):
        await repo.create(
            task_id=task_id,
            user_id="user-1",
            thread_id=thread_id,
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title=task_id,
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=None,
        )

    listed = await repo.list_by_user_and_thread("user-1", "thread-1")
    assert sorted(t["id"] for t in listed) == ["task-a", "task-c"]
    assert await repo.list_by_user_and_thread("user-2", "thread-1") == []

    await close_engine()


@pytest.mark.asyncio
async def test_reconcile_recovers_live_run_link_from_metadata(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf)
        run_repo = RunRepository(sf)
        now = datetime.now(UTC)

        await task_repo.create(
            task_id="task-metadata-link",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="metadata fallback",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await task_run_repo.create(
            run_record_id="task-run-metadata-link",
            task_id="task-metadata-link",
            thread_id="thread-metadata-link",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        await run_repo.put(
            "run-metadata-link",
            thread_id="thread-metadata-link",
            user_id="user-1",
            status="running",
            metadata={
                "scheduled_task_id": "task-metadata-link",
                "scheduled_task_run_id": "task-run-metadata-link",
            },
            owner_worker_id="worker-a",
            lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
        )

        assert await task_run_repo.reconcile_active_runs(error="lease expired", now=now) == 0
        row = (await task_run_repo.list_by_task("task-metadata-link"))[0]
        assert row["status"] == "queued"
        assert row["run_id"] is None
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_reconcile_ignores_stale_parent_last_run_before_metadata_fallback(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf)
        run_repo = RunRepository(sf)
        now = datetime.now(UTC)

        await task_repo.create(
            task_id="task-stale-parent-link",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="stale parent link",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await task_run_repo.create(
            run_record_id="task-run-current",
            task_id="task-stale-parent-link",
            thread_id="thread-current",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        await task_repo.update("task-stale-parent-link", user_id="user-1", updates={"last_run_id": "run-previous"})
        await run_repo.put(
            "run-previous",
            thread_id="thread-previous",
            user_id="user-1",
            status="success",
            metadata={"scheduled_task_id": "task-stale-parent-link", "scheduled_task_run_id": "task-run-previous"},
        )
        await run_repo.put(
            "run-current",
            thread_id="thread-current",
            user_id="user-1",
            status="running",
            metadata={
                "scheduled_task_id": "task-stale-parent-link",
                "scheduled_task_run_id": "task-run-current",
            },
            owner_worker_id="worker-a",
            lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
        )

        assert await task_run_repo.reconcile_active_runs(error="lease expired", now=now) == 0
        assert (await task_run_repo.list_by_task("task-stale-parent-link"))[0]["status"] == "queued"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_reconcile_preserves_row_when_heartbeat_wins_takeover(tmp_path):
    class RenewedRunRepository:
        async def claim_for_takeover(self, *_args, **_kwargs):
            return False

        async def get(self, *_args, **_kwargs):
            return {"status": "running"}

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        task_run_repo = ScheduledTaskRunRepository(sf, run_repository=RenewedRunRepository())
        run_repo = RunRepository(sf)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="task-heartbeat-race",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="heartbeat race",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await task_run_repo.create(
            run_record_id="task-run-heartbeat-race",
            task_id="task-heartbeat-race",
            thread_id="thread-heartbeat-race",
            scheduled_for=now,
            trigger="scheduled",
            status="running",
        )
        await task_run_repo.update_status(
            "task-run-heartbeat-race",
            status="running",
            run_id="run-heartbeat-race",
        )
        await run_repo.put(
            "run-heartbeat-race",
            thread_id="thread-heartbeat-race",
            user_id="user-1",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        )

        assert await task_run_repo.reconcile_active_runs(error="lease expired", now=now) == 0
        row = (await task_run_repo.list_by_task("task-heartbeat-race"))[0]
        assert row["status"] == "running"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_after_launch_rejects_stale_lease_owner(tmp_path, caplog):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        repo = ScheduledTaskRepository(sf)
        now = datetime.now(UTC)
        await repo.create(
            task_id="task-fenced",
            user_id="user-1",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="fenced",
            prompt="p",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=now,
        )
        assert await repo.claim_dispatch_lease("task-fenced", lease_owner="worker-a", now=now, lease_seconds=60) is not None
        await repo.update(
            "task-fenced",
            user_id="user-1",
            updates={
                "lease_owner": "worker-b",
                "lease_expires_at": now + timedelta(seconds=120),
            },
        )

        with caplog.at_level("WARNING", logger="deerflow.persistence.scheduled_tasks.sql"):
            updated = await repo.update_after_launch(
                "task-fenced",
                status="enabled",
                next_run_at=now + timedelta(minutes=1),
                last_run_at=now,
                last_run_id="run-a",
                last_thread_id="thread-a",
                last_error=None,
                increment_run_count=True,
                expected_lease_owner="worker-a",
            )
        assert updated is False
        assert "task-fenced" in caplog.text
        assert "expected lease owner worker-a, current owner worker-b" in caplog.text
        task = await repo.get("task-fenced", user_id="user-1")
        assert task is not None
        assert task["lease_owner"] == "worker-b"
        assert task["last_run_id"] is None
        assert task["run_count"] == 0
    finally:
        await close_engine()
