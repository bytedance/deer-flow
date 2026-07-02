"""Parser for user-facing time strings.

Supports three input shapes:

1. **Relative durations** — ``"20m"``, ``"1h"``, ``"30s"``, ``"2d"``,
   ``"1w"``. Resolved against a reference ``now`` to produce an absolute
   timestamp.
2. **ISO 8601 timestamps** — ``"2026-06-20T09:00:00Z"``,
   ``"2026-06-20T17:00:00+08:00"``, ``"2026-06-20"`` (date only, midnight
   UTC). Strings without a timezone are treated as UTC.
3. **Epoch milliseconds** — ``"1718841600000"`` (rare; useful when an
   external system supplies an integer timestamp).

This module is deliberately small and stateless: the parser takes a
string + optional reference time and returns a ``datetime`` (or raises
``ValueError``). Callers compose it into higher-level triggers.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


_RELATIVE_RE = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)
_UNIT_TO_TIMEDELTA: dict[str, timedelta] = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}

# ISO 8601 timezone suffix: Z, +HH:MM, +HHMM, -HH:MM, -HHMM
_ISO_TZ_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)
_ISO_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


class TimeParseError(ValueError):
    """Raised when a time string cannot be parsed."""


def parse_relative_duration(expr: str) -> timedelta:
    """Parse a relative duration string like ``"20m"`` into a timedelta.

    Raises ``TimeParseError`` if the string is not a valid relative
    duration. Callers that want to distinguish "this is relative" from
    "this is ISO" should call this first and fall back to
    ``parse_absolute_time`` on failure.
    """
    expr = expr.strip()
    match = _RELATIVE_RE.match(expr)
    if not match:
        raise TimeParseError(f"not a relative duration: {expr!r}")
    value = int(match.group(1))
    unit = match.group(2).lower()
    return value * _UNIT_TO_TIMEDELTA[unit]


def is_relative_duration(expr: str) -> bool:
    """Cheap check: does this string look like a relative duration?"""
    return bool(_RELATIVE_RE.match(expr.strip()))


def parse_absolute_time(expr: str) -> datetime:
    """Parse an ISO 8601 timestamp or epoch-millisecond string.

    Strings without a timezone are normalised to UTC. Returns a
    timezone-aware ``datetime``.
    """
    raw = expr.strip()
    if not raw:
        raise TimeParseError("empty time string")

    # Epoch milliseconds (pure digits, length > 9 to avoid confusing with year)
    if raw.isdigit() and len(raw) >= 10:
        try:
            epoch_ms = int(raw)
        except ValueError as exc:
            raise TimeParseError(f"invalid epoch ms: {expr!r}") from exc
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC)

    # Date only: "2026-06-20" → midnight UTC
    if _ISO_DATE_ONLY_RE.match(raw):
        raw = f"{raw}T00:00:00Z"
    elif _ISO_DATETIME_RE.match(raw) and not _ISO_TZ_RE.search(raw):
        # Datetime without timezone → treat as UTC
        raw = f"{raw}Z"

    # Python's fromisoformat handles Z suffix in 3.11+, but for older
    # versions we normalise Z → +00:00.
    iso_normalised = raw.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_normalised)
    except ValueError as exc:
        raise TimeParseError(f"unrecognized time string: {expr!r}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_time_expr(expr: str, *, now: datetime | None = None) -> datetime:
    """Parse a user-facing time string into an absolute datetime.

    Accepts relative durations (``"20m"``) or absolute timestamps (ISO
    8601, epoch ms). Relative durations are resolved against ``now``
    (defaults to current UTC time).
    """
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    try:
        duration = parse_relative_duration(expr)
        return reference + duration
    except TimeParseError:
        pass

    return parse_absolute_time(expr)
