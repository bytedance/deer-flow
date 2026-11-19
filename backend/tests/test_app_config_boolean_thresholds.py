"""YAML booleans must not coerce into the integer thresholds in app_config.

`config.yaml` legitimately mixes booleans (`enabled: true`) with integer knobs on
neighbouring lines, so a typo like `recursion_limit: true` loads cleanly — and
Pydantic coerces it to `1`, which for the recursion limit means every Gateway run
dies at the first LangGraph super-step. Mirrors the loop-detection and circuit
breaker guards already in the repo.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig, LlmCallConfig
from deerflow.config.sandbox_config import SandboxConfig

LLM_CALL_INT_FIELDS = (
    "max_concurrent_calls",
    "retry_max_attempts",
    "retry_base_delay_ms",
    "retry_cap_delay_ms",
    "burst_retry_base_delay_ms",
)


def _app_config(**overrides: object) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="local"), **overrides)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", LLM_CALL_INT_FIELDS)
def test_llm_call_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        LlmCallConfig(**{field: value})


def test_llm_call_config_keeps_numeric_inputs() -> None:
    config = LlmCallConfig(max_concurrent_calls="4", retry_max_attempts=3)
    assert config.max_concurrent_calls == 4
    assert config.retry_max_attempts == 3


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", ["recursion_limit", "max_recursion_limit"])
def test_recursion_limits_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        _app_config(**{field: value})


def test_recursion_limits_keep_numeric_inputs() -> None:
    config = _app_config(recursion_limit="25")
    assert config.recursion_limit == 25
