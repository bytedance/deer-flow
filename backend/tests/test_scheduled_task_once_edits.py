from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.gateway.scheduled_task_validation import _recompute_schedule
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.mark.parametrize("status", ["enabled", "paused"])
@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai"])
def test_unchanged_once_schedule_can_be_saved_inside_minimum_delay(status, timezone):
    now = datetime(2027, 1, 1, tzinfo=UTC)
    run_at = now + timedelta(seconds=30)
    existing = {
        "schedule_type": "once",
        "schedule_spec": {"run_at": run_at.isoformat()},
        "timezone": timezone,
        "status": status,
        "next_run_at": run_at.isoformat(),
    }
    updates = {"title": "Updated title", "prompt": "Updated instructions", "schedule_spec": dict(existing["schedule_spec"]), "timezone": timezone}

    _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(min_once_delay_seconds=60), now=now)

    assert updates["next_run_at"] == run_at
    assert updates["title"] == "Updated title"
    assert updates["prompt"] == "Updated instructions"
    assert "status" not in updates


@pytest.mark.parametrize("status", ["enabled", "paused", "completed", "failed", "cancelled"])
def test_changed_once_schedule_still_requires_minimum_delay(status):
    now = datetime(2027, 1, 1, tzinfo=UTC)
    original = now + timedelta(hours=1)
    existing = {
        "schedule_type": "once",
        "schedule_spec": {"run_at": original.isoformat()},
        "timezone": "UTC",
        "status": status,
        "next_run_at": original.isoformat(),
    }
    updates = {"schedule_spec": {"run_at": (now + timedelta(seconds=30)).isoformat()}}

    with pytest.raises(HTTPException) as error:
        _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(min_once_delay_seconds=60), now=now)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "once_too_soon"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_rearming_once_schedule_still_requires_minimum_delay(status):
    now = datetime(2027, 1, 1, tzinfo=UTC)
    run_at = now + timedelta(seconds=30)
    existing = {
        "schedule_type": "once",
        "schedule_spec": {"run_at": run_at.isoformat()},
        "timezone": "UTC",
        "status": status,
        "next_run_at": run_at.isoformat(),
    }
    updates = {"schedule_spec": dict(existing["schedule_spec"])}

    with pytest.raises(HTTPException) as error:
        _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(min_once_delay_seconds=60), now=now)

    assert error.value.detail["code"] == "once_too_soon"


@pytest.mark.parametrize("run_at", ["2027-01-01T08:00:30", "2027-01-01T08:00:30+08:00"])
def test_unchanged_once_schedule_compares_execution_instants(run_at):
    now = datetime(2027, 1, 1, tzinfo=UTC)
    upcoming = now + timedelta(seconds=30)
    existing = {
        "schedule_type": "once",
        "schedule_spec": {"run_at": run_at},
        "timezone": "Asia/Shanghai",
        "status": "enabled",
        "next_run_at": upcoming.isoformat(),
    }
    updates = {"schedule_spec": {"run_at": upcoming.isoformat()}}

    _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(), now=now)

    assert updates["next_run_at"] == upcoming


def test_unchanged_once_schedule_in_the_past_is_still_rejected():
    now = datetime(2027, 1, 1, tzinfo=UTC)
    run_at = now - timedelta(seconds=30)
    existing = {
        "schedule_type": "once",
        "schedule_spec": {"run_at": run_at.isoformat()},
        "timezone": "UTC",
        "status": "enabled",
        "next_run_at": run_at.isoformat(),
    }
    updates = {"schedule_spec": dict(existing["schedule_spec"])}

    with pytest.raises(HTTPException) as error:
        _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(), now=now)

    assert error.value.detail["code"] == "once_in_past"


@pytest.mark.asyncio
async def test_saved_once_edit_keeps_the_original_due_time(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        repo = ScheduledTaskRepository(get_session_factory())
        now = datetime.now(UTC)
        run_at = now + timedelta(seconds=30)
        existing = await repo.create(
            task_id="once-edit",
            user_id="owner",
            thread_id=None,
            context_mode="fresh_thread_per_run",
            assistant_id="lead_agent",
            title="Original title",
            prompt="Original instructions",
            schedule_type="once",
            schedule_spec={"run_at": run_at.isoformat()},
            timezone="UTC",
            next_run_at=run_at,
        )
        updates = {"title": "Updated title", "prompt": "Updated instructions", "schedule_spec": dict(existing["schedule_spec"]), "timezone": existing["timezone"]}

        _recompute_schedule(existing, updates, scheduler_config=SchedulerConfig(), now=now)
        await repo.update("once-edit", user_id="owner", updates=updates, require_mutable=True)

        stored = await repo.get("once-edit", user_id="owner")
        assert stored["title"] == "Updated title"
        assert stored["prompt"] == "Updated instructions"
        assert datetime.fromisoformat(stored["next_run_at"]) == run_at
        assert await repo.claim_due_tasks(now=run_at - timedelta(seconds=1), lease_owner="worker", lease_seconds=120, limit=10) == []
        due = await repo.claim_due_tasks(now=run_at, lease_owner="worker", lease_seconds=120, limit=10)
        assert [task["id"] for task in due] == ["once-edit"]
    finally:
        await close_engine()
