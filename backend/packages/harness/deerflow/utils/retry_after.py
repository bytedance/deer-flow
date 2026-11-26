"""Bounds for provider-supplied model retry delays."""

import math
from collections.abc import Mapping
from datetime import UTC
from email.utils import parsedate_to_datetime

MAX_RETRY_AFTER_MS = 24 * 60 * 60 * 1000

_RETRY_AFTER_HEADERS = ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After")


def bounded_retry_after_ms(delay_ms: int | float) -> int | None:
    """Return a finite delay up to 24 hours, or None to use local backoff."""
    if isinstance(delay_ms, float) and not math.isfinite(delay_ms):
        return None
    if delay_ms > MAX_RETRY_AFTER_MS:
        return None
    return max(0, int(delay_ms))


def retry_after_hint_ms(headers: Mapping[str, str] | None, *, now: float) -> int | None:
    """Read the first usable retry hint from response headers, or None for local backoff."""
    if not headers:
        return None
    for header in _RETRY_AFTER_HEADERS:
        raw = headers.get(header)
        if not raw:
            continue
        in_milliseconds = "ms" in header.lower()
        try:
            milliseconds = float(raw) if in_milliseconds else float(raw) * 1000
        except (TypeError, ValueError, OverflowError):
            if in_milliseconds:
                continue
            milliseconds = parse_retry_after_date_ms(str(raw), now=now)
            if milliseconds is None:
                continue
        bounded = bounded_retry_after_ms(milliseconds)
        if bounded is not None:
            return bounded
    return None


def parse_retry_after_date_ms(raw: str, *, now: float) -> int | None:
    """Parse an HTTP-date in UTC, bounded by the common provider-hint policy."""
    try:
        target = parsedate_to_datetime(raw)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return bounded_retry_after_ms((target.timestamp() - now) * 1000)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
