"""Tests for the scheduled-task HTTP response models.

Two things are being pinned, and they pull in opposite directions:

  - **the leak is closed** -- server-owned and scheduler-internal fields that
    the pre-migration router dumped from the ORM row must not appear, and
  - **nothing the client already reads changed** -- the field set and the
    timestamp spelling have to stay byte-compatible with what the legacy
    `to_dict()` + `coerce_iso` path emitted, or the frontend breaks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.gateway.routers.schedule.models import ScheduledRunResponse, ScheduledTaskResponse
from deerflow.domain.schedule.model import ContextMode, RunStatus, ScheduledRun, ScheduledTask, ScheduleSpec, TaskStatus, TriggerKind

# Exactly the frontend's `ScheduledTask` type (frontend/src/core/scheduled-tasks/types.ts).
FRONTEND_TASK_FIELDS = {
    "id",
    "thread_id",
    "context_mode",
    "title",
    "prompt",
    "schedule_type",
    "schedule_spec",
    "timezone",
    "status",
    "next_run_at",
    "last_run_at",
    "last_run_id",
    "last_thread_id",
    "last_error",
    "run_count",
    "created_at",
    "updated_at",
}

# Exactly the frontend's `ScheduledTaskRun` type.
FRONTEND_RUN_FIELDS = {
    "id",
    "task_id",
    "thread_id",
    "run_id",
    "scheduled_for",
    "trigger",
    "status",
    "error",
    "started_at",
    "finished_at",
    "created_at",
}

# What the ORM dump used to expose. Lease fields never reached the domain, so
# they cannot leak now; the other three can, and must not.
LEAKED_FIELDS = {"user_id", "assistant_id", "overlap_policy", "lease_owner", "lease_expires_at"}


def _task(**overrides) -> ScheduledTask:
    defaults = dict(
        task_id="task-1",
        user_id="user-1",
        title="Morning digest",
        prompt="summarize",
        schedule=ScheduleSpec.cron_schedule("0 9 * * *", "Asia/Shanghai"),
        context_mode=ContextMode.REUSE_THREAD,
        thread_id="thread-1",
        status=TaskStatus.ENABLED,
        next_run_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
        last_run_at=datetime(2026, 7, 31, 1, 0, tzinfo=UTC),
        last_run_id="run-1",
        last_thread_id="thread-1",
        last_error=None,
        run_count=3,
        created_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 31, 1, 0, tzinfo=UTC),
    )
    return ScheduledTask(**{**defaults, **overrides})


def _run(**overrides) -> ScheduledRun:
    defaults = dict(
        record_id="task-run-1",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
        trigger=TriggerKind.SCHEDULED,
        status=RunStatus.SUCCESS,
        run_id="run-1",
        error=None,
        started_at=datetime(2026, 8, 1, 1, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 8, 1, 1, 0, 9, tzinfo=UTC),
        created_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
    )
    return ScheduledRun(**{**defaults, **overrides})


class TestTheLeakIsClosed:
    def test_no_server_owned_field_is_published(self):
        emitted = set(ScheduledTaskResponse.from_domain(_task()).model_dump())
        assert emitted & LEAKED_FIELDS == set()

    def test_the_field_set_is_exactly_what_the_frontend_declares(self):
        """Both directions matter: an extra field is a leak, a missing one
        breaks a client that reads it."""
        assert set(ScheduledTaskResponse.from_domain(_task()).model_dump()) == FRONTEND_TASK_FIELDS

    def test_run_records_publish_exactly_the_declared_fields(self):
        assert set(ScheduledRunResponse.from_domain(_run()).model_dump()) == FRONTEND_RUN_FIELDS


class TestFieldMapping:
    def test_the_aggregate_id_is_published_as_id(self):
        assert ScheduledTaskResponse.from_domain(_task()).id == "task-1"

    def test_the_record_id_is_published_as_id(self):
        assert ScheduledRunResponse.from_domain(_run()).id == "task-run-1"

    def test_the_schedule_value_object_is_flattened_into_three_fields(self):
        """The client's shape predates the value object and keeps the three
        columns separate; the flattening is this model's job, not the
        domain's."""
        response = ScheduledTaskResponse.from_domain(_task())
        assert response.schedule_type == "cron"
        assert response.schedule_spec == {"cron": "0 9 * * *"}
        assert response.timezone == "Asia/Shanghai"

    def test_a_once_schedule_flattens_to_run_at(self):
        task = _task(schedule=ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "UTC"))
        response = ScheduledTaskResponse.from_domain(task)
        assert response.schedule_type == "once"
        assert response.schedule_spec == {"run_at": "2026-08-01T09:00:00+00:00"}

    def test_enums_are_emitted_as_their_string_values(self):
        """`StrEnum` would serialize acceptably either way, but the client
        compares against string literals, so the model declares `str`."""
        payload = json.loads(ScheduledTaskResponse.from_domain(_task()).model_dump_json())
        assert payload["status"] == "enabled"
        assert payload["context_mode"] == "reuse_thread"


class TestTimestampCompatibility:
    def test_utc_timestamps_keep_the_legacy_spelling(self):
        """`coerce_iso` emitted `astimezone(UTC).isoformat()`; anything else
        is a silent wire change for every client parsing these."""
        payload = json.loads(ScheduledTaskResponse.from_domain(_task()).model_dump_json())
        assert payload["next_run_at"] == "2026-08-01T01:00:00+00:00"
        assert payload["created_at"] == "2026-07-01T00:00:00+00:00"

    def test_a_non_utc_timestamp_is_converted_not_echoed(self):
        """The legacy path normalised the offset away. A value that reached
        the aggregate in another zone must not start emitting `+08:00`."""
        shanghai = timezone(timedelta(hours=8))
        task = _task(next_run_at=datetime(2026, 8, 1, 9, 0, tzinfo=shanghai))
        payload = json.loads(ScheduledTaskResponse.from_domain(task).model_dump_json())
        assert payload["next_run_at"] == "2026-08-01T01:00:00+00:00"

    def test_a_naive_timestamp_is_assumed_utc(self):
        """Same assumption the repository's `_tz_aware` makes on read."""
        task = _task(next_run_at=datetime(2026, 8, 1, 1, 0))
        payload = json.loads(ScheduledTaskResponse.from_domain(task).model_dump_json())
        assert payload["next_run_at"] == "2026-08-01T01:00:00+00:00"

    @pytest.mark.parametrize("field", ["next_run_at", "last_run_at"])
    def test_absent_timestamps_stay_null(self, field):
        payload = json.loads(ScheduledTaskResponse.from_domain(_task(**{field: None})).model_dump_json())
        assert payload[field] is None

    def test_run_timestamps_use_the_same_spelling(self):
        payload = json.loads(ScheduledRunResponse.from_domain(_run()).model_dump_json())
        assert payload["scheduled_for"] == "2026-08-01T01:00:00+00:00"
        assert payload["finished_at"] == "2026-08-01T01:00:09+00:00"
