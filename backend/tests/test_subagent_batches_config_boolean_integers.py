"""YAML booleans must not coerce into the subagent batch scheduler's numeric knobs.

`config.yaml` legitimately mixes booleans (`enabled: true`) with numeric knobs on
neighbouring lines, so a typo like `subagent_batches.max_attempts: true` loads
cleanly — and Pydantic coerces it to `1`, so every durable batch item gets a
single attempt and any transient failure is terminal. `default_max_running_items:
true` and `max_running_items_per_batch: true` serialize batch execution. Mirrors
the scheduler-config boolean guard.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.subagent_batches_config import SubagentBatchesConfig

SUBAGENT_BATCHES_INT_FIELDS = (
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
@pytest.mark.parametrize("field", SUBAGENT_BATCHES_INT_FIELDS)
def test_subagent_batches_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentBatchesConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
def test_subagent_batches_config_rejects_boolean_poll_interval(value: bool) -> None:
    with pytest.raises(ValidationError, match="must be a number, not a boolean"):
        SubagentBatchesConfig(poll_interval_seconds=value)


def test_subagent_batches_config_keeps_numeric_inputs() -> None:
    config = SubagentBatchesConfig(
        poll_interval_seconds="2.5",
        max_items_per_batch=100,
        max_attempts=3,
    )
    assert config.poll_interval_seconds == 2.5
    assert config.max_items_per_batch == 100
    assert config.max_attempts == 3
