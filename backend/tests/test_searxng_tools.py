"""Unit tests for the SearXNG community search tool."""

import pytest

from deerflow.community.searxng.tools import _coerce_max_results


def test_returns_value_when_valid_positive_int() -> None:
    assert _coerce_max_results(3, 5) == 3


def test_returns_value_for_numeric_string() -> None:
    assert _coerce_max_results("7", 5) == 7


def test_returns_value_for_integral_float() -> None:
    assert _coerce_max_results(4.0, 5) == 4


@pytest.mark.parametrize(
    "raw",
    [True, False, 3.5, float("inf"), float("-inf"), "oops", None, [], {}],
    ids=["bool-true", "bool-false", "fractional", "inf", "neg-inf", "string", "none", "list", "dict"],
)
def test_falls_back_to_default_on_invalid_input(raw) -> None:
    assert _coerce_max_results(raw, 5) == 5
