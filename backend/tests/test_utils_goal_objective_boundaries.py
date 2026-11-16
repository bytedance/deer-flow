"""Boundary coverage for ``deerflow.utils.goal_objective``."""

from __future__ import annotations

import pytest

from deerflow.utils.goal_objective import MAX_GOAL_OBJECTIVE_CHARS, normalize_goal_objective


def test_normalize_goal_objective_collapses_all_whitespace() -> None:
    assert normalize_goal_objective("  a  \n\t b   c  ") == "a b c"


def test_normalize_goal_objective_rejects_blank_only_input() -> None:
    for blank in ("", "   ", "\n\t\r "):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_goal_objective(blank)


def test_normalize_goal_objective_accepts_exact_limit() -> None:
    text = "x" * MAX_GOAL_OBJECTIVE_CHARS
    assert normalize_goal_objective(text) == text


def test_normalize_goal_objective_rejects_one_over_limit() -> None:
    with pytest.raises(ValueError, match="at most"):
        normalize_goal_objective("x" * (MAX_GOAL_OBJECTIVE_CHARS + 1))


def test_normalize_goal_objective_counts_characters_not_bytes() -> None:
    text = "\u4e2d" * MAX_GOAL_OBJECTIVE_CHARS
    assert normalize_goal_objective(text) == text
