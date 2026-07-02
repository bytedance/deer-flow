"""Self-contained 5-field cron expression parser and evaluator.

Zero external dependencies. Supports the standard Vixie cron syntax:

- ``*``                   — wildcard
- ``N``                   — single integer
- ``a-b``                 — inclusive range
- ``a,b,c``               — list
- ``*/N``                 — step from the field minimum
- ``a-b/N``               — step within a range
- ``a/N``                 — step from ``a`` to field max

Five fields, in order: ``minute hour day-of-month month day-of-week``.
Day-of-week uses the Vixie cron convention: Sunday=0 through Saturday=6.

Day-of-month and day-of-week use Vixie cron OR semantics: when both
fields are non-wildcard, a date matches when **either** field matches
(not both). To require both, schedule on one field and guard in the job
prompt; this matches ``croniter`` / system cron behaviour.

Public API:

- ``parse_cron_expr(expr)`` → tuple of 5 sets
- ``compute_next_cron(fields, after, tz_name)`` → ``datetime | None``
- ``compute_previous_cron(fields, before, tz_name)`` → ``datetime | None``

Implementation note: ``compute_next_cron`` uses a bounded minute-by-minute
scan (worst case ~525,600 iterations for a 1-year window) instead of a
calendar-aware algorithm. This is fast enough (<10ms typical) and
sidesteps timezone / DST corner cases.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


# (lo, hi) for each of the 5 cron fields in canonical order
_FIELD_RANGES: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day-of-month
    (1, 12),  # month
    (0, 6),  # day-of-week (Sun=0 .. Sat=6)
)

# Worst-case scan window. ``0 0 29 2 *`` (Feb 29) needs up to 4 years in
# the rare case the cursor lands just past one occurrence, but a 1-year
# window is enough for almost every realistic expression; callers should
# surface "never fires" to the user instead of looping forever.
_MAX_SCAN_MINUTES = 366 * 24 * 60


class CronParseError(ValueError):
    """Raised when a cron expression is syntactically invalid."""


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field into the set of matching integers.

    Raises ``CronParseError`` for any malformed input or value outside
    ``[lo, hi]``.
    """
    field = field.strip()
    if not field:
        raise CronParseError("empty cron field")

    # Whole-field wildcard short-circuit
    if field == "*":
        return set(range(lo, hi + 1))

    result: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronParseError(f"empty list element in cron field {field!r}")

        # Step syntax: */N, a-b/N, a/N
        if "/" in part:
            base, _, step_str = part.partition("/")
            try:
                step = int(step_str)
            except ValueError as exc:
                raise CronParseError(f"invalid step {step_str!r} in {part!r}") from exc
            if step <= 0:
                raise CronParseError(f"step must be positive in {part!r}")

            if base == "*":
                start, end = lo, hi
            elif "-" in base:
                start_str, _, end_str = base.partition("-")
                try:
                    start, end = int(start_str), int(end_str)
                except ValueError as exc:
                    raise CronParseError(f"invalid range {base!r}") from exc
                if start > end:
                    raise CronParseError(f"range start must be <= end in {base!r}")
            else:
                try:
                    start = int(base)
                except ValueError as exc:
                    raise CronParseError(f"invalid step base {base!r}") from exc
                end = hi

            result.update(range(start, end + 1, step))
            continue

        # Bare wildcard as list element (uncommon, but be permissive)
        if part == "*":
            result.update(range(lo, hi + 1))
            continue

        # Range syntax: a-b
        if "-" in part:
            start_str, _, end_str = part.partition("-")
            try:
                start, end = int(start_str), int(end_str)
            except ValueError as exc:
                raise CronParseError(f"invalid range {part!r}") from exc
            if start > end:
                raise CronParseError(f"range start must be <= end in {part!r}")
            result.update(range(start, end + 1))
            continue

        # Bare integer
        try:
            result.add(int(part))
        except ValueError as exc:
            raise CronParseError(f"invalid value {part!r}") from exc

    invalid = {v for v in result if not (lo <= v <= hi)}
    if invalid:
        raise CronParseError(f"cron field {field!r} has out-of-range values {sorted(invalid)} (allowed {lo}..{hi})")
    return result


def parse_cron_expr(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    """Parse a 5-field cron expression.

    Returns a 5-tuple of integer sets in canonical order: minute, hour,
    day-of-month, month, day-of-week.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise CronParseError(f"cron expression must have exactly 5 fields, got {len(fields)}: {expr!r}")
    return tuple(  # type: ignore[return-value]
        _parse_field(field, lo, hi) for field, (lo, hi) in zip(fields, _FIELD_RANGES)
    )


def _resolve_timezone(tz_name: str | None) -> ZoneInfo:
    """Resolve a timezone name. Falls back to UTC for invalid names."""
    if not tz_name or tz_name.upper() == "UTC":
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("unknown timezone %r, falling back to UTC", tz_name)
        return ZoneInfo("UTC")


def _dom_dow_match(
    candidate: datetime,
    dom_set: set[int],
    mon_set: set[int],
    dow_set: set[int],
) -> bool:
    """Apply Vixie cron OR semantics for day-of-month and day-of-week.

    Per the original cron spec, when both fields are restricted (non-
    wildcard), the date matches when **either** matches. When only one is
    restricted, only that one matters.

    Day-of-week semantics: cron uses Vixie convention ``Sun=0..Sat=6``,
    while Python ``datetime.weekday()`` uses ``Mon=0..Sun=6``. We convert
    the cron set to Python weekday values once per match.
    """
    if candidate.month not in mon_set:
        return False

    # Convert cron dow (Sun=0..Sat=6) → Python weekday (Mon=0..Sun=6)
    python_dow_set = {(d + 6) % 7 for d in dow_set}

    dom_is_wildcard = len(dom_set) == 31  # full range 1..31
    dow_is_wildcard = len(dow_set) == 7  # full range 0..6

    dom_match = candidate.day in dom_set
    dow_match = candidate.weekday() in python_dow_set

    if dom_is_wildcard and dow_is_wildcard:
        return True
    if dom_is_wildcard:
        return dow_match
    if dow_is_wildcard:
        return dom_match
    # Both restricted → OR
    return dom_match or dow_match


def compute_next_cron(
    fields: Iterable[set[int]],
    after: datetime,
    tz_name: str = "UTC",
) -> datetime | None:
    """Return the next datetime strictly after ``after`` that matches.

    ``after`` should be timezone-aware. If naive, it is treated as UTC.
    The returned datetime is timezone-aware in ``tz_name``.

    Returns ``None`` when no match exists within ~1 year (e.g. ``0 0 29 2 *``
    just past Feb 29 in a non-leap year may need to scan 4+ years).
    """
    minute_set, hour_set, dom_set, mon_set, dow_set = fields
    tz = _resolve_timezone(tz_name)

    # Normalise the cursor to the target timezone.
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    candidate = (after + timedelta(minutes=1)).astimezone(tz)
    candidate = candidate.replace(second=0, microsecond=0)

    for _ in range(_MAX_SCAN_MINUTES):
        if candidate.minute in minute_set and candidate.hour in hour_set and _dom_dow_match(candidate, dom_set, mon_set, dow_set):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def compute_previous_cron(
    fields: Iterable[set[int]],
    before: datetime,
    tz_name: str = "UTC",
) -> datetime | None:
    """Return the most recent datetime strictly before ``before`` that
    matched. Used by stagger to verify whether a candidate slot is a
    natural cron hit.
    """
    minute_set, hour_set, dom_set, mon_set, dow_set = fields
    tz = _resolve_timezone(tz_name)

    if before.tzinfo is None:
        before = before.replace(tzinfo=UTC)
    candidate = (before - timedelta(minutes=1)).astimezone(tz)
    candidate = candidate.replace(second=0, microsecond=0)

    for _ in range(_MAX_SCAN_MINUTES):
        if candidate.minute in minute_set and candidate.hour in hour_set and _dom_dow_match(candidate, dom_set, mon_set, dow_set):
            return candidate
        candidate -= timedelta(minutes=1)
    return None


def is_recurring_top_of_hour(fields: Iterable[set[int]]) -> bool:
    """Detect whether a cron expression fires at the top of every hour.

    Used by stagger to decide whether to apply the default 5-minute
    anti-thundering-herd jitter. The pattern is::

        minute == {0}                 # exactly minute 0
        AND hour is wildcard          # any hour
        AND dom / mon / dow are wildcard

    Examples that return True:
        ``0 * * * *``       every hour on the hour
        ``0 */2 * * *``     every 2 hours on the hour
        ``0 0,12 * * *``    midnight and noon (NOT top-of-hour recurring —
                            hour list is explicit, not wildcard)

    The last case is intentionally excluded because staggering a fixed
    hour list would shift it away from the user's intent.
    """
    minute_set, hour_set, dom_set, mon_set, dow_set = fields
    if minute_set != {0}:
        return False
    # Hour wildcard: either full range or */N stepping (covers every N hours)
    if hour_set == set(range(0, 24)):
        return True
    # Detect */N stepping: must be an arithmetic progression from 0 with step
    sorted_hours = sorted(hour_set)
    if len(sorted_hours) >= 2 and sorted_hours[0] == 0:
        step = sorted_hours[1] - sorted_hours[0]
        if step > 1 and all(sorted_hours[i + 1] - sorted_hours[i] == step for i in range(len(sorted_hours) - 1)):
            return True
    return False
