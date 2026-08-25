from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run import RunRepository
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime import ConflictError

pytestmark = pytest.mark.asyncio


async def _seed_reuse_task(task_repo: ScheduledTaskRepository, *, task_id: str, now: datetime) -> dict:
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        context_mode="reuse_thread",
        assistant_id="lead_agent",
        title="Follow up",
        prompt="Continue from the existing conversation",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=now + timedelta(days=1),
    )
    task = await task_repo.get(task_id, user_id="user-1")
    assert task is not None
    return task


def _make_service(task_repo, run_repo, launch_run, *, queue_timeout_seconds: int = 3600):
    return ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=launch_run,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
        queue_timeout_seconds=queue_timeout_seconds,
    )


async def test_busy_reuse_thread_is_queued_then_launched_on_a_later_poll(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        task = await _seed_reuse_task(task_repo, task_id="task-queue", now=now)
        attempts = 0

        async def launch_run(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConflictError("Thread thread-1 already has an active run")
            return {"run_id": "run-queued", "thread_id": kwargs["thread_id"]}

        service = _make_service(task_repo, run_repo, launch_run)

        result = await service.dispatch_task(task, now=now, trigger="manual")

        assert result["outcome"] == "queued"
        rows = await run_repo.list_by_task("task-queue")
        assert len(rows) == 1
        assert rows[0]["status"] == "queued"
        assert rows[0]["attempt_count"] == 1

        await service.run_once(now=now + timedelta(seconds=5))

        rows = await run_repo.list_by_task("task-queue")
        assert rows[0]["status"] == "running"
        assert rows[0]["run_id"] == "run-queued"
        assert rows[0]["attempt_count"] == 2
        assert attempts == 2
    finally:
        await close_engine()


async def test_paused_task_manual_run_waits_for_busy_thread_and_stays_paused(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await _seed_reuse_task(task_repo, task_id="task-paused-manual", now=now)
        await task_repo.update(
            "task-paused-manual",
            user_id="user-1",
            updates={"status": "paused"},
        )
        task = await task_repo.get("task-paused-manual", user_id="user-1")
        assert task is not None
        attempts = 0

        async def launch_run(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConflictError("Thread thread-1 already has an active run")
            return {"run_id": "run-paused-manual", "thread_id": kwargs["thread_id"]}

        service = _make_service(task_repo, run_repo, launch_run)

        result = await service.dispatch_task(task, now=now, trigger="manual")

        assert result["outcome"] == "queued"
        assert (await run_repo.list_by_task(task["id"]))[0]["status"] == "queued"
        assert (await task_repo.get(task["id"], user_id="user-1"))["status"] == "paused"

        await service.run_once(now=now + timedelta(seconds=5))

        row = (await run_repo.list_by_task(task["id"]))[0]
        assert row["status"] == "running"
        assert row["run_id"] == "run-paused-manual"
        assert attempts == 2
        assert (await task_repo.get(task["id"], user_id="user-1"))["status"] == "paused"
    finally:
        await close_engine()


async def test_queued_run_survives_single_instance_restart_sweep(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        await run_repo.create(
            run_record_id="task-run-queued",
            task_id="task-queued",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )

        swept = await run_repo.mark_stale_active_runs(error="gateway restarted")

        assert swept == 0
        assert (await run_repo.list_by_task("task-queued"))[0]["status"] == "queued"
    finally:
        await close_engine()


async def test_only_one_worker_can_claim_a_queued_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo_a = ScheduledTaskRunRepository(sf)
        run_repo_b = ScheduledTaskRunRepository(sf)
        now = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        await run_repo_a.create(
            run_record_id="task-run-claim",
            task_id="task-claim",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )

        claims = await asyncio.gather(
            run_repo_a.claim_queued_run(
                "task-run-claim",
                lease_owner="worker-a",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            ),
            run_repo_b.claim_queued_run(
                "task-run-claim",
                lease_owner="worker-b",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            ),
        )

        assert sum(claim is not None for claim in claims) == 1
        row = (await run_repo_a.list_by_task("task-claim"))[0]
        assert row["status"] == "launching"
        assert row["attempt_count"] == 1
        assert row["lease_owner"] in {"worker-a", "worker-b"}
    finally:
        await close_engine()


async def test_same_thread_queue_is_claimed_in_fifo_order(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo_a = ScheduledTaskRunRepository(sf)
        run_repo_b = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        for run_id, task_id in (
            ("task-run-a", "task-a"),
            ("task-run-b", "task-b"),
        ):
            await run_repo_a.create(
                run_record_id=run_id,
                task_id=task_id,
                thread_id="shared-thread",
                scheduled_for=now,
                trigger="scheduled",
                status="queued",
            )

        newer = await run_repo_b.claim_queued_run(
            "task-run-b",
            lease_owner="worker-b",
            now=now,
            lease_seconds=120,
            global_max_concurrent_runs=3,
        )
        older = await run_repo_a.claim_queued_run(
            "task-run-a",
            lease_owner="worker-a",
            now=now,
            lease_seconds=120,
            global_max_concurrent_runs=3,
        )

        assert newer is None
        assert older is not None
        assert await run_repo_b.list_queued_runs(limit=10) == []
        assert (
            await run_repo_b.claim_queued_run(
                "task-run-b",
                lease_owner="worker-b",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            )
            is None
        )
    finally:
        await close_engine()


async def test_queue_drain_rotates_busy_thread_heads_without_breaking_fifo(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        for run_id, task_id, thread_id in (
            ("task-run-busy-old", "task-busy-old", "busy-thread"),
            ("task-run-busy-new", "task-busy-new", "busy-thread"),
            ("task-run-ready", "task-ready", "ready-thread"),
        ):
            await run_repo.create(
                run_record_id=run_id,
                task_id=task_id,
                thread_id=thread_id,
                scheduled_for=now,
                trigger="scheduled",
                status="queued",
            )

        claimed = await run_repo.claim_queued_run(
            "task-run-busy-old",
            lease_owner="worker-a",
            now=now,
            lease_seconds=120,
            global_max_concurrent_runs=3,
        )
        assert claimed is not None
        assert await run_repo.requeue_claimed_run(
            "task-run-busy-old",
            lease_owner="worker-a",
            error="thread is busy",
        )

        candidates = await run_repo.list_queued_runs(limit=10)

        # The untouched ready thread gets the next bounded-drain slot, and the
        # newer row for the busy thread stays hidden behind its FIFO head.
        assert [row["id"] for row in candidates] == [
            "task-run-ready",
            "task-run-busy-old",
        ]
    finally:
        await close_engine()


async def test_expired_launch_claim_is_requeued_but_waiting_timeout_fails(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await run_repo.create(
            run_record_id="task-run-stale-claim",
            task_id="task-stale-claim",
            thread_id="thread-1",
            scheduled_for=now - timedelta(minutes=5),
            trigger="scheduled",
            status="queued",
        )
        claimed = await run_repo.claim_queued_run(
            "task-run-stale-claim",
            lease_owner="dead-worker",
            now=now,
            lease_seconds=5,
            global_max_concurrent_runs=3,
        )
        assert claimed is not None

        reconciled = await run_repo.reconcile_active_runs(error="gateway lease expired", now=now + timedelta(seconds=6))

        assert reconciled == 1
        row = (await run_repo.list_by_task("task-stale-claim"))[0]
        assert row["status"] == "queued"
        assert row["lease_owner"] is None

        expired = await run_repo.expire_queued_runs(
            created_before=now + timedelta(seconds=7),
            error="queue wait timeout exceeded",
            now=now + timedelta(seconds=7),
        )
        assert [item["id"] for item in expired] == ["task-run-stale-claim"]
        assert (await run_repo.list_by_task("task-stale-claim"))[0]["status"] == "failed"
    finally:
        await close_engine()


async def test_slow_launch_is_reassociated_after_lease_recovery(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        task = await _seed_reuse_task(task_repo, task_id="task-slow-launch", now=now)
        queued = await run_repo.create(
            run_record_id="task-run-slow-launch",
            task_id=task["id"],
            thread_id="thread-1",
            scheduled_for=now,
            trigger="manual",
            status="queued",
        )
        launch_started = asyncio.Event()
        allow_launch_return = asyncio.Event()

        async def launch_run(**kwargs):
            launch_started.set()
            await allow_launch_return.wait()
            return {"run_id": "run-slow-launch", "thread_id": kwargs["thread_id"]}

        service = ScheduledTaskService(
            task_repo=task_repo,
            task_run_repo=run_repo,
            launch_run=launch_run,
            poll_interval_seconds=1,
            lease_seconds=5,
            max_concurrent_runs=3,
        )
        attempt = asyncio.create_task(service._attempt_queued_run(task, queued, now=now))
        await launch_started.wait()

        recovered = await run_repo.recover_expired_launch_claims(
            error="launch lease expired",
            now=now + timedelta(seconds=6),
        )
        assert recovered == 1
        assert (await run_repo.list_by_task(task["id"]))[0]["status"] == "queued"

        allow_launch_return.set()
        result = await attempt

        row = (await run_repo.list_by_task(task["id"]))[0]
        assert result["outcome"] == "launched"
        assert row["status"] == "running"
        assert row["run_id"] == "run-slow-launch"
        assert row["lease_owner"] is None
    finally:
        await close_engine()


async def test_failed_launch_releases_child_and_advances_parent_atomically(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="task-failed-launch-atomic",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Atomic failure",
            prompt="fail",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=now - timedelta(minutes=1),
        )
        await run_repo.create(
            run_record_id="task-run-failed-launch-atomic",
            task_id="task-failed-launch-atomic",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        assert (
            await run_repo.claim_queued_run(
                "task-run-failed-launch-atomic",
                lease_owner="worker-a",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            )
            is not None
        )

        failed, peer_claims = await asyncio.gather(
            run_repo.fail_launching_run(
                "task-run-failed-launch-atomic",
                task_id="task-failed-launch-atomic",
                lease_owner="worker-a",
                error="launch failed",
                now=now,
            ),
            task_repo.claim_due_tasks(
                now=now,
                lease_owner="worker-b",
                lease_seconds=120,
                limit=1,
            ),
        )

        assert failed is True
        assert peer_claims == []
        row = (await run_repo.list_by_task("task-failed-launch-atomic"))[0]
        task = await task_repo.get("task-failed-launch-atomic", user_id="user-1")
        assert row["status"] == "failed"
        assert task is not None
        assert datetime.fromisoformat(task["next_run_at"]) > now
        assert task["lease_owner"] is None
        assert task["last_error"] == "launch failed"
    finally:
        await close_engine()


async def test_failed_manual_launch_preserves_paused_next_run_at(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        next_run_at = now + timedelta(days=1)
        await task_repo.create(
            task_id="task-failed-manual-launch",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Manual launch failure",
            prompt="fail",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=next_run_at,
        )
        await task_repo.update(
            "task-failed-manual-launch",
            user_id="user-1",
            updates={"status": "paused"},
        )
        await run_repo.create(
            run_record_id="task-run-failed-manual-launch",
            task_id="task-failed-manual-launch",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="manual",
            status="queued",
        )
        assert (
            await run_repo.claim_queued_run(
                "task-run-failed-manual-launch",
                lease_owner="worker-a",
                now=now,
                lease_seconds=120,
                global_max_concurrent_runs=3,
            )
            is not None
        )

        assert await run_repo.fail_launching_run(
            "task-run-failed-manual-launch",
            task_id="task-failed-manual-launch",
            lease_owner="worker-a",
            error="launch failed",
            now=now,
        )

        row = (await run_repo.list_by_task("task-failed-manual-launch"))[0]
        task = await task_repo.get("task-failed-manual-launch", user_id="user-1")
        assert row["status"] == "failed"
        assert task is not None
        assert task["status"] == "paused"
        assert task["next_run_at"] == next_run_at.isoformat()
    finally:
        await close_engine()


async def test_pause_atomically_cancels_waiting_run_but_rejects_launching_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        now = datetime.now(UTC)
        await _seed_reuse_task(task_repo, task_id="task-pause-queued", now=now)
        await run_repo.create(
            run_record_id="task-run-pause-queued",
            task_id="task-pause-queued",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )

        result = await task_repo.pause_with_queue_cancellation(
            "task-pause-queued",
            user_id="user-1",
            error="paused while queued",
            now=now,
        )

        assert result == "paused"
        assert (await task_repo.get("task-pause-queued", user_id="user-1"))["status"] == "paused"
        assert (await run_repo.list_by_task("task-pause-queued"))[0]["status"] == "interrupted"

        await _seed_reuse_task(task_repo, task_id="task-pause-launching", now=now)
        await run_repo.create(
            run_record_id="task-run-pause-launching",
            task_id="task-pause-launching",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        await run_repo.claim_queued_run(
            "task-run-pause-launching",
            lease_owner="worker-a",
            now=now,
            lease_seconds=120,
            global_max_concurrent_runs=3,
        )

        result = await task_repo.pause_with_queue_cancellation(
            "task-pause-launching",
            user_id="user-1",
            error="paused while queued",
            now=now,
        )

        assert result == "executing"
        assert (await task_repo.get("task-pause-launching", user_id="user-1"))["status"] == "enabled"
        assert (await run_repo.list_by_task("task-pause-launching"))[0]["status"] == "launching"
    finally:
        await close_engine()


async def test_manual_enqueue_cannot_unpause_a_task_that_cancels_its_waiting_run(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)

        class DelayedCreateRunRepository(ScheduledTaskRunRepository):
            def __init__(self, session_factory):
                super().__init__(session_factory)
                self.created = asyncio.Event()
                self.resume_dispatch = asyncio.Event()

            async def create(self, **kwargs):
                row = await super().create(**kwargs)
                self.created.set()
                await self.resume_dispatch.wait()
                return row

        run_repo = DelayedCreateRunRepository(sf)
        now = datetime.now(UTC)
        task = await _seed_reuse_task(task_repo, task_id="task-manual-pause-race", now=now)

        async def launch_run(**_kwargs):
            raise AssertionError("a queued occurrence cancelled by pause must not launch")

        service = _make_service(task_repo, run_repo, launch_run)
        dispatch = asyncio.create_task(service.dispatch_task(task, now=now, trigger="manual"))
        await run_repo.created.wait()

        pause_result = await task_repo.pause_with_queue_cancellation(
            task["id"],
            user_id="user-1",
            error="paused while queued",
            now=now,
        )
        run_repo.resume_dispatch.set()
        result = await dispatch

        assert pause_result == "paused"
        assert result["outcome"] == "queued"
        assert (await task_repo.get(task["id"], user_id="user-1"))["status"] == "paused"
        assert (await run_repo.list_by_task(task["id"]))[0]["status"] == "interrupted"
    finally:
        await close_engine()


@pytest.mark.parametrize("action", ["pause", "delete"])
async def test_pause_or_delete_before_manual_admission_prevents_launch(tmp_path, action):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)

        class DelayedAdmissionRunRepository(ScheduledTaskRunRepository):
            def __init__(self, session_factory):
                super().__init__(session_factory)
                self.before_insert = asyncio.Event()
                self.resume_insert = asyncio.Event()

            async def create(self, **kwargs):
                self.before_insert.set()
                await self.resume_insert.wait()
                return await super().create(**kwargs)

        run_repo = DelayedAdmissionRunRepository(sf)
        now = datetime.now(UTC)
        task = await _seed_reuse_task(task_repo, task_id=f"task-{action}-before-admission", now=now)
        launches = []

        async def launch_run(**kwargs):
            launches.append(kwargs)
            return {"run_id": f"run-{action}", "thread_id": kwargs["thread_id"]}

        service = _make_service(task_repo, run_repo, launch_run)
        dispatch = asyncio.create_task(service.dispatch_task(task, now=now, trigger="manual"))
        await run_repo.before_insert.wait()

        if action == "pause":
            mutation = await task_repo.pause_with_queue_cancellation(
                task["id"],
                user_id="user-1",
                error="paused before admission",
                now=now + timedelta(seconds=1),
            )
            assert mutation == "paused"
        else:
            mutation = await task_repo.delete_with_queue_cancellation(
                task["id"],
                user_id="user-1",
                error="deleted before admission",
                now=now + timedelta(seconds=1),
            )
            assert mutation == "deleted"

        run_repo.resume_insert.set()
        result = await dispatch

        assert launches == []
        assert await run_repo.list_by_task(task["id"]) == []
        if action == "pause":
            assert result["outcome"] == "conflict"
            assert (await task_repo.get(task["id"], user_id="user-1"))["status"] == "paused"
        else:
            assert result["outcome"] == "not_found"
            assert await task_repo.get(task["id"], user_id="user-1") is None
    finally:
        await close_engine()


async def test_scheduled_queue_timeout_advances_cron_without_immediate_requeue(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        admitted_at = datetime.now(UTC)
        await task_repo.create(
            task_id="task-timeout",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Timeout",
            prompt="Prompt",
            schedule_type="cron",
            schedule_spec={"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=admitted_at - timedelta(minutes=1),
        )
        await run_repo.create(
            run_record_id="task-run-timeout",
            task_id="task-timeout",
            thread_id="thread-1",
            scheduled_for=admitted_at,
            trigger="scheduled",
            status="queued",
        )

        async def launch_run(**_kwargs):
            raise AssertionError("an expired queue row must not launch")

        service = _make_service(
            task_repo,
            run_repo,
            launch_run,
            queue_timeout_seconds=60,
        )
        poll_at = admitted_at + timedelta(seconds=61)

        await service.run_once(now=poll_at)

        rows = await run_repo.list_by_task("task-timeout")
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        task = await task_repo.get("task-timeout", user_id="user-1")
        assert task is not None
        assert task["status"] == "enabled"
        assert datetime.fromisoformat(task["next_run_at"]) > poll_at
        assert task["last_error"] == "scheduled task queue wait timeout exceeded"
    finally:
        await close_engine()


async def test_manual_queue_timeout_preserves_serialized_next_run_at(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        admitted_at = datetime.now(UTC)
        next_run_at = admitted_at + timedelta(days=1)
        await task_repo.create(
            task_id="task-manual-timeout",
            user_id="user-1",
            thread_id="thread-1",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Manual timeout",
            prompt="Prompt",
            schedule_type="cron",
            schedule_spec={"cron": "0 9 * * *"},
            timezone="UTC",
            next_run_at=next_run_at,
        )
        await run_repo.create(
            run_record_id="task-run-manual-timeout",
            task_id="task-manual-timeout",
            thread_id="thread-1",
            scheduled_for=admitted_at,
            trigger="manual",
            status="queued",
        )

        async def launch_run(**_kwargs):
            raise AssertionError("an expired queue row must not launch")

        service = _make_service(
            task_repo,
            run_repo,
            launch_run,
            queue_timeout_seconds=60,
        )

        await service.run_once(now=admitted_at + timedelta(seconds=61))

        row = (await run_repo.list_by_task("task-manual-timeout"))[0]
        assert row["status"] == "failed"
        task = await task_repo.get("task-manual-timeout", user_id="user-1")
        assert task is not None
        assert task["status"] == "enabled"
        assert task["next_run_at"] == next_run_at.isoformat()
        assert task["last_error"] == "scheduled task queue wait timeout exceeded"
    finally:
        await close_engine()


async def test_expired_launch_claim_attaches_existing_run_instead_of_relaunching(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        task_repo = ScheduledTaskRepository(sf)
        run_repo = ScheduledTaskRunRepository(sf)
        durable_runs = RunRepository(sf)
        now = datetime.now(UTC)
        launched_at = now + timedelta(seconds=1)
        await _seed_reuse_task(task_repo, task_id="task-attached", now=now)
        await run_repo.create(
            run_record_id="task-run-attached",
            task_id="task-attached",
            thread_id="thread-1",
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        assert (
            await run_repo.claim_queued_run(
                "task-run-attached",
                lease_owner="worker-a",
                now=now,
                lease_seconds=5,
                global_max_concurrent_runs=3,
            )
            is not None
        )
        assert await run_repo.requeue_claimed_run(
            "task-run-attached",
            lease_owner="worker-a",
            error="earlier overlap",
        )
        assert (
            await run_repo.claim_queued_run(
                "task-run-attached",
                lease_owner="worker-a",
                now=now,
                lease_seconds=5,
                global_max_concurrent_runs=3,
            )
            is not None
        )
        await durable_runs.put(
            "run-attached",
            thread_id="thread-1",
            user_id="user-1",
            status="running",
            metadata={
                "scheduled_task_id": "task-attached",
                "scheduled_task_run_id": "task-run-attached",
            },
            created_at=launched_at.isoformat(),
        )

        recovered = await run_repo.recover_expired_launch_claims(
            error="launch lease expired",
            now=now + timedelta(seconds=6),
        )

        assert recovered == 1
        row = (await run_repo.list_by_task("task-attached"))[0]
        assert row["status"] == "running"
        assert row["run_id"] == "run-attached"
        assert row["lease_owner"] is None
        assert row["started_at"] == launched_at.isoformat()
        assert row["error"] is None
        task = await task_repo.get("task-attached", user_id="user-1")
        assert task is not None
        assert task["last_run_id"] == "run-attached"
        assert task["run_count"] == 1

        # If the original launch coroutine resumes after recovery, its normal
        # parent update must be idempotent for the same durable run id.
        await task_repo.update_after_launch(
            "task-attached",
            status="enabled",
            next_run_at=datetime.fromisoformat(task["next_run_at"]),
            last_run_at=now,
            last_run_id="run-attached",
            last_thread_id="thread-1",
            last_error=None,
            increment_run_count=True,
        )
        assert (await task_repo.get("task-attached", user_id="user-1"))["run_count"] == 1
    finally:
        await close_engine()
