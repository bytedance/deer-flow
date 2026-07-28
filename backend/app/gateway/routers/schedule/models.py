"""The HTTP shapes of the scheduled-task API.

The primary adapter's own model of what a client sends and receives -- the
counterpart to the domain aggregates, not a view of them. Two things follow
from that:

**Responses are an allowlist, not a dump.** The pre-migration router returned
the ORM row's ``to_dict()``, which leaked ``user_id``, ``lease_owner``,
``lease_expires_at``, ``overlap_policy`` and ``assistant_id`` -- lease fields
are scheduler-internal bookkeeping, and the other three are server-owned. None
appear in the frontend's ``ScheduledTask`` type or anywhere in its code, so
naming the fields explicitly here closes the leak without a client change. A
field added to the aggregate from now on stays invisible until it is
deliberately published.

**Timestamps keep the legacy spelling.** The legacy path emitted
``coerce_iso`` -> ``astimezone(UTC).isoformat()``, i.e.
``2026-08-01T09:00:00+00:00``. Pydantic v2 would serialize the same instant as
``...T09:00:00Z``, which is a silent wire change for every client parsing
these, so ``UtcTimestamp`` pins ``isoformat()`` explicitly. Both spellings are
valid ISO 8601 and JS ``Date`` accepts either -- the point is that changing it
is a decision, not a side effect of adopting a model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer

from app.gateway.routers.schedule.spec_wire import spec_to_wire
from deerflow.domain.schedule.model import ScheduledRun, ScheduledTask

UtcTimestamp = Annotated[datetime, PlainSerializer(lambda value: value.isoformat(), return_type=str)]


def _utc(value: datetime | None) -> datetime | None:
    """Match the legacy `coerce_iso` normalisation exactly."""
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ScheduledTaskCreateRequest(BaseModel):
    thread_id: str | None = None
    context_mode: str = "fresh_thread_per_run"
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str


class ScheduledTaskUpdateRequest(BaseModel):
    context_mode: str | None = None
    thread_id: str | None = None
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    schedule_spec: dict[str, Any] | None = None
    timezone: str | None = None


class ScheduledTaskResponse(BaseModel):
    """One scheduled task as the client sees it.

    Mirrors the frontend's `ScheduledTask` type field for field.
    """

    id: str
    thread_id: str | None
    context_mode: str
    title: str
    prompt: str
    schedule_type: str
    schedule_spec: dict[str, str]
    timezone: str
    status: str
    next_run_at: UtcTimestamp | None
    last_run_at: UtcTimestamp | None
    last_run_id: str | None
    last_thread_id: str | None
    last_error: str | None
    run_count: int
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @classmethod
    def from_domain(cls, task: ScheduledTask) -> ScheduledTaskResponse:
        return cls(
            id=task.task_id,
            thread_id=task.thread_id,
            context_mode=str(task.context_mode),
            title=task.title,
            prompt=task.prompt,
            schedule_type=str(task.schedule.schedule_type),
            schedule_spec=spec_to_wire(task.schedule),
            timezone=task.schedule.timezone,
            status=str(task.status),
            next_run_at=_utc(task.next_run_at),
            last_run_at=_utc(task.last_run_at),
            last_run_id=task.last_run_id,
            last_thread_id=task.last_thread_id,
            last_error=task.last_error,
            run_count=task.run_count,
            created_at=_utc(task.created_at),
            updated_at=_utc(task.updated_at),
        )


class ScheduledRunResponse(BaseModel):
    """One execution record. Mirrors the frontend's `ScheduledTaskRun` type."""

    id: str
    task_id: str
    thread_id: str
    run_id: str | None
    scheduled_for: UtcTimestamp
    trigger: str
    status: str
    error: str | None
    started_at: UtcTimestamp | None
    finished_at: UtcTimestamp | None
    created_at: UtcTimestamp

    @classmethod
    def from_domain(cls, run: ScheduledRun) -> ScheduledRunResponse:
        return cls(
            id=run.record_id,
            task_id=run.task_id,
            thread_id=run.thread_id,
            run_id=run.run_id,
            scheduled_for=_utc(run.scheduled_for),
            trigger=str(run.trigger),
            status=str(run.status),
            error=run.error,
            started_at=_utc(run.started_at),
            finished_at=_utc(run.finished_at),
            created_at=_utc(run.created_at),
        )


class TriggerResponse(BaseModel):
    id: str
    triggered: bool


class DeleteResponse(BaseModel):
    id: str
    deleted: bool
