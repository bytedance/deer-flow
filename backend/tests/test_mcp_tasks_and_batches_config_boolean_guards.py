"""YAML booleans must not coerce into the MCP task poller's or the batch scheduler's numeric knobs.

``config.yaml`` legitimately mixes booleans (``enabled: true``) with integer
knobs on neighbouring lines, so a typo like
``mcp_tasks.max_poll_backoff_seconds: true`` loads cleanly — and Pydantic
coerces it to ``1``, which collapses a 300-second backoff into a one-second
retry. The same hole exists on every numeric field of both models: the fields
whose ``ge`` bound happens to be ``1`` accept the coerced value outright, and
the rest only reject it by accident because ``1`` falls below their lower
bound. ``SubagentBatchesConfig.poll_interval_seconds`` is a float field, so a
boolean becomes ``1.0``.

Both models now register the shared ``mode="before"`` ``reject_boolean`` guard
introduced for #6017, mirroring ``scheduler_config`` and ``app_config``.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.mcp_tasks_config import McpTasksConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig

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

BATCHES_INT_FIELDS = (
    "lease_seconds",
    "max_items_per_batch",
    "default_max_live_items",
    "max_live_items_per_batch",
    "default_max_running_items",
    "max_running_items_per_batch",
    "max_attempts",
    "max_result_chars",
    "result_preview_max_chars",
)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", MCP_TASKS_INT_FIELDS)
def test_mcp_tasks_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        McpTasksConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BATCHES_INT_FIELDS)
def test_batches_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentBatchesConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
def test_batches_config_rejects_boolean_seconds(value: bool) -> None:
    with pytest.raises(ValidationError, match="must be a number, not a boolean"):
        SubagentBatchesConfig(poll_interval_seconds=value)


def test_mcp_tasks_config_keeps_defaults_and_numeric_inputs() -> None:
    defaults = McpTasksConfig()
    assert defaults.poll_interval_seconds == 5
    assert defaults.max_poll_backoff_seconds == 300

    config = McpTasksConfig(poll_interval_seconds="30", max_concurrent_polls=4)
    assert config.poll_interval_seconds == 30
    assert config.max_concurrent_polls == 4


def test_batches_config_keeps_defaults_and_numeric_inputs() -> None:
    defaults = SubagentBatchesConfig()
    assert defaults.poll_interval_seconds == 1.0
    assert defaults.max_attempts == 3

    config = SubagentBatchesConfig(poll_interval_seconds=2.5, max_attempts=5)
    assert config.poll_interval_seconds == 2.5
    assert config.max_attempts == 5


def test_batches_config_still_enforces_cross_field_limits() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        SubagentBatchesConfig(default_max_running_items=64, max_running_items_per_batch=8)


def test_app_config_sections_reject_boolean_integers() -> None:
    from deerflow.config.app_config import AppConfig

    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        AppConfig(mcp_tasks={"max_poll_backoff_seconds": True}, sandbox={"use": "local"})
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        AppConfig(subagent_batches={"max_attempts": True}, sandbox={"use": "local"})
