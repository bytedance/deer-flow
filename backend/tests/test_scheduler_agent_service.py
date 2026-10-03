"""Exercise task snapshots and notification commits through the real scheduler."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.scheduler.notification_delivery import render_notification_text
from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime import RunStatus


@pytest.fixture
async def scheduler(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    tasks, occurrences = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    deliveries, connections = NotificationDeliveryRepository(sf), ChannelConnectionRepository(sf)
    launches = []

    async def launch(**kwargs):
        launches.append(kwargs)
        run_id = f"run-{len(launches)}"
        async with sf() as session:
            session.add(RunRow(run_id=run_id, thread_id=kwargs["thread_id"], user_id=kwargs["owner_user_id"], status="running", metadata_json=kwargs["metadata"]))
            await session.commit()
        return {"run_id": run_id, "thread_id": kwargs["thread_id"]}

    service = ScheduledTaskService(task_repo=tasks, task_run_repo=occurrences, launch_run=launch, poll_interval_seconds=1, lease_seconds=120, max_concurrent_runs=3, connection_repo=connections, notification_repo=deliveries)
    try:
        yield sf, tasks, occurrences, service, launches, deliveries
    finally:
        await close_engine()


async def create_task(tasks, **extra):
    return await tasks.create(
        task_id="task-a",
        user_id="owner",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="Meeting preparation",
        prompt="Read the supplied materials and prepare the meeting.",
        schedule_type="interval",
        schedule_spec={"every_seconds": 3600},
        timezone="UTC",
        next_run_at=datetime.now(UTC),
        origin_thread_id="origin",
        **extra,
    )


async def finish(sf, service, launch, result, *, verdict=None):
    async with sf() as session:
        row = await session.get(RunRow, result["run_id"])
        row.status = "success"
        row.goal_verdict = verdict
        await session.commit()
    record = SimpleNamespace(run_id=result["run_id"], user_id="owner", metadata=launch["metadata"], status=RunStatus.success, error=None, goal_verdict=verdict)
    await service.handle_run_completion(record)


async def dispatch_scheduled(tasks, service):
    now = datetime.now(UTC)
    await tasks.update("task-a", user_id="owner", updates={"next_run_at": now})
    claimed = await tasks.claim_due_tasks(now=now, lease_owner=service._lease_owner, lease_seconds=120, limit=1)
    assert len(claimed) == 1
    return await service.dispatch_task(claimed[0], now=now, trigger="scheduled")


@pytest.mark.anyio
async def test_launch_snapshots_goal_and_explicit_task_notes(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    task = await create_task(tasks, goal_objective="Meeting preparation is complete", standing_notes=["Use the develop branch"])
    result = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    assert result["outcome"] == "launched"
    assert "Use the develop branch" in launches[0]["prompt"]
    assert launches[0]["metadata"]["scheduled_goal_objective"] == task["goal_objective"]
    async with sf() as session:
        rows = list((await session.scalars(select(NotificationDeliveryRow))).all())
        assert rows == []


@pytest.mark.anyio
async def test_next_fresh_occurrence_carries_only_the_previous_executed_thread(scheduler):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    task = await create_task(tasks)
    first = await service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
    await finish(sf, service, launches[0], first)
    current = await tasks.get("task-a", user_id="owner")
    second = await service.dispatch_task(current, now=datetime.now(UTC), trigger="manual")
    assert second["outcome"] == "launched"
    assert launches[1]["metadata"]["scheduled_previous_thread_id"] == first["thread_id"]
    assert second["thread_id"] != first["thread_id"]


@pytest.mark.anyio
async def test_auto_pause_and_notice_share_the_completion_transaction(scheduler, monkeypatch):
    sf, tasks, _occurrences, service, launches, deliveries = scheduler
    await create_task(tasks, goal_objective="Meeting preparation is complete")
    async with sf() as session:
        session.add(ChannelConnectionRow(id="owner-connection", owner_user_id="owner", provider="wecom", external_account_id="owner-wecom", status="connected"))
        session.add(ChannelConnectionRow(id="foreign-connection", owner_user_id="foreign", provider="wecom", external_account_id="foreign-wecom", status="connected"))
        await session.commit()
    verdict = {"satisfied": False, "blocker": "needs_user_input", "reason": "Required materials are missing", "relied_on_assumption": False, "stand_down_reason": "blocked:needs_user_input"}
    for _ in range(2):
        result = await dispatch_scheduled(tasks, service)
        await finish(sf, service, launches[-1], result, verdict=verdict)
    result = await dispatch_scheduled(tasks, service)
    original = deliveries.enqueue_in_session

    async def fail_notice(*args, **kwargs):
        if kwargs["event"] == "task_paused":
            raise RuntimeError("outbox temporarily unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(deliveries, "enqueue_in_session", fail_notice)
    with pytest.raises(RuntimeError, match="outbox temporarily unavailable"):
        await finish(sf, service, launches[-1], result, verdict=verdict)
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "enabled"
    monkeypatch.setattr(deliveries, "enqueue_in_session", original)
    await finish(sf, service, launches[-1], result, verdict=verdict)
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "paused"
    async with sf() as session:
        rows = list((await session.scalars(select(NotificationDeliveryRow))).all())
        assert [row.event for row in rows].count("task_paused") == 1
        assert {row.target for row in rows} == {"owner-wecom"}


def test_unmet_and_pause_notifications_have_distinct_safe_text():
    unmet = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": "blocked:needs_user_input", "error": "private raw failure"}})
    paused = render_notification_text({"event": "task_paused", "task_id": "task-a", "payload": {"reason_code": "consecutive_unmet"}})
    assert "goal was not met" in unmet
    assert "needs_user_input" in unmet
    assert "private raw failure" not in unmet
    assert "automatically paused" in paused
    assert "completed" not in unmet + paused


def test_assumption_marker_is_visible_without_forwarding_raw_error_text():
    text = render_notification_text({"event": "run_completed", "task_id": "task-a", "payload": {"relied_on_assumption": True, "result_summary": "Report is ready"}})
    assert "met, relying on stated assumptions" in text


@pytest.mark.anyio
async def test_end_reached_at_atomic_admission_reports_completed(scheduler, monkeypatch):
    _sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks)
    now = datetime.now(UTC)
    claimed = await tasks.claim_due_tasks(now=now, lease_owner=service._lease_owner, lease_seconds=120, limit=1)
    assert len(claimed) == 1
    # The preliminary check observed a live task; its deadline changes before
    # occurrence admission takes the authoritative parent lock.
    await tasks.update("task-a", user_id="owner", updates={"end_at": now - timedelta(seconds=1)})

    async def preliminary_check(*_args, **_kwargs):
        return False

    monkeypatch.setattr(tasks, "complete_if_ended", preliminary_check)
    result = await service.dispatch_task(claimed[0], now=now, trigger="scheduled")
    assert result["outcome"] == "completed"
    assert launches == []
    assert (await tasks.get("task-a", user_id="owner"))["status"] == "completed"


@pytest.mark.anyio
@pytest.mark.parametrize("outcomes", [("external_wait",) * 3, ("goal_not_met_yet", "goal_not_met_yet", "external_wait", "goal_not_met_yet")])
async def test_external_wait_does_not_advance_unmet_streak(scheduler, outcomes):
    sf, tasks, _occurrences, service, launches, _deliveries = scheduler
    await create_task(tasks, goal_objective="report is ready")
    for index, blocker in enumerate(outcomes):
        result = await dispatch_scheduled(tasks, service)
        verdict = {"satisfied": False, "blocker": blocker, "reason": "synthetic independent dependency", "stand_down_reason": f"blocked:{blocker}", "relied_on_assumption": False}
        await finish(sf, service, launches[-1], result, verdict=verdict)
        status = (await tasks.get("task-a", user_id="owner"))["status"]
        assert status == ("paused" if index == 3 else "enabled")


@pytest.mark.parametrize("reason", ["token_capped", "no_durable_end_of_turn", "thread_changed_after_evaluation", "thread_changed_before_continuation"])
def test_known_host_stand_down_reasons_are_reported(reason):
    text = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": reason}})
    assert f"Reason: `{reason}`" in text
