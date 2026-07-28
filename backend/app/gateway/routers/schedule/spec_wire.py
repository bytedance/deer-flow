"""Boundary mapping -- the schedule_spec HTTP body field.

The primary adapter's own translation between the request/response shape and
`ScheduleSpec`. Its counterpart is `app/adapters/schedule/spec_column.py`, which
does the same job for the stored JSON column; see that module for why the two
are kept apart rather than shared.

The split is deliberate: **structural** checks (is the key present? is it a
str?) belong here, **value** rules (5-field cron, resolvable timezone, run_at
present) belong to `ScheduleSpec.__post_init__`. That is why this module is
thin -- most of what could go wrong is caught one layer in, and reported with
the same domain error, so the router maps one family onto 422.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from deerflow.domain.schedule.model import InvalidScheduleError, ScheduleSpec, ScheduleType


def wire_to_spec(schedule_type: str, spec: Mapping[str, Any] | None, timezone: str) -> ScheduleSpec:
    """Parse the submitted triple into the value object.

    Raises:
        InvalidScheduleError: unknown schedule type, or the type's required key
            is missing or not a string. Raising a *domain* error from a primary
            adapter is intentional -- domain errors are the vocabulary the outer
            ring uses to say "this violates a domain rule", and the router maps
            that one family uniformly onto 422.
    """
    try:
        kind = ScheduleType(schedule_type)
    except ValueError as exc:
        raise InvalidScheduleError(f"Unsupported schedule_type: {schedule_type}") from exc

    fields = spec or {}
    if kind is ScheduleType.CRON:
        raw_cron = fields.get("cron")
        if not isinstance(raw_cron, str):
            raise InvalidScheduleError("cron schedule requires schedule_spec.cron")
        return ScheduleSpec.cron_schedule(raw_cron, timezone)

    raw_run_at = fields.get("run_at")
    if not isinstance(raw_run_at, str):
        raise InvalidScheduleError("once schedule requires run_at")
    try:
        run_at = datetime.fromisoformat(raw_run_at)
    except ValueError as exc:
        raise InvalidScheduleError(f"once schedule has an unparseable run_at: {raw_run_at!r}") from exc
    return ScheduleSpec.once_at(run_at, timezone)


def spec_to_wire(spec: ScheduleSpec) -> dict[str, str]:
    """Rebuild the response body shape.

    Note this emits the normalized value rather than echoing the caller's
    bytes: the frontend submits an already-UTC-aware ISO value
    (`zonedLocalToUtcIso`), so a trailing-Z input comes back as "+00:00". Both
    forms parse on either side, so the normalization is deliberate --
    preferable to carrying the raw dict on the value object just to preserve
    the exact input spelling.
    """
    if spec.schedule_type is ScheduleType.CRON:
        return {"cron": spec.cron or ""}
    return {"run_at": spec.run_at.isoformat() if spec.run_at else ""}
