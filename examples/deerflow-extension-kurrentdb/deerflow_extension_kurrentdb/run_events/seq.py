"""``seq`` assignment for a thread's run-event stream.

A new event's ``seq`` is one above the highest ``seq`` the thread ever assigned:
the newest boundary's ``seq_high_water`` (0 without one) and every ``seq`` after it.
Boundaries carry the high water of everything they removed, so ``seq`` stays
strictly increasing and is never reused, even when a deleted run owned the top numbers.
"""

from __future__ import annotations

from collections.abc import Iterable


def next_seq(boundary_high_water: int, seqs_after: Iterable[int]) -> int:
    return max(boundary_high_water, max(seqs_after, default=0)) + 1
