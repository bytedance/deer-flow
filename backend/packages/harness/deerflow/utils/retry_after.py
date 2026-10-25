"""Bounds for provider-supplied model retry delays."""

import math
from datetime import UTC
from email.utils import parsedate_to_datetime

MAX_RETRY_AFTER_MS = 24 * 60 * 60 * 1000


def bounded_retry_after_ms(delay_ms: int | float) -> int | None:
    """Return a finite delay up to 24 hours, or None to use local backoff."""
    if isinstance(delay_ms, float) and not math.isfinite(delay_ms):
        return None
    if delay_ms > MAX_RETRY_AFTER_MS:
        return None
    return max(0, int(delay_ms))


def parse_retry_after_date_ms(raw: str, *, now: float) -> int | None:
    """Parse an HTTP-date in UTC, bounded by the common provider-hint policy."""
    try:
        target = parsedate_to_datetime(raw)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return bounded_retry_after_ms((target.timestamp() - now) * 1000)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
