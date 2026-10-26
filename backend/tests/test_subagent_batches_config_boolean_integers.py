"""YAML booleans must not coerce into the subagent scheduler's numeric knobs.

`config.yaml`'s `subagent_batches` section mixes a boolean (`enabled: true`)
with nine integer knobs and one float on neighbouring lines, so a typo like
`max_attempts: true` loads cleanly — and Pydantic coerces it to `1`. Since the
Gateway captures these limits once at startup, that silently turns
`max_attempts` into "every transient failure is terminal" and the running-item
caps into one-at-a-time execution (issue #6290). The sibling `subagent_runtime`
admission config shares both traits — neighbouring booleans and
capture-once-at-startup semantics — so `max_running: true` serializes every
ordinary native subagent behind a single process slot.

Mirrors the scheduler-config boolean guard
(`test_scheduler_config_boolean_integers.py`): the shared `reject_boolean`
before-validators reject booleans with a field-specific error before
Pydantic's numeric coercion, using `an integer` wording for the int fields and
`a number` for the float poll interval.
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

# Both the silent-coercion fields (`max_attempts`, the running-item caps, ...)
# and the high-floor ones (`lease_seconds`, `max_result_chars`, ...) reject
# booleans; the floors no longer mask the misleading "greater than or equal to"
# message.
BATCH_BOOL_FIELDS = BATCH_INT_FIELDS + ("poll_interval_seconds",)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BATCH_INT_FIELDS)
def test_batch_int_fields_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentBatchesConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
def test_batch_poll_interval_rejects_booleans(value: bool) -> None:
    with pytest.raises(ValidationError, match="must be a number, not a boolean"):
        SubagentBatchesConfig(poll_interval_seconds=value)


def test_batch_config_keeps_numeric_inputs() -> None:
    config = SubagentBatchesConfig(
        poll_interval_seconds="2.5",
        lease_seconds=300,
        max_attempts=3,
        default_max_running_items=3,
    )
    assert config.poll_interval_seconds == 2.5
    assert config.lease_seconds == 300
    assert config.max_attempts == 3
    assert config.default_max_running_items == 3


# The sibling admission config shares the section's neighbouring
# booleans and the same captured-at-startup semantics: `max_running: true`
# would serialize every ordinary native subagent behind one process slot.
RUNTIME_INT_FIELDS = ("max_running", "max_queued", "queue_timeout_seconds")


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", RUNTIME_INT_FIELDS)
def test_subagent_runtime_config_rejects_boolean_integers(field: str, value: bool) -> None:
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig

    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentRuntimeConfig(**{field: value})


def test_subagent_runtime_config_keeps_numeric_inputs() -> None:
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig

    config = SubagentRuntimeConfig(max_running="4", max_queued=100, queue_timeout_seconds=600)
    assert config.max_running == 4
    assert config.max_queued == 100
    assert config.queue_timeout_seconds == 600
