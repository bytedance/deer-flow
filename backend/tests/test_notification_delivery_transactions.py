"""Notification obligations must share the occurrence's commit boundary."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow


@pytest.fixture
async def delivery_repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}", sqlite_dir=str(tmp_path))
    try:
        yield NotificationDeliveryRepository(get_session_factory())
    finally:
        await close_engine()


def delivery_args(**overrides):
    return {
        "task_id": "task-a",
        "task_run_id": "occurrence-a",
        "run_id": "run-a",
        "event": "task_paused",
        "provider": "wecom",
        "target": "alice-external",
        "owner_user_id": "alice",
        "payload": {"reason_code": "consecutive_unmet"},
        **overrides,
    }


@pytest.mark.anyio
async def test_delivery_is_not_visible_until_occurrence_transaction_commits(delivery_repo):
    async with delivery_repo.session_factory() as session:
        inserted = await delivery_repo.enqueue_in_session(session, **delivery_args())
        assert inserted["status"] == "pending"
        async with delivery_repo.session_factory() as reader:
            assert await reader.scalar(select(func.count()).select_from(NotificationDeliveryRow)) == 0
        await session.commit()
    claimed = await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)
    assert [row["id"] for row in claimed] == [inserted["id"]]


@pytest.mark.anyio
async def test_rollback_cannot_leave_a_pause_notification_without_the_pause(delivery_repo):
    async with delivery_repo.session_factory() as session:
        await delivery_repo.enqueue_in_session(session, **delivery_args())
        await session.rollback()
    assert await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5) == []


@pytest.mark.anyio
async def test_completion_replay_preserves_the_first_delivery_payload(delivery_repo):
    async with delivery_repo.session_factory() as session:
        first = await delivery_repo.enqueue_in_session(session, **delivery_args())
        second = await delivery_repo.enqueue_in_session(session, **delivery_args(payload={"reason_code": "different"}))
        assert first["id"] == second["id"]
        assert second["payload"] == first["payload"]
        await session.commit()
    assert len(await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)) == 1


@pytest.mark.anyio
async def test_one_occurrence_can_commit_unmet_and_pause_notices_together(delivery_repo):
    async with delivery_repo.session_factory() as session:
        await delivery_repo.enqueue_in_session(session, **delivery_args(event="run_unmet"))
        await delivery_repo.enqueue_in_session(session, **delivery_args(event="task_paused"))
        await session.commit()
    claimed = await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)
    assert {row["event"] for row in claimed} == {"run_unmet", "task_paused"}


@pytest.mark.anyio
async def test_observer_notice_commits_and_rolls_back_with_complete_run(delivery_repo):
    """The finalization observer stages the v2 notice inside complete_run's transaction."""
    from app.scheduler.service import ScheduledTaskService
    from deerflow.persistence.channel_connections import ChannelConnectionRepository
    from deerflow.persistence.channel_connections.model import ChannelConnectionRow
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

    sf = delivery_repo.session_factory
    tasks, runs = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    service = ScheduledTaskService(task_repo=tasks, task_run_repo=runs, launch_run=None, poll_interval_seconds=60, lease_seconds=30, max_concurrent_runs=3, connection_repo=ChannelConnectionRepository(sf), notification_repo=delivery_repo)
    now = datetime(2026, 10, 6, 8, tzinfo=UTC)
    await tasks.create(
        task_id="task-a",
        user_id="alice",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=None,
        title="Digest",
        prompt="Summarize.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=now,
    )
    await runs.create(run_record_id="occurrence-a", task_id="task-a", thread_id="thread-a", scheduled_for=now, trigger="scheduled", status="running")
    await runs.update_status("occurrence-a", status="running", run_id="run-a", started_at=now)
    async with sf() as session:
        session.add(ChannelConnectionRow(id="binding", owner_user_id="alice", provider="wecom", status="connected", external_account_id="alice-external"))
        await session.commit()

    async def fails_after_enqueue(session, task, occurrence, *, events):
        await service._on_finalization(session, task, occurrence, events=events)
        assert await session.scalar(select(func.count()).select_from(NotificationDeliveryRow)) == 1
        raise RuntimeError("commit interrupted")

    def complete():
        return tasks.complete_run("task-a", user_id="alice", task_run_id="occurrence-a", run_id="run-a", status="success", error=None, finished_at=now)

    tasks.set_finalization_observer(fails_after_enqueue)
    with pytest.raises(RuntimeError, match="commit interrupted"):
        await complete()
    # The notice rolled back with the outcome; the occurrence is still active.
    assert await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5) == []
    assert (await runs.list_by_task("task-a"))[0]["status"] == "running"

    tasks.set_finalization_observer(service._on_finalization)
    assert await complete() is True
    (claimed,) = await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)
    assert (claimed["event"], claimed["task_run_id"], claimed["run_id"]) == ("run_completed", "occurrence-a", "run-a")
    assert claimed["payload"] == {"payload_version": 2, "task_id": "task-a", "task_title": "Digest", "locale": None, "reason_code": None, "latest_reason_code": None, "run_status": "success"}
