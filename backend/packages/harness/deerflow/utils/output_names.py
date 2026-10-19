"""Collision-free output file names shared by the capture tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

# Cap collision-suffix probing so a saturated outputs directory cannot spin forever.
MAX_COLLISION_PROBES = 1000
# Retry bound for the timestamped fallback: the microseconds stamp can only repeat
# when another writer claimed that exact name within the same microsecond.
MAX_TIMESTAMP_ATTEMPTS = 5


def output_name_candidates(name: str) -> Iterator[str]:
    """Yield *name*, then ``stem-1`` .. ``stem-1000``, then timestamped fallbacks.

    Callers claim each candidate atomically and move on when it is taken; the
    generator never checks the filesystem, so naming cannot race the claim.
    Timestamps are taken lazily, one per fallback attempt.
    """
    yield name
    stem, suffix = Path(name).stem, Path(name).suffix
    for index in range(1, MAX_COLLISION_PROBES + 1):
        yield f"{stem}-{index}{suffix}"
    for _ in range(MAX_TIMESTAMP_ATTEMPTS):
        yield f"{stem}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}{suffix}"
