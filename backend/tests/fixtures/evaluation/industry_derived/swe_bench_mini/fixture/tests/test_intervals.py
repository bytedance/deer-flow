from __future__ import annotations

from tinycalc import merge_intervals


def test_merge_overlapping_intervals():
    assert merge_intervals([(5, 8), (1, 3), (2, 6)]) == [(1, 8)]


def test_merge_adjacent_integer_intervals():
    assert merge_intervals([(1, 3), (4, 5), (8, 9)]) == [(1, 5), (8, 9)]


def test_empty_input_is_supported():
    assert merge_intervals([]) == []
