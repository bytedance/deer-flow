"""Bounds for provider-supplied model retry delays."""

import math
import time
from datetime import UTC
from email.utils import parsedate_to_datetime

MAX_RETRY_AFTER_MS = 24 * 60 * 60 * 1000

# Providers disagree on the spelling and the unit of the retry hint, so every
# caller reads the same tuple: the ``-ms`` spellings are milliseconds, the
# others are seconds or an HTTP date.
RETRY_AFTER_HEADERS = ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After")


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


def retry_after_hint_ms(error: Exception | None, *, now: float | None = None) -> int | None:
    """Read a bounded retry hint from an error's response headers.

    Every provider retry loop shares this parser so one header cannot mean two
    different things: decimals are accepted (gateways in front of a provider
    emit them), ``-ms`` spellings are milliseconds, and anything unparseable,
    non-finite or past the 24-hour bound falls back to the caller's schedule.
    ``now`` keeps each caller's clock (and its tests' fixed clock) authoritative
    for HTTP-date hints.
    """
    response = getattr(error, "response", None) if error is not None else None
    headers = getattr(response, "headers", None)
    if not headers:
        return None

    current = time.time() if now is None else now
    for header in RETRY_AFTER_HEADERS:
        raw = headers.get(header)
        if not raw:
            continue
        is_milliseconds = "ms" in header.lower()
        try:
            milliseconds = float(raw) if is_milliseconds else float(raw) * 1000
        except (TypeError, ValueError, OverflowError):
            if is_milliseconds:
                continue
            milliseconds = parse_retry_after_date_ms(str(raw), now=current)
            if milliseconds is None:
                continue
        bounded = bounded_retry_after_ms(milliseconds)
        if bounded is not None:
            return bounded
    return None
