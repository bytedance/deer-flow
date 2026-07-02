"""Exponential backoff schedule for consecutive job errors.

    attempt 1 → 30s
    attempt 2 → 1m
    attempt 3 → 5m
    attempt 4 → 15m
    attempt 5+ → 60m (capped)

The schedule resets after a successful run.
"""

from __future__ import annotations

from datetime import timedelta

# Ordered list of backoffs by consecutive error count (1-indexed).
DEFAULT_BACKOFFS: tuple[timedelta, ...] = (
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)


def error_backoff_delay(consecutive_errors: int) -> timedelta:
    """Return the backoff delay before the next retry attempt.

    ``consecutive_errors`` is 1-indexed: the first failure returns the
    first backoff slot. Errors beyond the list length return the last
    slot (capped).
    """
    if consecutive_errors <= 0:
        return timedelta(0)
    idx = min(consecutive_errors - 1, len(DEFAULT_BACKOFFS) - 1)
    return DEFAULT_BACKOFFS[idx]
