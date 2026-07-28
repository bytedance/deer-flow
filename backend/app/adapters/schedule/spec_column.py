"""Boundary mapping (not a port implementation) -- the schedule_spec JSON column.

Unlike its siblings in this package, this module implements no port: it is the
translation `scheduled_task_repository` needs between the stored column and the
value object, so the domain never grows a `Mapping[str, Any]` in its
signatures.

Its counterpart on the other side of the application is
`app/gateway/routers/schedule/spec_wire.py`, which does the same job for the
HTTP request/response body. The two are near-identical today and are still kept
apart on purpose: a primary adapter must not import a secondary one, and the
two shapes are only equal by coincidence -- the day the API grows a field the
column does not have, they diverge without either side having to be untangled
first. The function names differ (`column_to_spec` here, `wire_to_spec` there)
so an import from the wrong side is visible rather than silently working.

The duplication is bounded because the split inside each is deliberate:
**structural** checks (is the key present? is it a str?) belong to the
boundary, **value** rules (5-field cron, resolvable timezone, run_at present)
belong to `ScheduleSpec.__post_init__`. Only the structural half is repeated,
and `tests/test_schedule_spec_parity.py` feeds both the same malformed inputs
so a drift between them fails a test rather than reaching production.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from deerflow.domain.schedule.model import InvalidScheduleError, ScheduleSpec, ScheduleType


def column_to_spec(schedule_type: str, spec: Mapping[str, Any] | None, timezone: str) -> ScheduleSpec:
    """Parse the stored/submitted triple into the value object.

    Raises:
        InvalidScheduleError: unknown schedule type, or the type's required key
            is missing or not a string. Raising a *domain* error from an
            adapter is intentional -- domain errors are the vocabulary the
            outer ring uses to say "this violates a domain rule", and the
            router maps this one family uniformly.
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


def spec_to_column(spec: ScheduleSpec) -> dict[str, str]:
    """Rebuild the persisted/wire JSON shape.

    Note this normalizes the stored string rather than echoing the caller's
    bytes: the frontend submits an already-UTC-aware ISO value
    (`zonedLocalToUtcIso`), so a trailing-Z input round-trips out as "+00:00".
    Both forms parse on either side, so the normalization is deliberate --
    preferable to carrying the raw dict on the value object just to preserve
    the exact input spelling.
    """
    if spec.schedule_type is ScheduleType.CRON:
        return {"cron": spec.cron or ""}
    return {"run_at": spec.run_at.isoformat() if spec.run_at else ""}
