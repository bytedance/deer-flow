"""YAML booleans must not coerce into the durable batch scheduler's numeric knobs.

`config.yaml` legitimately mixes `subagent_batches.enabled: true` with numeric
knobs on neighbouring lines, and Pydantic coerces `true` into `1` before the
`ge`/`le` constraints run. The batch service captures these limits once at
Gateway startup (`subagent_batches` is registered in `STARTUP_ONLY_FIELDS`), so
a mistyped boolean is already in effect by the time anything could notice:
`max_attempts: true` gives every batch item a single attempt, making any
transient failure terminal, while `default_max_running_items: true` and
`max_running_items_per_batch: true` serialize batch execution to one running
item. Mirrors the scheduler-config boolean guard (#6258) and the MCP task poller
guard, with the wording split the way `extensions_config` already splits it:
"an integer" for int fields, "a number" for the float poll interval.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.subagent_batches_config import SubagentBatchesConfig

BATCH_INT_FIELDS = (
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

BATCH_NUMBER_FIELDS = ("poll_interval_seconds",)


def _guard_cases():
    return [(field, "an integer") for field in BATCH_INT_FIELDS] + [(field, "a number") for field in BATCH_NUMBER_FIELDS]


def test_guard_covers_every_numeric_field() -> None:
    annotations = {name: field.annotation for name, field in SubagentBatchesConfig.model_fields.items()}
    numeric = {name for name, annotation in annotations.items() if annotation in (int, float)}
    assert numeric == set(BATCH_INT_FIELDS) | set(BATCH_NUMBER_FIELDS)
    assert all(annotations[field] is int for field in BATCH_INT_FIELDS)
    assert all(annotations[field] is float for field in BATCH_NUMBER_FIELDS)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize(("field", "kind"), _guard_cases())
def test_subagent_batches_config_rejects_boolean_numbers(field: str, kind: str, value: bool) -> None:
    with pytest.raises(ValidationError, match=f"must be {kind}, not a boolean"):
        SubagentBatchesConfig(**{field: value})


def test_subagent_batches_config_names_the_field_that_was_mistyped() -> None:
    with pytest.raises(ValidationError, match="max_attempts must be an integer, not a boolean"):
        SubagentBatchesConfig(max_attempts=True)


def test_subagent_batches_config_float_field_does_not_inherit_integer_wording() -> None:
    with pytest.raises(ValidationError, match=r"poll_interval_seconds must be a number, not a boolean") as excinfo:
        SubagentBatchesConfig(poll_interval_seconds=True)
    assert "must be an integer" not in str(excinfo.value)


def test_subagent_batches_config_keeps_numeric_inputs() -> None:
    config = SubagentBatchesConfig(
        poll_interval_seconds="2.5",
        max_attempts=5,
        max_result_chars=2_000,
        result_preview_max_chars=500,
    )
    assert config.poll_interval_seconds == 2.5
    assert config.max_attempts == 5
    assert config.max_result_chars == 2_000


def test_subagent_batches_config_keeps_boolean_enabled() -> None:
    assert SubagentBatchesConfig(enabled=True).enabled is True


def test_subagent_batches_config_relative_limits_still_apply() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        SubagentBatchesConfig(default_max_running_items=10, max_running_items_per_batch=4)
