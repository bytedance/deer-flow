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

from deerflow.domain.schedule.commands import UNSET, ContextChange, CreateScheduledTask, UpdateScheduledTask
from deerflow.domain.schedule.model import ScheduledRun, ScheduledTask, ScheduleSpec, ScheduleType

UtcTimestamp = Annotated[datetime, PlainSerializer(lambda value: value.isoformat(), return_type=str)]


def _utc(value: datetime | None) -> datetime | None:
    """Match the legacy `coerce_iso` normalisation exactly."""
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _spec_to_wire(spec: ScheduleSpec) -> dict[str, str]:
    """The value object -> the `schedule_spec` body field.

    Emits the normalized value rather than echoing the caller's bytes: the
    frontend submits an already-UTC-aware ISO value (`zonedLocalToUtcIso`), so
    a trailing-Z input comes back as "+00:00". Both forms parse on either side,
    so the normalization is deliberate.

    All this side owns is which two keys the body uses. Its counterpart is
    `SqlScheduledTaskRepository._spec_to_column`; the two are near-identical
    today by coincidence, and are kept apart because a primary adapter must not
    import a secondary one and because the day the API grows a field the column
    does not have, they diverge without either having to be untangled.
    """
    if spec.schedule_type is ScheduleType.CRON:
        return {"cron": spec.cron or ""}
    return {"run_at": spec.run_at.isoformat() if spec.run_at else ""}


class CreateScheduledTaskRequest(BaseModel):
    """Body of ``POST /scheduled-tasks``.

    No identity field: ``user_id`` is resolved server-side and injected
    through ``to_command``, never read off the wire.
    """

    thread_id: str | None = None
    context_mode: str = "fresh_thread_per_run"
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str

    def to_command(self, user_id: str) -> CreateScheduledTask:
        """Wire shape -> command (transformation ① of the chain)."""
        return CreateScheduledTask(
            user_id=user_id,
            title=self.title,
            prompt=self.prompt,
            schedule=self.to_schedule(),
            context_mode=self.context_mode,
            thread_id=self.thread_id,
        )

    def to_schedule(self) -> ScheduleSpec:
        """Parse the submitted triple into the value object.

        Raises `InvalidScheduleError` -- a *domain* error out of a primary
        adapter, on purpose: it is the vocabulary the outer ring uses to say
        "this violates a domain rule", and the router maps that one family onto
        422. Structural problems (key missing, wrong type) and value problems
        (5-field cron, resolvable timezone) both arrive as it.
        """
        return ScheduleSpec.from_primitives(
            self.schedule_type,
            cron=self.schedule_spec.get("cron"),
            run_at=self.schedule_spec.get("run_at"),
            timezone=self.timezone,
        )


class UpdateScheduledTaskRequest(BaseModel):
    """Body of ``PATCH /scheduled-tasks/{task_id}``.

    On the wire, ``None`` means "not supplied" -- an explicit ``null`` has
    always meant that on this endpoint, and unbinding a thread is expressed
    by switching ``context_mode``, not by nulling ``thread_id``. The
    ``None``-to-``UNSET`` translation in ``to_command`` is where that wire
    convention meets the command's unambiguous three-state fields.
    """

    context_mode: str | None = None
    thread_id: str | None = None
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    schedule_spec: dict[str, Any] | None = None
    timezone: str | None = None

    def changes_schedule(self) -> bool:
        return self.schedule_spec is not None or self.timezone is not None

    def changes_context(self) -> bool:
        return self.context_mode is not None or self.thread_id is not None

    def to_command(self, task_id: str, user_id: str, current: ScheduledTask | None) -> UpdateScheduledTask:
        """Wire shape -> command (transformation ① of the chain).

        A schedule or context change needs the parts the client omitted, so
        the router reads the current task once and passes it in -- this model
        stays IO-free and only translates. ``current`` may be ``None`` when
        neither composite field is being changed.
        """
        schedule = UNSET
        if current is not None and self.changes_schedule():
            schedule = self.to_schedule(current.schedule)
        context = UNSET
        if current is not None and self.changes_context():
            context = ContextChange(
                context_mode=self.context_mode if self.context_mode is not None else str(current.context_mode),
                thread_id=self.thread_id if self.thread_id is not None else current.thread_id,
            )
        return UpdateScheduledTask(
            task_id=task_id,
            user_id=user_id,
            title=self.title if self.title is not None else UNSET,
            prompt=self.prompt if self.prompt is not None else UNSET,
            schedule=schedule,
            context=context,
        )

    def to_schedule(self, current: ScheduleSpec) -> ScheduleSpec:
        """Build the replacement spec, taking what was omitted from `current`.

        The schedule *type* is not patchable; only its spec and its zone are.
        Omitted parts are read straight off the current value object rather
        than round-tripped through the wire shape and back.
        """
        if self.schedule_spec is not None:
            cron = self.schedule_spec.get("cron")
            run_at = self.schedule_spec.get("run_at")
        else:
            cron = current.cron
            run_at = current.run_at.isoformat() if current.run_at else None
        return ScheduleSpec.from_primitives(
            str(current.schedule_type),
            cron=cron,
            run_at=run_at,
            timezone=self.timezone if self.timezone is not None else current.timezone,
        )


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
            schedule_spec=_spec_to_wire(task.schedule),
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
