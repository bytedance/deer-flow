from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from deerflow.domain.schedule.exceptions import InvalidScheduleError
from deerflow.domain.schedule.model.enums import ScheduleType

CRON_FIELD_COUNT = 5


@dataclass(frozen=True)
class SchedulePolicy:
    """Operator-tunable thresholds the domain needs but must not read itself.

    Built by the composition root from the scheduler configuration and passed
    in. Deliberately not held by any aggregate: a task whose meaning changes
    with deployment config is not a domain object.

    The defaults are the permissive ones on purpose -- "nobody configured a
    policy" must not invent a business constraint. Real values only ever
    arrive from the outer ring.
    """

    min_once_delay_seconds: int = 0
    """How far ahead a one-shot schedule must be at submission time. Read by
    `ScheduleSpec.ensure_launchable`; a cron schedule is never subject to it."""

    max_concurrent_runs: int = 1
    """Ceiling on active scheduled executions across ALL tasks. Long runs
    accumulate across polls, so each poll may only claim into what is left."""

    lease_seconds: int = 60
    """How long a claim on a task stays valid. Bounds how quickly a task
    orphaned between claim and dispatch becomes reachable again."""


@dataclass(frozen=True)
class ScheduleSpec:
    """Parsed, validated view of (schedule_type, schedule_spec, timezone).

    The stored JSON spec is mapped in and out by the adapter layer, never here:
    a `Mapping[str, Any]` in a domain signature would mean the domain is
    handling a persistence/transport format. The two halves of that parsing
    split cleanly — structural checks (is the key present? is it a str?) belong
    to the boundary, value rules (5-field cron, resolvable timezone, run_at
    present) belong to __post_init__ below. Storage keeps the same raw JSON, so
    this needs no migration.

    Normalization happens in __post_init__ rather than in the factories below,
    so direct construction cannot bypass it: a frozen dataclass is still
    constructible field-by-field, and "valid on construction" has to hold for
    that path too.
    """

    schedule_type: ScheduleType
    timezone: str
    cron: str | None = None
    run_at: datetime | None = None

    def __post_init__(self) -> None:
        # The timezone is checked first because normalizing a naive run_at
        # below needs it to already be known-good.
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise InvalidScheduleError(f"Unknown timezone: {self.timezone}") from exc

        if self.schedule_type is ScheduleType.CRON:
            if not self.cron:
                raise InvalidScheduleError("cron schedule requires schedule_spec.cron")
            fields = [part for part in self.cron.split() if part]
            if len(fields) != CRON_FIELD_COUNT:
                raise InvalidScheduleError(f"Cron expression must contain exactly {CRON_FIELD_COUNT} fields")
            object.__setattr__(self, "cron", " ".join(fields))

        if self.schedule_type is ScheduleType.ONCE:
            if self.run_at is None:
                raise InvalidScheduleError("once schedule requires run_at")
            if self.run_at.tzinfo is None:
                # A naive run_at means wall-clock time in this schedule's own
                # timezone (schedules.py:40-43). Localizing here rather than at
                # every read site keeps the rest of this class tz-aware only.
                object.__setattr__(self, "run_at", self.run_at.replace(tzinfo=zone))

    @classmethod
    def cron_schedule(cls, expr: str, timezone: str) -> ScheduleSpec:
        """Readability sugar — all validation lives in __post_init__."""
        return cls(ScheduleType.CRON, timezone, cron=expr)

    @classmethod
    def once_at(cls, run_at: datetime, timezone: str) -> ScheduleSpec:
        """Readability sugar — all validation lives in __post_init__."""
        return cls(ScheduleType.ONCE, timezone, run_at=run_at)

    @classmethod
    def from_primitives(cls, schedule_type: str, *, cron: str | None, run_at: str | None, timezone: str) -> ScheduleSpec:
        """Build from the loose strings both boundaries arrive as.

        The HTTP body and the stored JSON column both carry a schedule type
        plus a mapping, so the rule for turning that into a value object lives
        here instead of being written out once per adapter. Each adapter keeps
        only what is genuinely its own — which keys its own format uses — and
        the errors below stay one family the router maps uniformly.

        Four strings rather than a `Mapping[str, Any]` on purpose: a mapping in
        this signature would mean the domain is handling a transport or storage
        format, which is the thing this class exists to avoid.

        `cron` and `run_at` are annotated as the contract expects them but
        checked rather than trusted — both callers read from data a client can
        influence, so a non-string must be rejected here instead of reaching
        `fromisoformat` or the cron parser. The field the given type does not
        use is ignored: a boundary that carries both keys is not an error.

        Raises:
            InvalidScheduleError: unknown schedule type, the type's field
                missing or not a string, or an unparseable `run_at`. Value
                rules — 5-field cron, resolvable timezone — are left to
                __post_init__ and surface as the same error.
        """
        try:
            kind = ScheduleType(schedule_type)
        except ValueError as exc:
            raise InvalidScheduleError(f"Unsupported schedule_type: {schedule_type}") from exc

        if kind is ScheduleType.CRON:
            if not isinstance(cron, str):
                raise InvalidScheduleError("cron schedule requires schedule_spec.cron")
            return cls.cron_schedule(cron, timezone)

        if not isinstance(run_at, str):
            raise InvalidScheduleError("once schedule requires run_at")
        try:
            parsed = datetime.fromisoformat(run_at)
        except ValueError as exc:
            raise InvalidScheduleError(f"once schedule has an unparseable run_at: {run_at!r}") from exc
        return cls.once_at(parsed, timezone)

    def next_after(self, now: datetime) -> datetime | None:
        """Next fire time in UTC, or None when there is no future occurrence.

        The dispatch-path calculation (was `next_run_at` in schedules.py:24-55).
        It applies no submission-time policy — see ensure_launchable for that,
        and do not swap the two: re-arming a cron task through the stricter one
        would reject it right after a perfectly normal launch.

        ONCE returns run_at while it is still ahead of `now`, else None (the
        single occurrence is in the past). CRON is evaluated in this schedule's
        timezone and returned as UTC. A naive `now` is read as UTC
        (schedules.py:32-33).
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        if self.schedule_type is ScheduleType.ONCE:
            return self.run_at if self.run_at > now else None

        zone = ZoneInfo(self.timezone)
        next_local = croniter(self.cron, now.astimezone(zone)).get_next(datetime)
        if next_local.tzinfo is None:
            # Unreachable with an aware input on today's croniter, and kept
            # verbatim from schedules.py:51-52 rather than dropped: it costs
            # one branch and guards a library detail we do not control.
            next_local = next_local.replace(tzinfo=zone)
        return next_local.astimezone(UTC)

    def ensure_launchable(self, now: datetime, policy: SchedulePolicy) -> datetime | None:
        """Next fire time, with the constraints that only apply at submission.

        Used by create/update; the dispatch path must use next_after instead.

        Raises:
            InvalidScheduleError: a ONCE schedule with no future occurrence, or
                one closer than policy.min_once_delay_seconds. CRON is never
                subject to the delay floor (router:105, router:196).
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        next_at = self.next_after(now)
        if self.schedule_type is not ScheduleType.ONCE:
            return next_at
        if next_at is None:
            raise InvalidScheduleError("once schedule must be in the future")
        if (next_at - now).total_seconds() < policy.min_once_delay_seconds:
            raise InvalidScheduleError(f"once schedule must be at least {policy.min_once_delay_seconds} seconds in the future")
        return next_at
