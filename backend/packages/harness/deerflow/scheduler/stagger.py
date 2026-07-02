"""Deterministic per-job top-of-hour stagger.

Recurring top-of-hour cron jobs (``0 * * * *``,
``0 */2 * * *``, etc.) get a stable per-job offset within a configurable
window (default 5 minutes). The offset is derived from a SHA-256 hash of
the job id, so the same job always lands at the same offset — restarting
the scheduler does not reshuffle every job's schedule.

Why hash instead of random:
- Deterministic — restart-safe and reproducible
- Spread out — SHA-256 distributes job ids uniformly across the window
- No coordination — each scheduler instance computes the same offset
"""

from __future__ import annotations

import hashlib

DEFAULT_TOP_OF_HOUR_STAGGER_MS: int = 5 * 60 * 1000


def stable_offset_ms(job_id: str, stagger_ms: int) -> int:
    """Return a deterministic offset in ``[0, stagger_ms)`` for ``job_id``.

    Returns ``0`` when ``stagger_ms <= 1`` (effectively no staggering).
    """
    if stagger_ms <= 1:
        return 0
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % stagger_ms
