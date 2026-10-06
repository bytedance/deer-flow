"""YAML booleans must not coerce into the subagent and ACP invocation backstops.

`config.yaml` legitimately mixes booleans (`enabled: true`) with integer knobs on
neighbouring lines, so a typo like `subagents.timeout_seconds: true` loads cleanly —
and Pydantic coerces it to `1`. The subagent executor bounds every run with
`future.result(timeout=self.config.timeout_seconds)`, so 1800 seconds becomes a
1-second kill, and `resolve_recursion_limit(self.config.max_turns)` turns a
`max_turns: true` typo into a LangGraph budget of a single super-step. The ACP
agent timeout mirrors `subagents.timeout_seconds` and has the same hole. Mirrors
the app-config, loop-detection, and tool-output boolean guards already in the repo.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.subagents_config import CustomSubagentConfig, SubagentOverrideConfig, SubagentsAppConfig

BACKSTOP_FIELDS = ("timeout_seconds", "max_turns")
GLOBAL_INT_FIELDS = ("timeout_seconds", "max_turns", "max_total_per_run")


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_override_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentOverrideConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_custom_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        CustomSubagentConfig(description="d", system_prompt="s", **{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", GLOBAL_INT_FIELDS)
def test_global_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentsAppConfig(**{field: value})


@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_override_backstops_keep_none_and_numeric_inputs(field: str) -> None:
    config = SubagentOverrideConfig(**{field: None})
    assert getattr(config, field) is None
    config = SubagentOverrideConfig(**{field: "30"})
    assert getattr(config, field) == 30


def test_custom_backstops_keep_numeric_inputs() -> None:
    config = CustomSubagentConfig(description="d", system_prompt="s", max_turns="25", timeout_seconds=600)
    assert config.max_turns == 25
    assert config.timeout_seconds == 600


def test_global_backstops_keep_numeric_inputs() -> None:
    config = SubagentsAppConfig(timeout_seconds="900", max_turns="40", max_total_per_run=8)
    assert config.timeout_seconds == 900
    assert config.max_turns == 40
    assert config.max_total_per_run == 8


@pytest.mark.parametrize("value", [True, False])
def test_acp_timeout_rejects_booleans(value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        ACPAgentConfig(command="cmd", description="d", timeout_seconds=value)


def test_acp_timeout_keeps_numeric_input() -> None:
    config = ACPAgentConfig(command="cmd", description="d", timeout_seconds="600")
    assert config.timeout_seconds == 600
