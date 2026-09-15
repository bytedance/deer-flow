from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.grading import GRADER_VERSION, OVERLAP_THRESHOLD, grade_answer, normalize_answer

EVAL_ROOT = Path(__file__).parents[1] / "scripts" / "benchmark" / "deermem_eviction"


def test_config_pins_the_committed_grader_version() -> None:
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert config.qa.grader_version == GRADER_VERSION == "deterministic-overlap-v1"


def test_grader_is_blind_by_construction() -> None:
    parameters = inspect.signature(grade_answer).parameters
    assert list(parameters) == ["prediction", "reference"]


def test_normalization_lowercases_strips_and_maps_number_words() -> None:
    assert normalize_answer("Seven WEEKS!") == ["7", "weeks"]
    assert normalize_answer("fifteen") == ["15"]
    assert normalize_answer("eleven") == ["eleven"]
    assert normalize_answer("70-200mm zoom lens") == ["70", "200mm", "zoom", "lens"]
    assert normalize_answer("  \t\n ") == []


def test_empty_and_insufficient_predictions_are_rejected() -> None:
    empty = grade_answer("", "3 weeks")
    assert not empty.correct
    assert empty.rule == "empty-prediction"
    assert not grade_answer("   ", "3 weeks").correct
    result = grade_answer("INSUFFICIENT.", "3 weeks")
    assert not result.correct
    assert result.rule == "insufficient"
    assert not grade_answer("insufficient", "3 weeks").correct


def test_empty_reference_is_a_contract_error() -> None:
    with pytest.raises(ValueError):
        grade_answer("3 weeks", "  .  ")


def test_exact_match_ignores_case_punctuation_and_number_words() -> None:
    assert grade_answer("Every week.", "every week").rule == "exact"
    assert grade_answer("NO", "no").rule == "exact"
    assert grade_answer("seven", "7").rule == "exact"


def test_substring_matches_are_token_level_and_bidirectional() -> None:
    assert grade_answer("132 points", "132").rule == "substring"
    assert grade_answer("132", "132 points").rule == "substring"
    assert grade_answer("Ford F-150 pickup truck.", "Ford F-150").rule == "substring"
    assert grade_answer("Ford F-150 pickup truck.", "a Ford F-150").correct
    assert not grade_answer("5", "25").correct
    assert not grade_answer("no", "north").correct


def test_conflicting_numeric_answers_are_rejected() -> None:
    result = grade_answer("5", "3 weeks")
    assert not result.correct
    assert result.rule == "numeric-conflict"
    assert not grade_answer("12 weeks", "8 weeks").correct


def test_numbers_inside_an_explicit_reference_range_are_accepted() -> None:
    reference = "ranging from 5 to 10 hours"
    assert grade_answer("7", reference).rule == "numeric-range"
    assert grade_answer("5 hours", reference).rule == "numeric-range"
    assert grade_answer("10", reference).correct
    assert not grade_answer("4", reference).correct
    assert not grade_answer("11", reference).correct
    assert grade_answer("7", "ranging from 5 dollars to 10 dollars").rule == "numeric-range"


def test_overlap_requires_sixty_percent_in_both_directions() -> None:
    assert OVERLAP_THRESHOLD == 0.6
    accepted = grade_answer("under my bed", "under the bed")
    assert accepted.correct
    assert accepted.rule == "overlap-accept"
    assert grade_answer("red kite string", "red kite ribbon").correct
    assert not grade_answer("red kite", "red balloon ribbon string flag").correct
    assert not grade_answer("50mm prime lens", "70-200mm zoom lens").correct
    assert not grade_answer("YES", "NO").correct


def test_all_stopword_predictions_cannot_pass_overlap() -> None:
    result = grade_answer("of the", "3 weeks")
    assert not result.correct
    assert result.rule == "overlap-reject"
