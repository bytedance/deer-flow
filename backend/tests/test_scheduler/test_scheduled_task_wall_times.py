"""HTTP and conversation admission must not silently move nonexistent local times."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.gateway.routers.scheduled_tasks import ScheduledTaskCreateRequest, ScheduledTaskUpdateRequest
from app.gateway.scheduled_task_validation import (
    prepare_resume_updates,
    resolve_end_at,
    validate_scheduled_task_create,
    validate_scheduled_task_update,
)
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.scheduler.schedules import next_run_at

NOW = datetime(2026, 10, 22, tzinfo=UTC)
GAPS = [
    ("America/New_York", "2027-03-14T02:30:00"),
    ("Europe/Berlin", "2027-03-28T02:30:00"),
    ("Australia/Sydney", "2027-10-03T02:30:00"),
    ("Australia/Lord_Howe", "2027-10-03T02:15:00"),
]


def _existing(timezone, **updates):
    return {
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2027-01-01T09:00:00"},
        "timezone": timezone,
        "status": "enabled",
        "next_run_at": datetime(2027, 1, 1, tzinfo=UTC),
        "context_mode": "fresh_thread_per_run",
        "thread_id": None,
        "goal_objective": None,
        "max_runs": None,
        "end_at": None,
        **updates,
    }


def _time_fields(field, value):
    return {"schedule_spec": {"run_at": value}} if field == "run_at" else {"end_at": value}


@pytest.mark.asyncio
@pytest.mark.parametrize(("timezone", "wall_time"), GAPS)
@pytest.mark.parametrize("field", ["run_at", "end_at"])
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_shared_admission_rejects_nonexistent_wall_time(timezone, wall_time, field, operation):
    fields = _time_fields(field, wall_time)
    with pytest.raises(HTTPException) as caught:
        if operation == "create":
            body = ScheduledTaskCreateRequest(
                title="Report",
                prompt="Write the report",
                schedule_type="once",
                timezone=timezone,
                **({"schedule_spec": {"run_at": "2027-01-01T09:00:00"}} | fields),
            )
            await validate_scheduled_task_create(body, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(return_value="lead_agent"), now=NOW)
        else:
            body = ScheduledTaskUpdateRequest(**fields)
            await validate_scheduled_task_update(_existing(timezone), body.model_dump(exclude_unset=True), user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(), used=0, now=NOW)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == ("invalid_schedule" if field == "run_at" else "invalid_request")
    assert caught.value.detail["message"].startswith(f"{field}: ")
    assert "does not exist" in caught.value.detail["message"]
    assert timezone in caught.value.detail["message"]


@pytest.mark.parametrize(("timezone", "wall_time"), GAPS)
def test_resume_rejects_nonexistent_end_at(timezone, wall_time):
    with pytest.raises(HTTPException) as caught:
        prepare_resume_updates(_existing(timezone, status="paused"), {"end_at": wall_time}, used=0, now=NOW)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_request"
    assert "does not exist" in caught.value.detail["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timezone", "wall_time", "expected"),
    [
        ("America/New_York", "2027-03-14T01:30:00", "2027-03-14T06:30:00+00:00"),
        ("America/New_York", "2027-03-14T03:30:00", "2027-03-14T07:30:00+00:00"),
        ("Europe/Berlin", "2027-03-28T01:30:00", "2027-03-28T00:30:00+00:00"),
        ("Europe/Berlin", "2027-03-28T03:30:00", "2027-03-28T01:30:00+00:00"),
        ("Australia/Sydney", "2027-10-03T01:30:00", "2027-10-02T15:30:00+00:00"),
        ("Australia/Sydney", "2027-10-03T03:30:00", "2027-10-02T16:30:00+00:00"),
        ("Australia/Lord_Howe", "2027-10-03T01:45:00", "2027-10-02T15:15:00+00:00"),
        ("Australia/Lord_Howe", "2027-10-03T02:45:00", "2027-10-02T15:45:00+00:00"),
        ("America/New_York", "2027-11-07T01:30:00", "2027-11-07T05:30:00+00:00"),
        ("America/New_York", "2027-11-07T01:30:00-05:00", "2027-11-07T06:30:00+00:00"),
        ("America/New_York", "2027-03-14T02:30:00-05:00", "2027-03-14T07:30:00+00:00"),
        ("Asia/Shanghai", "2027-03-14T02:30:00", "2027-03-13T18:30:00+00:00"),
    ],
)
async def test_valid_wall_times_and_explicit_instants_keep_their_meaning(timezone, wall_time, expected):
    body = ScheduledTaskCreateRequest(title="Report", prompt="Write the report", schedule_type="once", schedule_spec={"run_at": wall_time}, timezone=timezone)
    definition = await validate_scheduled_task_create(body, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(return_value="lead_agent"), now=NOW)
    assert definition["next_run_at"] == datetime.fromisoformat(expected)
    assert resolve_end_at(wall_time, timezone) == datetime.fromisoformat(expected)


def test_end_at_preserves_an_aware_second_fold():
    end_at = datetime(2027, 11, 7, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1)
    assert resolve_end_at(end_at, "America/New_York") == datetime(2027, 11, 7, 6, 30, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["enabled", "paused"])
async def test_unchanged_legacy_gap_schedule_keeps_its_already_accepted_instant(status):
    timezone, wall_time = GAPS[0]
    spec = {"run_at": wall_time}
    accepted = next_run_at("once", spec, timezone, now=NOW)
    existing = _existing(timezone, status=status, schedule_spec=spec, next_run_at=accepted)
    updates = await validate_scheduled_task_update(
        existing, {"schedule_spec": spec, "timezone": timezone, "title": "Renamed"}, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(), used=0, now=NOW
    )
    assert updates["next_run_at"] == accepted
    assert next_run_at("once", spec, timezone, now=accepted) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["timezone", "terminal"])
async def test_gap_schedule_is_revalidated_when_reinterpreted_or_rearmed(change):
    timezone, wall_time = GAPS[0]
    spec = {"run_at": wall_time}
    existing = _existing("UTC" if change == "timezone" else timezone, schedule_spec=spec, status="completed" if change == "terminal" else "enabled")
    fields = {"timezone": timezone} if change == "timezone" else {"schedule_spec": spec}
    with pytest.raises(HTTPException) as caught:
        await validate_scheduled_task_update(existing, fields, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(), used=0, now=NOW)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_schedule"
    assert caught.value.detail["message"].startswith("run_at: ")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "reactivate"])
@pytest.mark.parametrize("run_at", ["not-a-date", "2027-02-30T09:00:00"])
async def test_invalid_once_date_names_run_at_in_the_admission_error(operation, run_at):
    spec = {"run_at": run_at}
    with pytest.raises(HTTPException) as caught:
        if operation == "create":
            body = ScheduledTaskCreateRequest(title="Report", prompt="Write the report", schedule_type="once", schedule_spec=spec, timezone="UTC")
            await validate_scheduled_task_create(body, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(), now=NOW)
        else:
            existing = _existing("UTC", status="completed" if operation == "reactivate" else "enabled")
            await validate_scheduled_task_update(existing, {"schedule_spec": spec}, user_id="owner", thread_store=None, scheduler_config=SchedulerConfig(), assistant_resolver=AsyncMock(), used=0, now=NOW)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_schedule"
    assert caught.value.detail["message"].startswith("run_at: ")
