"""YAML booleans must not coerce into the MCP task poller's integer knobs.

`config.yaml` legitimately mixes `mcp_tasks.enabled: true` with integer knobs on
neighbouring lines, so a typo like `poll_interval_seconds: true` loads cleanly -
and Pydantic coerces it to `1`, which makes the poller hit MCP task backends five
times as often as configured. `max_concurrent_polls: true` serializes polling,
`max_poll_backoff_seconds: true` caps retry backoff at one second and
`tracking_degraded_after_errors: true` marks tracking degraded after a single
error. `lease_seconds`, `input_required_poll_interval_seconds`, `max_result_bytes`
and `result_preview_max_chars` already reject `true`, but only through their
higher `ge` floors and with a misleading "greater than or equal to" message.
Mirrors the scheduler-config boolean guard (#6258).
"""

import pytest
from pydantic import ValidationError

from deerflow.config.mcp_tasks_config import McpTasksConfig

MCP_TASK_INT_FIELDS = (
    "poll_interval_seconds",
    "lease_seconds",
    "max_concurrent_polls",
    "max_poll_backoff_seconds",
    "input_required_poll_interval_seconds",
    "tracking_degraded_after_errors",
    "max_result_bytes",
    "result_preview_max_chars",
)


def test_guard_covers_every_numeric_field() -> None:
    numeric = {name for name, field in McpTasksConfig.model_fields.items() if field.annotation in (int, float)}
    assert numeric == set(MCP_TASK_INT_FIELDS)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", MCP_TASK_INT_FIELDS)
def test_mcp_tasks_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        McpTasksConfig(**{field: value})


def test_mcp_tasks_config_names_the_field_that_was_mistyped() -> None:
    with pytest.raises(ValidationError, match="max_concurrent_polls must be an integer"):
        McpTasksConfig(max_concurrent_polls=True)


def test_mcp_tasks_config_keeps_numeric_inputs() -> None:
    config = McpTasksConfig(
        poll_interval_seconds="30",
        max_concurrent_polls=5,
        max_result_bytes=4096,
    )
    assert config.poll_interval_seconds == 30
    assert config.max_concurrent_polls == 5
    assert config.max_result_bytes == 4096
