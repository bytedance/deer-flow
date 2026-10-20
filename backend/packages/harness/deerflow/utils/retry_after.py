"""Bounds for provider-supplied model retry delays."""

import math

MAX_RETRY_AFTER_MS = 24 * 60 * 60 * 1000


def bounded_retry_after_ms(delay_ms: int | float) -> int | None:
    """Return a finite delay up to 24 hours, or None to use local backoff."""
    if isinstance(delay_ms, float) and not math.isfinite(delay_ms):
        return None
    if delay_ms > MAX_RETRY_AFTER_MS:
        return None
    return max(0, int(delay_ms))
