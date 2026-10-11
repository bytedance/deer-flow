"""YAML booleans must not coerce into the scheduler's integer knobs.

`config.yaml` legitimately mixes booleans (`enabled: true`) with integer knobs on
neighbouring lines, so a typo like `scheduler.recursion_limit: true` loads
cleanly — and Pydantic coerces it to `1`, which makes every scheduler-launched
run hit the LangGraph recursion ceiling at its first super-step (the same hole
the app-config guard already closes for Gateway runs). `max_concurrent_runs: true`
serializes the scheduler and `poll_interval_seconds: true` polls five times a
second. Mirrors the app-config boolean guard.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.scheduler_config import SchedulerConfig

SCHEDULER_INT_FIELDS = (
    "poll_interval_seconds",
    "lease_seconds",
    "max_concurrent_runs",
    "max_concurrent_runs_per_user",
    "queue_timeout_seconds",
    "min_once_delay_seconds",
    "recursion_limit",
)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", SCHEDULER_INT_FIELDS)
def test_scheduler_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SchedulerConfig(**{field: value})


def test_scheduler_config_keeps_numeric_inputs() -> None:
    config = SchedulerConfig(
        poll_interval_seconds="30",
        max_concurrent_runs=5,
        recursion_limit=500,
    )
    assert config.poll_interval_seconds == 30
    assert config.max_concurrent_runs == 5
    assert config.recursion_limit == 500
