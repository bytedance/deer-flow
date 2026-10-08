"""Unit tests for deerflow.utils.goal_objective."""

import pytest

from deerflow.utils.goal_objective import (
    MAX_GOAL_OBJECTIVE_CHARS,
    normalize_goal_objective,
)


def test_collapses_internal_whitespace_and_strips():
    assert normalize_goal_objective("  hello   world  ") == "hello world"


def test_preserves_single_spaces():
    assert normalize_goal_objective("hello world") == "hello world"


def test_newlines_collapsed_to_single_space():
    assert normalize_goal_objective("line1\n\nline2") == "line1 line2"


def test_empty_string_raises():
    with pytest.raises(ValueError):
        normalize_goal_objective("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        normalize_goal_objective("   \n\t  ")


def test_within_max_length_passes():
    value = "a" * MAX_GOAL_OBJECTIVE_CHARS
    assert normalize_goal_objective(value) == value


def test_exceeding_max_length_raises():
    value = "a" * (MAX_GOAL_OBJECTIVE_CHARS + 1)
    with pytest.raises(ValueError):
        normalize_goal_objective(value)


if __name__ == "__main__":
    test_collapses_internal_whitespace_and_strips()
    test_preserves_single_spaces()
    test_newlines_collapsed_to_single_space()
    test_empty_string_raises()
    test_whitespace_only_raises()
    test_within_max_length_passes()
    test_exceeding_max_length_raises()
    print("All goal_objective tests passed.")
