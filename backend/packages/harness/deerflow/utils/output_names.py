"""Collision-free output file names shared by the capture tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Cap collision-suffix probing so a saturated outputs directory cannot spin forever.
MAX_COLLISION_PROBES = 1000
# Retry bound for the timestamped fallback: each attempt offsets one clock sample,
# so the bound does not depend on the host clock advancing between yields.
MAX_TIMESTAMP_ATTEMPTS = 5


def output_name_candidates(name: str) -> Iterator[str]:
    """Yield *name*, then ``stem-1`` .. ``stem-1000``, then timestamped fallbacks.

    Callers claim each candidate atomically and move on when it is taken; the
    generator never checks the filesystem, so naming cannot race the claim.
    The clock is sampled lazily, once, when the first fallback is reached; each
    later fallback offsets that sample by one microsecond. A host clock whose
    tick is coarser than the microsecond stamp (for example Windows' ~15 ms
    system-time tick) therefore cannot repeat a stamp inside one burst, and
    every fallback stays a distinct candidate.
    """
    yield name
    stem, suffix = Path(name).stem, Path(name).suffix
    for index in range(1, MAX_COLLISION_PROBES + 1):
        yield f"{stem}-{index}{suffix}"
    stamp = datetime.now(UTC)
    for attempt in range(MAX_TIMESTAMP_ATTEMPTS):
        yield f"{stem}-{(stamp + timedelta(microseconds=attempt)).strftime('%Y%m%d-%H%M%S-%f')}{suffix}"
