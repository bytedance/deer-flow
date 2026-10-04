"""YAML booleans must not coerce into the MCP task poller's integer knobs.

`config.yaml` legitimately mixes booleans (`enabled: true`) with integer knobs on
neighbouring lines, so a typo like `mcp_tasks.poll_interval_seconds: true` loads
cleanly — and Pydantic coerces it to `1`, making the poller hit MCP task backends
five times as often as the configured default. `max_concurrent_polls: true`
serializes task polling and `max_poll_backoff_seconds: true` caps retry backoff
at one second. Mirrors the scheduler-config boolean guard.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.mcp_tasks_config import McpTasksConfig

MCP_TASKS_INT_FIELDS = (
    "poll_interval_seconds",
    "lease_seconds",
    "max_concurrent_polls",
    "max_poll_backoff_seconds",
    "input_required_poll_interval_seconds",
    "tracking_degraded_after_errors",
    "max_result_bytes",
    "result_preview_max_chars",
)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", MCP_TASKS_INT_FIELDS)
def test_mcp_tasks_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        McpTasksConfig(**{field: value})


def test_mcp_tasks_config_keeps_numeric_inputs() -> None:
    config = McpTasksConfig(
        poll_interval_seconds="30",
        max_concurrent_polls=8,
        max_poll_backoff_seconds=300,
    )
    assert config.poll_interval_seconds == 30
    assert config.max_concurrent_polls == 8
    assert config.max_poll_backoff_seconds == 300
