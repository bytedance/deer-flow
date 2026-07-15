from __future__ import annotations


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return intervals in deterministic order.

    BUG: this placeholder does not merge overlapping or adjacent intervals.
    """

    return sorted(intervals)
