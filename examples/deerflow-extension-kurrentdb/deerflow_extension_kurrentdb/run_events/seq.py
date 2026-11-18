"""``seq`` assignment for a thread's run-event stream.

A new event's ``seq`` is one above the highest ``seq`` the thread ever assigned:
the newest boundary's ``seq_high_water`` (0 without one) and every ``seq`` after it.
A deletion writes that same high water into its boundary (``RunsCompacted`` /
``ThreadCleared``), so ``seq`` stays strictly increasing and is never reused, even
when a deleted run owned the top numbers or the whole thread was cleared.
"""

from __future__ import annotations

from collections.abc import Iterable


def seq_high_water(boundary_high_water: int, seqs_after: Iterable[int]) -> int:
    """The highest ``seq`` ever assigned: the newest boundary's high water and every ``seq`` after it."""
    return max(boundary_high_water, max(seqs_after, default=0))


def next_seq(boundary_high_water: int, seqs_after: Iterable[int]) -> int:
    return seq_high_water(boundary_high_water, seqs_after) + 1
