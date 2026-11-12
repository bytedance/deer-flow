"""Tests for token budget configuration validation."""

import pytest
from pydantic import ValidationError

from deerflow.config.token_budget_config import TokenBudgetConfig


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", ["max_tokens", "max_input_tokens", "max_output_tokens"])
def test_token_limits_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        TokenBudgetConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", ["warn_threshold", "hard_stop_threshold"])
def test_token_thresholds_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be a number, not a boolean"):
        TokenBudgetConfig(**{field: value})


def test_token_budget_keeps_numeric_string_and_integer_coercion() -> None:
    config = TokenBudgetConfig.model_validate(
        {
            "max_input_tokens": "4096",
            "warn_threshold": 1,
            "hard_stop_threshold": "1.0",
        },
    )

    assert config.max_input_tokens == 4096
    assert config.warn_threshold == 1.0
    assert config.hard_stop_threshold == 1.0
